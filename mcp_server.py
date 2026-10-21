"""all_total 통합 실습 — MCP Server (Wave 2 축).

Tool / Resource / Prompt 3대 capability를 모두 노출하는 실제 fastmcp 서버.
FastAPI 백엔드(server.py)가 lifespan에서 이 파일을 subprocess(stdio)로 1회 기동해
프로세스가 살아 있는 동안 재사용한다 (Wave 1 싱글턴 + Wave 2 표준화의 결합).

- Tool    get_monitoring_status : 호출마다 값이 달라지는 동적 조회 → Tool이 맞다
- Resource runbook://incident-response/{incident_type} : URI로 식별되는 정적 문서
- Prompt  incident_analysis_prompt : 여러 Tool을 조합하는 표준 진단 절차를 강제
"""
import json
import random
from datetime import datetime
from pathlib import Path

from fastmcp import FastMCP
from pydantic import BaseModel, Field

mcp = FastMCP(name="capstone-all-total-ops")

DATA_DIR = Path(__file__).parent / "data"

from agent.iot_simulator import IoTSimulator
from agent.manual_search import ManualIndex
from agent.session_store import SqliteSessionStore

SIMULATOR = IoTSimulator()
MANUAL_INDEX = ManualIndex()

class SystemStatus(BaseModel):
    system_name: str = Field(description="시스템 이름")
    status: str = Field(description="상태: healthy / degraded / down")
    cpu_percent: float = Field(description="CPU 사용률 (%)")
    memory_percent: float = Field(description="메모리 사용률 (%)")
    last_checked: str = Field(description="마지막 체크 시각 (ISO 8601)")
    alerts: list[str] = Field(default_factory=list, description="활성 알림 목록")


@mcp.tool()
def get_monitoring_status(system_name: str) -> SystemStatus:
    """지정된 시스템의 현재 모니터링 상태를 조회합니다 (호출마다 값이 달라지는 동적 Tool)."""
    monitoring_data = json.loads((DATA_DIR / "monitoring.json").read_text())
    if system_name not in monitoring_data:
        return SystemStatus(
            system_name=system_name, status="unknown",
            cpu_percent=0.0, memory_percent=0.0,
            last_checked=datetime.now().isoformat(),
            alerts=[f"System '{system_name}' not found in monitoring"],
        )
    data = monitoring_data[system_name]
    jitter = random.uniform(-3.0, 8.0)
    return SystemStatus(
        system_name=system_name,
        status=data["status"],
        cpu_percent=round(data["cpu_base"] + jitter, 1),
        memory_percent=round(data["memory_base"] + jitter / 2, 1),
        last_checked=datetime.now().isoformat(timespec="microseconds"),
        alerts=data.get("alerts", []),
    )

@mcp.tool()
def list_devices() -> dict:
    """가상 장치 목록과 관측 가능한 현재 상태. 숨겨진 시나리오 정답은 반환하지 않는다."""
    return {"ok": True, "devices": [{"device_id": key, "name": value["name"],
            "available": key not in SIMULATOR.unavailable} for key, value in SIMULATOR.devices.items()]}


@mcp.tool()
def get_device_status(device_id: str) -> dict:
    """장치의 현재 관측 상태를 조회한다."""
    return SIMULATOR.status(device_id)


@mcp.tool()
def get_device_logs(device_id: str, limit: int = 10, level: str | None = None) -> dict:
    """가상 수집 버퍼의 최근 장치 로그를 시간순으로 조회한다. level은 INFO/WARN/ERROR 정확히 일치 필터이며 limit은 1~100이다. 오프라인에서도 기존 버퍼는 조회 가능하다."""
    return SIMULATOR.get_logs(device_id, limit=limit, level=level)


@mcp.tool()
def restart_collection(device_id: str, request_id: str = "") -> dict:
    """허용된 가상 수집 모듈 재시작. 명령 접수와 데이터 복구는 구분한다."""
    return SIMULATOR.restart(device_id, request_id)


@mcp.tool()
def reset_device_scenario(device_id: str) -> dict:
    """가상 장치만 초기 상태로 되돌리고 시나리오 버전을 변경한다. 유지보수 이력은 보존한다."""
    return SIMULATOR.reset(device_id)


@mcp.tool()
def search_iot_manuals(query: str, issues: list[str] | None = None,
                       operating_state: str | None = None, top_k: int = 3) -> dict:
    """IoT 매뉴얼 문단을 BM25로 검색하고 문서·문단 ID·점수·본문·후보 정보를 반환한다."""
    return MANUAL_INDEX.search(query, issues=issues, operating_state=operating_state, top_k=top_k)


@mcp.tool()
def get_maintenance_history(device_id: str, limit: int = 3) -> dict:
    """대화가 아닌 영속 유지보수 이력을 조회한다."""
    store = SqliteSessionStore()
    try:
        history = store.maintenance_history(device_id, limit)
        return {"ok": True, "device_id": device_id, "records": [
            {key: row[key] for key in ("id", "kind", "status", "summary", "updated_at")} for row in history]}
    finally:
        store.close()


@mcp.resource("runbook://incident-response/{incident_type}")
def get_incident_runbook(incident_type: str) -> str:
    """특정 incident 유형의 runbook(정적 문서)을 반환합니다."""
    runbook_path = DATA_DIR / "runbooks" / f"{incident_type}.md"
    if not runbook_path.exists():
        return f"# Runbook Not Found\n\nNo runbook for incident type: {incident_type}"
    return runbook_path.read_text()


@mcp.prompt()
def incident_analysis_prompt(system_name: str, symptom: str) -> str:
    """장애 진단 표준 절차 프롬프트 — planning 노드가 계획을 세울 때 이 절차를 따른다."""
    return f"""다음 장애에 대해 표준 진단 절차를 수행하세요.

## 장애 정보
- 시스템: {system_name}
- 증상: {symptom}

## 진단 절차 (반드시 순서대로 수행)
1. get_monitoring_status Tool로 관련 시스템의 현재 상태를 조회하세요.
2. 증상에 해당하는 runbook(runbook://incident-response/...)을 확인하세요.
3. 위 정보를 종합해 가능한 원인과 권장 조치를 제시하세요.
"""


if __name__ == "__main__":
    try:
        mcp.run(show_banner=False)
    except TypeError:   # 구버전 fastmcp 호환
        mcp.run()
