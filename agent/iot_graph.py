"""IoT 진단 → 매뉴얼 검색 → 원인 후보 설명 → 검수 → 최대 1회 재작성 → 기록."""
import re
from typing import TypedDict
from langgraph.graph import END, StateGraph
from langgraph.config import get_stream_writer
from .device_rules import assess_device
from .manual_search import source_description, SOURCE_FIELDS
from .iot_llm import ExplanationError, render_explanation
from .answer_quality import check_answer
from .query_router import route_query, device_ids, find_named_devices, is_device_discovery, HELP
from .device_logs import format_device_logs


class IoTState(TypedDict, total=False):
    query: str
    route: str
    device_id: str
    result: dict
    assessment: dict
    retrieval: dict
    history: list
    candidates: list
    runbook: str
    draft: dict
    final: str
    answer_source: str
    llm_usage: dict
    llm_error: str
    qa: dict
    attempts: int
    feedback: str
    maintenance_id: str
    device_logs: dict


def build_graph(deps):
    async def load_logs(device_id, limit):
        try:
            return await deps.mcp.call_tool("get_device_logs", {"device_id": device_id, "limit": limit})
        except Exception:
            return {"ok": False, "device_id": device_id, "error": "로그 수집 서버에서 기록을 가져오지 못했습니다."}

    async def inspect_device(state):
        route, ids = route_query(state["query"])
        devices = None
        matched_by_name = False
        if not device_ids(state["query"]):
            try:
                listing = await deps.mcp.call_tool("list_devices", {})
                devices = listing.get("devices", [])
            except Exception:
                if is_device_discovery(state["query"]) and re.search(r"센서|장치|설치|관리|담당", state["query"]):
                    return {"route": "device_search", "answer_source": "device_registry",
                            "final": "등록된 장치 목록을 조회하지 못했습니다. 잠시 후 다시 질문해 주세요."}
            matches = find_named_devices(state["query"], devices or [])
            if len(matches) > 1:
                candidates = "\n".join(f"- {d['device_id']}: {d['name']}" for d in matches)
                if is_device_discovery(state["query"]):
                    return {"route": "device_search", "answer_source": "device_registry",
                            "final": "등록된 이름에서 찾은 가상 장치입니다.\n" + candidates}
                return {"route": "clarify", "answer_source": "clarification",
                        "final": "이름이 일치하는 장치가 여러 개입니다. 점검할 장치 ID 하나를 골라주세요.\n" + candidates}
            if len(matches) == 1:
                ids = [matches[0]["device_id"]]
                route, ids = route_query(state["query"], resolved_ids=ids)
                matched_by_name = True
            elif is_device_discovery(state["query"]) and route != "list_devices" and re.search(r"센서|장치|설치|관리|담당", state["query"]):
                return {"route": "device_search", "answer_source": "device_registry",
                        "final": "질문과 이름이 일치하는 등록 장치를 찾지 못했습니다. 장치 ID를 알려주거나 '등록된 장치 목록 보여줘'라고 물어보세요."}
        if route == "clarify":
            return {"route": route, "answer_source": "clarification", "final": "점검할 장치 ID 하나를 알려주세요. 예: sensor-02"}
        if route == "help":
            return {"route": route, "answer_source": "service_help", "final": HELP}
        if route in ("list_devices", "device_info"):
            if devices is None:
                listing = await deps.mcp.call_tool("list_devices", {})
                devices = listing.get("devices", [])
            if route == "list_devices":
                return {"route": route, "answer_source": "device_registry", "final": "등록된 가상 IoT 장치:\n" + "\n".join(f"- {d['device_id']}: {d['name']}" for d in devices)}
            device = next((d for d in devices if d["device_id"] == ids[0]), None)
            if device is None:
                return {"route": route, "final": f"{ids[0]}: 등록되지 않은 장치입니다."}
            answer = f"{ids[0]}는 '{device['name']}'로 등록된 가상 IoT 장치예요."
            if matched_by_name:
                answer += "\n등록된 장치 이름을 기준으로 찾았습니다. 구체적인 관리 구역은 별도 등록되어 있지 않습니다."
            if "어디" in state["query"] and not matched_by_name:
                answer += "\n구체적인 설치 위치는 별도 등록되어 있지 않아 이름 이상의 위치를 확정할 수 없어요."
            if device.get("model_name"):
                answer += f"\n참고 제품: {device['model_name']} · 전원: {device.get('power_source')} · 실제 제품 연결은 없습니다."
            answer += f"\n현재 상태는 '{ids[0]} 점검해줘', 배터리는 '{ids[0]} 배터리 얼마나 남았어?'라고 물어보세요."
            return {"route": route, "device_id": ids[0], "answer_source": "device_registry", "final": answer}
        if route == "logs":
            logs = await load_logs(ids[0], 10)
            return {"route": route, "device_id": ids[0], "device_logs": logs,
                    "answer_source": "device_logs", "final": format_device_logs(logs)}
        if route == "history":
            listing = await deps.mcp.call_tool("list_devices", {})
            if ids[0] not in {d["device_id"] for d in listing.get("devices", [])}:
                return {"route": route, "final": f"{ids[0]}: 등록되지 않은 장치입니다."}
            result = await deps.mcp.call_tool("get_maintenance_history", {"device_id": ids[0], "limit": 5})
            records = result.get("records", [])
            labels = {"normal": "정상", "open": "점검 필요", "resolved": "복구 확인", "needs_visit": "현장 점검 필요", "verification_pending": "확인 불가"}
            answer = f"{ids[0]}의 최근 유지보수 기록:\n" + ("\n".join(f"- {r['updated_at']} · {labels.get(r['status'], r['status'])}: {r['summary']}" for r in records) if records else "아직 저장된 기록이 없습니다.")
            return {"route": route, "device_id": ids[0], "answer_source": "maintenance_history", "final": answer}
        if route == "manual":
            retrieval = await deps.mcp.call_tool("search_iot_manuals", {"query": state["query"], "top_k": 3})
            docs = retrieval.get("documents", [])
            answer = "매뉴얼에서 찾은 일반 점검 절차예요. 특정 장치의 현재 상태를 점검한 결과는 아닙니다."
            if docs:
                answer += "\n\n" + "\n\n".join(f"[{d['source_id']}] {d['title']} · {d['section']}\n{d['text']}\n{source_description(d)}" for d in docs)
            else:
                answer += "\n관련 근거를 찾지 못했습니다. 증상이나 질문을 더 구체적으로 알려주세요."
            return {"route": route, "answer_source": "manual_search", "retrieval": retrieval, "final": answer}
        result = await deps.mcp.call_tool("get_device_status", {"device_id": ids[0]})
        if not result["ok"]:
            return {"route": route, "final": f"{ids[0]}: {result['error']}"}
        if route == "status":
            data = result["data"]
            query = state["query"]
            lines = [f"{data['name']} ({ids[0]})"]
            if "배터리" in query or "잔량" in query:
                battery = data.get("battery_pct")
                lines.append("배터리 잔량: " + (f"{battery}%" if battery is not None else "미확인"))
            elif "명령" in query or "기능" in query:
                lines.append("등록된 지원 명령: " + (", ".join(data.get("supported_actions", [])) or "없음"))
                lines.append("restart_collection은 가상 수집기 명령이며 실제 Shelly 재부팅 기능이 아닙니다.")
                lines.append("명령 지원 여부와 현재 실행 가능 여부는 다릅니다. 실행 가능 여부는 점검 후 확인하세요.")
            elif "연결" in query:
                lines.append("현재 연결 상태: " + ("연결됨" if data.get("connected") else "연결 끊김"))
            else:
                lines.append(f"최대 보고 간격: {data.get('report_interval_seconds', '미확인')}초")
                if data.get("model_name"):
                    lines.append(f"참고 제품: {data['model_name']} · 전원: {data.get('power_source')}")
                    lines.append("측정 주기와 서버 보고 간격은 다릅니다. 실제 제품 연결 없이 동작 조건을 모사합니다.")
            return {"route": route, "device_id": ids[0], "answer_source": "device_status", "final": "\n".join(lines)}
        return {"route": route, "device_id": ids[0], "result": result, "assessment": assess_device(result["data"])}

    async def retrieve_evidence(state):
        if state.get("final"):
            return {}
        logs = await load_logs(state["device_id"], 5)
        get_stream_writer()({"type": "DeviceLogsRetrieved", "ok": logs.get("ok", False), "count": len(logs.get("logs", []))})
        assessment = state["assessment"]
        issues = assessment["issues"]
        key = "sleeping" if assessment.get("operating_state") == "sleeping" else "healthy"
        query = state["query"] + " " + " ".join(issues or [key])
        try:
            retrieval = await deps.mcp.call_tool("search_iot_manuals", {
                "query": query, "issues": issues, "operating_state": assessment.get("operating_state"), "top_k": 3,
                "model": state["result"]["data"].get("model", "unregistered"),
                "power_source": state["result"]["data"].get("power_source")})
        except Exception:
            retrieval = {"documents": [], "error": "매뉴얼 검색 결과를 확인하지 못했습니다."}
        try:
            history_result = await deps.mcp.call_tool("get_maintenance_history", {"device_id": state["device_id"], "limit": 3})
        except Exception:
            history_result = {"records": []}
        documents = retrieval.get("documents", [])
        candidates, seen = [], set()
        for doc in documents:
            for cause in doc.get("causes", []):
                if cause["id"] not in seen:
                    candidates.append(cause)
                    seen.add(cause["id"])
        runbook = "\n\n".join(f"[{d['source_id']}] {d['title']} / {d['section']}\n{d['text']}" for d in documents)
        get_stream_writer()({"type": "ManualSearchCompleted", "count": len(documents)})
        return {"retrieval": retrieval, "history": history_result.get("records", []),
                "candidates": candidates, "runbook": runbook, "device_logs": logs}

    async def write_answer(state):
        if state.get("final"):
            return {}
        if not hasattr(deps.quality_llm, "explain_device"):
            return {"answer_source": "rules", "qa": {"passed": None, "errors": [], "method": "rules-only"}}
        if not state["retrieval"].get("documents"):
            return {"answer_source": "rules_no_evidence", "qa": {"passed": False, "errors": ["검색 근거 부족"], "method": "retrieval-error"}}
        attempts = state.get("attempts", 0) + 1
        get_stream_writer()({"type": "DeviceExplanationStarted", "attempt": attempts})
        docs = [{key: d.get(key) for key in ("source_id", "title", "section", "text", *SOURCE_FIELDS)}
                for d in state["retrieval"]["documents"]]
        try:
            draft, usage = await deps.quality_llm.explain_device(
                query=state["query"], device_id=state["device_id"], data=state["result"]["data"],
                assessment=state["assessment"], runbook=state["runbook"], documents=docs,
                history=state["history"], device_logs=state.get("device_logs"), cause_candidates=state["candidates"], feedback=state.get("feedback"))
        except ExplanationError as exc:
            return {"answer_source": "rules_fallback", "llm_error": str(exc), "attempts": attempts,
                    "qa": {"passed": False, "errors": [str(exc)], "method": "model-error"}, "draft": {}}
        previous = state.get("llm_usage", {})
        usage = {**usage, **{key: previous.get(key, 0) + usage.get(key, 0)
                            for key in ("input_tokens", "output_tokens", "total_tokens")}}
        return {"draft": draft, "llm_usage": usage, "attempts": attempts, "answer_source": "llm"}

    async def validate_answer(state):
        if state.get("final") or state.get("answer_source") != "llm":
            return {}
        qa = check_answer(state["draft"], device_id=state["device_id"], data=state["result"]["data"],
                          assessment=state["assessment"], documents=state["retrieval"]["documents"], candidates=state["candidates"])
        get_stream_writer()({"type": "AnswerQualityChecked", "passed": qa["passed"], "attempt": state["attempts"]})
        return {"qa": qa, "feedback": " / ".join(qa["errors"])}

    def after_validation(state):
        if state.get("answer_source") == "llm" and not state["qa"]["passed"] and state.get("attempts", 0) < 2:
            return "write_answer"
        return "finalize"

    async def finalize(state):
        if state.get("final"):
            return {}
        data, assessment = state["result"]["data"], state["assessment"]
        labels = {"low_battery": "배터리 부족", "offline": "연결 끊김", "telemetry_delayed": "데이터 수신 지연", "invalid_data": "관측 데이터 확인 필요"}
        issues = assessment["issues"]
        summary = ", ".join(labels[i] for i in issues) if issues else "설정된 점검 기준에서 이상이 발견되지 않았습니다."
        if not issues and assessment.get("operating_state") == "sleeping":
            summary = "정상 절전·보고 대기 조건 안입니다. 실제 절전 여부는 미확인이고 원격 재시작하지 않습니다."
        battery = data.get("battery_pct")
        battery_label = f"{battery}%" if battery is not None else "미확인"
        lines = [f"{data.get('name', state['device_id'])} ({state['device_id']})", f"점검 결과: {summary}",
                 f"배터리: {battery_label}", f"마지막 수신 이후: {data.get('telemetry_age_seconds', '미확인')}초",
                 f"최대 보고 간격: {data.get('report_interval_seconds', '미확인')}초"]
        if data.get("model_name"):
            policy = assessment.get("reporting_policy", {})
            lines.extend([f"참고 제품: {data['model_name']} · 전원: {data.get('power_source')} · 가상 장치",
                          f"보고 판정: 제조사 보고 간격 + 프로젝트 수신 여유 {policy.get('grace_seconds', '미확인')}초",
                          "복구 버튼은 프로젝트 가상 수집기만 재시작합니다. 실제 Shelly 장치를 재부팅하지 않습니다."])
        source = state.get("answer_source", "rules")
        accepted = source == "llm" and state.get("qa", {}).get("passed")
        if accepted:
            lines.append("\n" + render_explanation(state["draft"]))
            selected = set(state["draft"]["candidate_ids"])
            candidates = [c for c in state["candidates"] if c["id"] in selected]
            lines.append("\n설명 모델: " + state["llm_usage"]["model"])
        else:
            candidates = state.get("candidates", [])[:2]
            if source == "llm":
                source = "rules_qa_fallback"
                lines.append("\nLLM 설명이 근거·정책 검수를 통과하지 못해 확인된 상태와 점검 절차로 안내합니다.")
            elif source == "rules_no_evidence":
                lines.append("\n매뉴얼 검색 근거가 부족해 LLM 추측 없이 조회 결과만 안내합니다.")
            elif source == "rules_fallback":
                lines.append("\nLLM 설명을 생성하지 못해 조회 결과와 매뉴얼만 표시합니다. " + state["llm_error"])
            else:
                lines.append("\n설명 방식: 데모 모드 · LLM 미사용")
        if candidates:
            lines.append("\n원인 후보 (검증 전 가능성):")
            for candidate in candidates:
                lines.append(f"- {candidate['title']} [{candidate['source_id']}]\n  추가 확인: {candidate['check']}")
        if not accepted:
            if assessment.get("operating_state") == "sleeping" and not issues:
                lines.append("\n다음 조치: 전원 방식별 보고 조건을 확인하고 다음 보고 기한 이후 새 수신 여부를 확인하세요.")
            elif data.get("recovery_attempts", 0):
                lines.append("\n다음 조치: 이미 복구를 시도했습니다. 추가 재시작 대신 현장 점검이 필요합니다.")
            elif issues:
                lines.append("\n다음 조치: 상태와 매뉴얼을 확인하고, 원격 조치가 불가능하면 현장 점검을 진행하세요.")
            lines.append("\n확인 한계: 관측값만으로 고장 원인을 확정할 수 없습니다.")
        lines.append("\n" + format_device_logs(state.get("device_logs", {"ok": False})))
        docs = state.get("retrieval", {}).get("documents", [])
        if docs:
            lines.append("\n참고 매뉴얼 검색 근거:")
            lines.extend(f"[{d['source_id']}] {d['title']} > {d['section']}\n{source_description(d)}" for d in docs)
        else:
            lines.append("\n검색 근거가 부족합니다. 원인을 확정하지 않고 추가 정보가 필요합니다.")
        if state.get("history"):
            lines.append(f"\n이전 유지보수 기록 {len(state['history'])}건을 참고했습니다.")
        record_id = None
        if deps.session_store is not None:
            status = "normal" if assessment["status"] == "healthy" else "open"
            record_id = deps.session_store.record_maintenance(state["device_id"], "inspection", status, summary,
                {"data": data, "assessment": assessment, "source_ids": [d["source_id"] for d in docs],
                 "manual_index_version": state.get("retrieval", {}).get("index_version"), "manual_sources": docs,
                 "answer_source": source, "qa": state.get("qa"), "query": state["query"], "device_logs": state.get("device_logs")})
        return {"final": "\n".join(lines), "answer_source": source, "maintenance_id": record_id}

    graph = StateGraph(IoTState)
    for name, fn in [("inspect_device", inspect_device), ("retrieve_evidence", retrieve_evidence),
                     ("write_answer", write_answer), ("validate_answer", validate_answer), ("finalize", finalize)]:
        graph.add_node(name, fn)
    graph.set_entry_point("inspect_device")
    graph.add_edge("inspect_device", "retrieve_evidence")
    graph.add_edge("retrieve_evidence", "write_answer")
    graph.add_edge("write_answer", "validate_answer")
    graph.add_conditional_edges("validate_answer", after_validation, {"write_answer": "write_answer", "finalize": "finalize"})
    graph.add_edge("finalize", END)
    return graph.compile()
