"""all_total 통합 실습 — FastAPI 백엔드 (Wave 1·3·12·14 축 + 전체 조립).

- Wave 1  : lifespan에서 Agent 번들(MCP 연결·LLM·그래프)을 프로세스당 정확히 1회 생성,
            app.state로 모든 요청이 공유 (creation_count/instance_id로 증명)
- Wave 2  : mcp_server.py를 subprocess(stdio)로 기동해 연결 유지
- Wave 3  : GET /chat/stream — 그래프 실행 과정을 SSE 이벤트로 스트리밍
- Wave 12 : 대화 이력을 SQLite(session.db)에 저장 — 재시작해도 유지
- Wave 14 : SUPERVISOR_VERSION(v1/v2) 환경변수로 legacy/신형 파이프라인 즉시 전환
- LangSmith: 요청당 chat_request 루트 run 아래로 노드·LLM·MCP 호출이 계층 기록됨
"""
import json
import os
import asyncio
import uuid
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()   # LANGCHAIN_TRACING_V2 / API_KEY / PROJECT — import보다 먼저

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree
from pydantic import BaseModel, Field

from agent.deps import SupervisorDeps
from agent.fake_llm import FastLLM, QualityLLM
from agent.iot_graph import build_graph
from agent.mcp_client import MCPClient
from agent.session_store import SqliteSessionStore
from agent.supervisor_v1 import run_v1
from agent.device_rules import assess_device, can_recover

CREATION_COUNT = 0   # Wave 1 — 프로세스 내 Agent 번들 생성 횟수 (항상 1이어야 정상)


class ChatRequest(BaseModel):   # Wave 1 — Pydantic 요청 검증
    message: str
    thread_id: str = "default"

class RecoveryRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=80)
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1, max_length=120)
    scenario_revision: str | None = None
    expected_sequence: int | None = None


class ScenarioRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=80)


def _build_llms():
    """LLM_BACKEND=fake(기본, 결정론) | ollama(로컬 실모델) | openai(실제 OpenAI API)."""
    backend = os.environ.get("LLM_BACKEND", "fake")
    if backend == "ollama":
        from agent.ollama_llm import OllamaFastLLM, OllamaQualityLLM
        fast = OllamaFastLLM(os.environ.get("OLLAMA_FAST_MODEL", "qwen3.5:2b"),
                             usd_per_1k_tokens=0.00015)
        quality = OllamaQualityLLM(os.environ.get("OLLAMA_QUALITY_MODEL", "qwen3.5:2b"),
                                   usd_per_1k_tokens=0.005)
        return backend, fast, quality
    if backend == "openai":
        from agent.openai_llm import OpenAIFastLLM, OpenAIQualityLLM
        fast = OpenAIFastLLM(os.environ.get("OPENAI_FAST_MODEL", "gpt-4o-mini"),
                             usd_per_1k_tokens=0.00015)
        quality = OpenAIQualityLLM(os.environ.get("OPENAI_QUALITY_MODEL", "gpt-4o"),
                                   usd_per_1k_tokens=0.005)
        return backend, fast, quality
    if backend != "fake":
        raise ValueError("LLM_BACKEND는 fake, openai, ollama 중 하나여야 합니다.")
    fast = FastLLM("fast-model-stub", usd_per_1k_tokens=0.00015)
    quality = QualityLLM("quality-model-stub", usd_per_1k_tokens=0.005)
    return backend, fast, quality


@asynccontextmanager
async def lifespan(app: FastAPI):
    global CREATION_COUNT
    CREATION_COUNT += 1
    backend, fast_llm, quality_llm = _build_llms()
    store = SqliteSessionStore()
    mcp = MCPClient(extra_env={"IOT_DB_PATH": str(store.db_path)})
    try:
        await mcp.start()
        app.state.llm_backend = backend
        deps = SupervisorDeps(fast_llm, quality_llm, mcp, store, os.environ.get("SUPERVISOR_VERSION", "v2"))
        app.state.deps = deps
        app.state.graph = build_graph(deps) if deps.version == "v2" else None
        app.state.instance_id = id(deps)
        app.state.recovery_lock = asyncio.Lock()
        yield
    finally:
        await mcp.stop()
        store.close()
        try:
            from langchain_core.tracers.langchain import wait_for_all_tracers
            wait_for_all_tracers()
        except Exception:
            pass


app = FastAPI(lifespan=lifespan)

@app.get("/api/devices")
async def devices():
    return await app.state.deps.mcp.call_tool("list_devices", {})


@app.get("/api/maintenance")
async def maintenance(device_id: str | None = None, limit: int = 20):
    return {"records": app.state.deps.session_store.maintenance_history(device_id, limit)}


