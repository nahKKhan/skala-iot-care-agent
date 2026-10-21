"""IoT 장치 조회·진단·복구·이력 API와 LangGraph SSE 진행 이벤트."""
import json
import os
import asyncio
import uuid
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()  # 모델·추적 설정을 읽은 뒤 앱 의존성을 생성한다.

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree
from pydantic import BaseModel, Field

from agent.deps import IoTDeps
from agent.fake_llm import RuleBasedLLM
from agent.iot_graph import build_graph
from agent.mcp_client import MCPClient
from agent.session_store import SqliteSessionStore
from agent.device_rules import assess_device, can_recover

CREATION_COUNT = 0  # 프로세스 내 MCP·그래프 초기화 횟수


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"

class RecoveryRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=80)
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1, max_length=120)
    scenario_revision: str | None = None
    expected_sequence: int | None = None


class ScenarioRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=80)


def _build_llm():
    """상태·질문 분류는 코드로 처리하고, 설명 모델만 생성한다."""
    backend = os.environ.get("LLM_BACKEND", "fake")
    if backend == "ollama":
        from agent.ollama_llm import OllamaQualityLLM
        return backend, OllamaQualityLLM(os.environ.get("OLLAMA_QUALITY_MODEL", "qwen3.5:2b"))
    if backend == "openai":
        from agent.openai_llm import OpenAIQualityLLM
        return backend, OpenAIQualityLLM(os.environ.get("OPENAI_QUALITY_MODEL", "gpt-4o"))
    if backend != "fake":
        raise ValueError("LLM_BACKEND는 fake, openai, ollama 중 하나여야 합니다.")
    return backend, RuleBasedLLM()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global CREATION_COUNT
    CREATION_COUNT += 1
    backend, quality_llm = _build_llm()
    store = SqliteSessionStore()
    mcp = MCPClient(extra_env={"IOT_DB_PATH": str(store.db_path)})
    try:
        await mcp.start()
        app.state.llm_backend = backend
        deps = IoTDeps(quality_llm=quality_llm, mcp=mcp, session_store=store)
        app.state.deps = deps
        app.state.graph = build_graph(deps)
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


@app.post("/api/scenario/reset-all")
async def reset_all_scenarios():
    async with app.state.recovery_lock:
        result = await app.state.deps.mcp.call_tool("reset_all_device_scenarios", {})
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail="전체 초기화 결과를 확인하지 못했습니다.")
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
            "pipeline": "iot",
            "llm_backend": app.state.llm_backend,
            "quality_llm": app.state.deps.quality_llm.name}


def _recovery_offer(result: dict) -> dict | None:
    """모델의 답변 문장이 아닌 조회한 상태로 복구 버튼 표시 여부를 결정한다."""
    device_result = result.get("result") or {}
    device = device_result.get("data") or {}
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
        "cost_usd": result.get("cost_usd"),  # IoT 경로는 청구 금액을 추정하지 않는다.
        "answer_source": result.get("answer_source", "rules"),
        "qa": result.get("qa"),
        "generation_attempts": result.get("attempts", 0),
        "maintenance_id": result.get("maintenance_id"),
        "retrieval": {key: value for key, value in result.get("retrieval", {}).items() if key != "documents"},
        "llm_usage": result.get("llm_usage"),
        "llm_error": result.get("llm_error"),
        "llm_backend": app.state.llm_backend,
        "pipeline": "iot",
        "instance_id": app.state.instance_id,
        "langsmith_run_id": run_id,
    }


@traceable(name="chat_request")
async def _handle_chat(message: str, thread_id: str) -> tuple[dict, str | None]:
    deps = app.state.deps
    result = await app.state.graph.ainvoke({"query": message})
    deps.session_store.append(thread_id, "user", message)
    deps.session_store.append(thread_id, "assistant", result["final"])
    rt = get_current_run_tree()
    return result, (str(rt.id) if rt else None)


@app.post("/chat")
async def chat(req: ChatRequest):
    result, run_id = await _handle_chat(req.message, req.thread_id)
    return {"reply": result["final"], "device_id": result.get("device_id"),
            "sources": result.get("retrieval", {}).get("documents", []),
            "device_logs": result.get("device_logs"),
            "recovery": _recovery_offer(result),
            "metadata": _metadata(result, run_id)}


@app.get("/chat/stream")
async def chat_stream(message: str, thread_id: str = "default"):
    """IoT 그래프 진행 이벤트와 최종 답변을 SSE로 전달한다."""
    deps = app.state.deps

    async def gen():
        result = {}
        async for mode, payload in app.state.graph.astream(
                {"query": message}, stream_mode=["updates", "custom"]):
            if mode == "custom":
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                continue
            for delta in payload.values():
                if isinstance(delta, dict):
                    result.update(delta)
        final = {"type": "FinalAnswer", "reply": result["final"], "device_id": result.get("device_id"),
                 "recovery": _recovery_offer(result), "metadata": _metadata(result, None),
                 "sources": result.get("retrieval", {}).get("documents", []),
                 "device_logs": result.get("device_logs")}
        yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
        deps.session_store.append(thread_id, "user", message)
        deps.session_store.append(thread_id, "assistant", result["final"])
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8100, log_level="warning")
