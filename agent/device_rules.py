def assess_device(data: dict) -> dict:
    """장치의 관측값으로 주의가 필요한 상태를 분류합니다."""

    issues = []

    if data["battery_pct"] <= 20:
        issues.append("low_battery")

    if not data["connected"]:
        issues.append("offline")

    elif (
        data["telemetry_age_seconds"]
        > data["report_interval_seconds"] * 3
    ):
        issues.append("telemetry_delayed")

    return {
        "status": "needs_attention" if issues else "healthy",
        "issues": issues
    }