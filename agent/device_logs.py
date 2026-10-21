"""모델이 작성하지 않은 조회 로그를 그대로 표시한다."""


def format_device_logs(result):
    if not result.get("ok"):
        return "장치 로그 조회 실패: " + result.get("error", "로그를 확인하지 못했습니다.")
    entries = result.get("logs", [])
    lines = [f"{result['device_id']} 장치 로그 · 가상 수집 버퍼 · 최근 {len(entries)}건 (시간순)"]
    if not result.get("device_available"):
        lines.append("장치와 현재 통신 가능한 상태가 아닙니다. 수집 버퍼에 남은 기록을 표시합니다.")
    if not entries:
        lines.append("조회 조건에 해당하는 로그가 없습니다.")
    for entry in entries:
        lines.append(f"- {entry['timestamp']} [{entry['level']}] {entry['component']} / {entry['code']}: {entry['message']}")
    lines.append("로그는 관측 기록이며, 기록만으로 고장 원인을 확정하지 않습니다.")
    return "\n".join(lines)
