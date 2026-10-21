import re
from typing import TypedDict

from langgraph.graph import END, StateGraph

from .device_rules import assess_device


class IoTState(TypedDict, total=False):
    query: str
    device_id: str
    result: dict
    assessment: dict
    runbook: str
    final: str


def build_graph(deps):

    # 1. 입력에서 장치 ID를 찾고 상태 조회·판단
    async def inspect_device(state):
        device_ids = list(dict.fromkeys(
            re.findall(r"\bsensor-\d+\b", state["query"].lower())
        ))

        if len(device_ids) != 1:
            return {
                "final": "점검할 장치 ID 하나를 알려주세요. 예: sensor-02"
            }

        device_id = device_ids[0]
        result = await deps.mcp.call_tool(
            "get_device_status",
            {"device_id": device_id}
        )

        if not result["ok"]:
            return {"final": f"{device_id}: {result['error']}"}

        return {
            "device_id": device_id,
            "result": result,
            "assessment": assess_device(result["data"])
        }

    # 2. 현재 준비된 수신 지연 매뉴얼 조회
    async def read_manual(state):
        if state.get("final"):
            return {"runbook": ""}

        if "telemetry_delayed" in state["assessment"]["issues"]:
            runbook = await deps.mcp.read_resource(
                "runbook://incident-response/telemetry_delayed",
                server="ops"
            )
            return {"runbook": runbook}

        return {"runbook": ""}

    # 3. 조회·판단 결과를 채팅 답변으로 정리
    async def write_answer(state):
        if state.get("final"):
            return {"final": state["final"]}

        data = state["result"]["data"]
        issues = state["assessment"]["issues"]

        labels = {
            "low_battery": "배터리 부족",
            "offline": "연결 끊김",
            "telemetry_delayed": "데이터 수신 지연"
        }

        summary = ", ".join(labels[issue] for issue in issues)
        if not issues:
            summary = "설정된 점검 기준에서 이상이 발견되지 않았습니다."

        lines = [
            f"{data['name']} ({state['device_id']})",
            f"점검 결과: {summary}",
            f"배터리: {data['battery_pct']}%",
            f"마지막 수신 이후: {data['telemetry_age_seconds']}초",
            f"전송 주기: {data['report_interval_seconds']}초"
        ]

        if state["runbook"]:
            lines.append("\n참고 매뉴얼:\n" + state["runbook"])

        return {"final": "\n".join(lines)}

    graph = StateGraph(IoTState)

    graph.add_node("inspect_device", inspect_device)
    graph.add_node("read_manual", read_manual)
    graph.add_node("write_answer", write_answer)

    graph.set_entry_point("inspect_device")
    graph.add_edge("inspect_device", "read_manual")
    graph.add_edge("read_manual", "write_answer")
    graph.add_edge("write_answer", END)

    return graph.compile()