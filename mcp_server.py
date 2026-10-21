"""가상 IoT 장치 상태·로그·매뉴얼·이력·복구를 제공하는 MCP 서버."""
from fastmcp import FastMCP
from agent.iot_simulator import IoTSimulator
from agent.manual_search import ManualIndex
from agent.session_store import SqliteSessionStore

mcp = FastMCP(name="iot-care-agent")
SIMULATOR = IoTSimulator()
MANUAL_INDEX = ManualIndex()


@mcp.tool()
def list_devices() -> dict:
    """가상 장치 목록과 상태 조회 가능 여부. 숨겨진 시나리오 정답은 반환하지 않는다."""
    return {"ok": True, "devices": [{"device_id": key, "name": value["name"],
            "model": value.get("model"), "model_name": value.get("model_name"),
            "simulated": True, "power_source": value.get("power_source"),
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
def reset_all_device_scenarios() -> dict:
    """등록된 모든 가상 장치 상태·로그를 초기화한다. 유지보수 이력과 요청 중복 방지 기록은 보존한다."""
    return SIMULATOR.reset_all()


@mcp.tool()
def search_iot_manuals(query: str, issues: list[str] | None = None,
                       operating_state: str | None = None, top_k: int = 3,
                       model: str | None = None, power_source: str | None = None) -> dict:
    """공식 문서 기반 한국어 요약과 별도 프로젝트 정책을 BM25로 검색한다. 출처·원문 URL·적용 모델을 반환하며 model 지정 시 다른 모델 문서를 제외한다."""
    return MANUAL_INDEX.search(query, issues=issues, operating_state=operating_state, top_k=top_k, model=model, power_source=power_source)


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


if __name__ == "__main__":
    try:
        mcp.run(show_banner=False)
    except TypeError:   # 구버전 fastmcp 호환
        mcp.run()
