"""가상 장치의 관측·복구 정책. 임계값은 이 프로젝트의 데모 기준이다."""
def assess_device(data: dict) -> dict:
    checks = {"connected": lambda v: isinstance(v, bool),
              "battery_pct": lambda v: type(v) in (int, float) and 0 <= v <= 100,
              "report_interval_seconds": lambda v: type(v) in (int, float) and v > 0,
              "telemetry_age_seconds": lambda v: type(v) in (int, float) and v >= 0}
    invalid = [key for key, check in checks.items() if not check(data.get(key))]
    if invalid:
        return {"status": "unknown", "issues": ["invalid_data"], "invalid_fields": invalid}
    issues = []
    if data["battery_pct"] <= 20:
        issues.append("low_battery")
    sleeping = data.get("mode") == "sleeping" and isinstance(data.get("wake_in_seconds"), (int, float)) and data["wake_in_seconds"] > 0
    if not sleeping:
        if not data["connected"]:
            issues.append("offline")
        elif data["telemetry_age_seconds"] > data["report_interval_seconds"] * 3:
            issues.append("telemetry_delayed")
    return {"status": "needs_attention" if issues else "healthy", "issues": issues,
            "operating_state": "sleeping" if sleeping else "active"}


def can_recover(data, assessment=None):
    assessment = assessment or assess_device(data)
    return ("telemetry_delayed" in assessment["issues"] and data.get("connected") is True
            and data.get("battery_pct", 0) > 20 and "restart_collection" in data.get("supported_actions", [])
            and data.get("recovery_attempts", 0) == 0)


CAUTION = "현재 관측과 검색 문서만으로 고장 원인을 확정할 수 없습니다."


def allowed_guidance(data, assessment, candidates):
    """실행 정책과 검색 문서에서 허용된 안내만 구성한다. 모델은 여기서 순서를 선택한다."""
    if assessment.get("operating_state") == "sleeping" and not assessment["issues"]:
        return ["예정된 기상 이후 연결과 새 데이터 수신 여부를 확인하세요."]
    if assessment.get("status") == "healthy":
        return ["연결과 데이터 수신 상태가 달라지는지 확인하세요."]
    if "invalid_data" in assessment["issues"]:
        return ["관측 데이터의 누락과 형식을 확인하고 상태를 다시 조회하세요."]
    if data.get("recovery_attempts", 0):
        steps = ["이미 복구를 시도했으므로 추가 재시작 대신 현장 점검을 진행하세요."]
    elif can_recover(data, assessment):
        steps = ["상태를 다시 조회해 지연이 계속되는지 확인하세요.",
                 "가상 복구 버튼으로 재시작을 요청한 뒤 새 데이터 수신을 확인하세요."]
    else:
        steps = ["현장에서 배터리·전원 접점과 연결 상태를 확인하세요.",
                 "연결이 회복되면 새 데이터가 수신되는지 확인하세요."]
    return list(dict.fromkeys(steps + [c["check"] for c in candidates]))