@app.post("/api/scenario/reset")
async def reset_scenario(req: ScenarioRequest):
    async with app.state.recovery_lock:
        result = await app.state.deps.mcp.call_tool("reset_device_scenario", {"device_id": req.device_id})
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.post("/api/recover")
async def recover_device(req: RecoveryRequest):
    deps = app.state.deps
    async with app.state.recovery_lock:
        payload = req.model_dump(exclude={"request_id"})
        cached = deps.session_store.reserve_recovery(req.request_id, payload)
        if cached is not None:
            return JSONResponse(cached["body"], status_code=cached["http_status"])

        def finish(body, http_status=200):
            deps.session_store.finish_recovery(req.request_id, body, http_status)
            return JSONResponse(body, status_code=http_status)

        before, command = None, None
        try:
            before = await deps.mcp.call_tool("get_device_status", {"device_id": req.device_id})
            if not before["ok"]:
                return finish({"detail": before["error"]}, 409 if before.get("unavailable") else 404)
            data = before["data"]
            if ((req.scenario_revision is not None and req.scenario_revision != data.get("scenario_revision"))
                or (req.expected_sequence is not None and req.expected_sequence != data.get("telemetry_sequence"))):
                return finish({"detail": "진단 후 상태가 바뀌었습니다. 최신 상태를 다시 점검해 주세요."}, 409)
            command = await deps.mcp.call_tool("restart_collection", {"device_id": req.device_id, "request_id": req.request_id})
            if not command["ok"]:
                return finish({"detail": command["error"]}, 409)
            after = await deps.mcp.call_tool("get_device_status", {"device_id": req.device_id})
            assessment = assess_device(after["data"]) if after["ok"] else None
            verified = (command.get("command_accepted", False)
                        and after["data"]["telemetry_sequence"] > data["telemetry_sequence"]
                        and assessment["status"] == "healthy") if after["ok"] else None
            status = "resolved" if verified else "needs_visit" if verified is False else "verification_pending"
            message = {"resolved": "새 데이터 수신과 정상 상태가 확인됐습니다.",
                       "needs_visit": "명령은 접수됐지만 새 데이터가 없습니다. 현장 점검이 필요합니다.",
                       "verification_pending": "명령은 접수됐지만 상태를 조회하지 못해 복구를 확인할 수 없습니다."}[status]
            result = {"device_id": req.device_id, "request_id": req.request_id, "simulated": True,
                      "before": data, "command": command, "after": after.get("data"),
                      "assessment": assessment, "recovery_verified": verified, "status": status, "message": message}
            result["maintenance_id"] = deps.session_store.record_maintenance(req.device_id, "recovery", status, message,
                                                                               {"request_id": req.request_id, **result})
            return finish(result)
        except Exception:
            logging.getLogger(__name__).exception("가상 복구 처리 중 통신 또는 저장 오류")
            message = "복구 처리 중 오류가 발생했습니다. 실행 여부 확인이 필요하며 자동 재실행하지 않습니다."
            body = {"device_id": req.device_id, "request_id": req.request_id, "recovery_verified": None, "detail": message}
            # pending 요청은 재실행하지 않는다. 저장이 가능하면 불확실한 결과를 영속 기록한다.
            try:
                deps.session_store.record_maintenance(req.device_id, "recovery", "verification_pending", message,
                                                       {"before": before, "command": command, "request_id": req.request_id})
                return finish(body, 502)
            except Exception:
                return JSONResponse(body, status_code=502)

@app.get("/health")
async def health():
    return {"status": "ok", "instance_id": app.state.instance_id,
            "creation_count": CREATION_COUNT,
            "supervisor_version": app.state.deps.version,
            "llm_backend": app.state.llm_backend,
            "fast_llm": app.state.deps.fast_llm.name,
            "quality_llm": app.state.deps.quality_llm.name}


@app.get("/version")
async def version():
    return {"supervisor_version": app.state.deps.version}


def _recovery_offer(result: dict) -> dict | None:
    """모델의 답변 문장이 아닌 조회한 상태로 복구 버튼 표시 여부를 결정한다."""
    device_result = result.get("result") or {}
    device = device_result.get("data") or {}
    issues = (result.get("assessment") or {}).get("issues", [])
    if not (device_result.get("ok") and result.get("device_id")
            and can_recover(device, result.get("assessment"))):
        return None
    return {
        "device_id": result["device_id"],
        "device_name": device.get("name", result["device_id"]),
        "action": "restart_collection",
        "scenario_revision": device.get("scenario_revision"),
        "expected_sequence": device.get("telemetry_sequence"),
        "simulated": True,
    }


def _metadata(result: dict, run_id: str | None) -> dict:
    return {
        "route": result.get("route"),
        "task_count": len(result.get("tasks", [])),
        "gate_removed": result.get("gate_removed", 0),
        "replan_rounds": result.get("replan_rounds", 0),
        "retry_count": result.get("retry_count", 0),
        "parallel_elapsed": result.get("parallel_elapsed"),
        "validation_attempts": result.get("validation_attempts", 0),
        "cost_usd": result.get("cost_usd"),  # IoT 경로는 청구 금액을 추정하지 않는다.
        "answer_source": result.get("answer_source", "rules"),
        "qa": result.get("qa"),
        "generation_attempts": result.get("attempts", 0),
        "maintenance_id": result.get("maintenance_id"),
        "retrieval": {key: value for key, value in result.get("retrieval", {}).items() if key != "documents"},
        "llm_usage": result.get("llm_usage"),
        "llm_error": result.get("llm_error"),
        "llm_backend": app.state.llm_backend,
        "supervisor_version": app.state.deps.version,
        "instance_id": app.state.instance_id,
        "langsmith_run_id": run_id,
    }


@traceable(name="chat_request")
async def _handle_chat(message: str, thread_id: str) -> tuple[dict, str | None]:
    deps = app.state.deps
    history = deps.session_store.load(thread_id)   # Wave 12
    if deps.version == "v2":
        result = await app.state.graph.ainvoke(
            {"query": message, "thread_id": thread_id, "history": history,
             "events": [], "cost_usd": 0.0})
    else:
        result = await run_v1(deps, message, thread_id, history)   # Wave 14
    deps.session_store.append(thread_id, "user", message)
    deps.session_store.append(thread_id, "assistant", result["final"])
    rt = get_current_run_tree()
    return result, (str(rt.id) if rt else None)


@app.post("/chat")
async def chat(req: ChatRequest):
    result, run_id = await _handle_chat(req.message, req.thread_id)
    return {"reply": result["final"], "events": result.get("events", []),
            "sources": result.get("retrieval", {}).get("documents", []),
            "recovery": _recovery_offer(result),
            "metadata": _metadata(result, run_id)}


@app.get("/chat/stream")
async def chat_stream(message: str, thread_id: str = "default"):
    """Wave 3 — 그래프의 노드별 진행 상황을 SSE로 스트리밍.

    이벤트마다 'data: {json}\\n\\n' 형태로 내려보내고 마지막에 data: [DONE] 센티널을
    보낸다 — 프론트엔드는 \\n\\n 경계로 이벤트를 분리해 파싱해야 한다(Wave 3b).
    """
    deps = app.state.deps

    async def gen():
        history = deps.session_store.load(thread_id)
        if deps.version != "v2":
            result = await run_v1(deps, message, thread_id, history)
            for ev in result["events"]:
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'FinalAnswer', 'reply': result['final']}, ensure_ascii=False)}\n\n"
        else:
            seen = 0
            final = ""
            inspection = {}  # SSE에서도 조회 결과를 모아 구조화된 복구 대상을 전달
            last_prompt = None   # finalize까지 살아남은 최종 write/chat 호출의 실제 프롬프트
            # stream_mode를 리스트로 주면 (mode, payload) 튜플이 나온다 — "updates"는
            # 노드가 끝날 때마다의 상태 델타, "custom"은 write_node/chat_answer_node가
            # get_stream_writer()로 실행 중에 즉시 흘려보내는 토큰(AnswerToken) 이벤트다.
            async for mode, payload in app.state.graph.astream(
                    {"query": message, "thread_id": thread_id, "history": history,
                     "events": [], "cost_usd": 0.0}, stream_mode=["updates", "custom"]):
                if mode == "custom":
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    continue
                for node_name, delta in payload.items():
                    if not isinstance(delta, dict):
                        continue
                    for key in ("route", "device_id", "result", "assessment", "answer_source", "llm_usage", "llm_error", "retrieval", "qa", "attempts", "maintenance_id"):
                        if key in delta:
                            inspection[key] = delta[key]
                    for ev in (delta.get("events") or [])[seen:]:
                        ev = {**ev, "node": node_name}
                        yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                    if delta.get("events"):
                        seen = len(delta["events"])
                    if delta.get("final"):
                        final = delta["final"]
                    if delta.get("last_prompt"):
                        last_prompt = delta["last_prompt"]
            yield f"data: {json.dumps({'type': 'FinalAnswer', 'reply': final, 'prompt': last_prompt, 'recovery': _recovery_offer(inspection), 'metadata': _metadata(inspection, None), 'sources': inspection.get('retrieval', {}).get('documents', [])}, ensure_ascii=False)}\n\n"
            deps.session_store.append(thread_id, "user", message)
            deps.session_store.append(thread_id, "assistant", final)
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8100, log_level="warning")
