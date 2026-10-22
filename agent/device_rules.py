"""제조사 보고 조건을 참고한 판정과 프로젝트 가상 수집기 복구 정책."""
import math

SHELLY_MODEL = "shelly_ht_gen3"
SHELLY_MANUAL_URL = "https://kb.shelly.cloud/knowledge-base/shelly-h-t-gen3"
REPORT_GRACE_SECONDS = 60  # 프로젝트가 정한 수신 여유. 제조사 고장 임계값이 아님.


def _number(value, *, minimum=0):
    return type(value) in (int, float) and math.isfinite(value) and value >= minimum


def assess_device(data: dict) -> dict:
    shelly = data.get("model") == SHELLY_MODEL
    usb = shelly and data.get("power_source") == "usb"
    checks = {"connected": lambda v: isinstance(v, bool),
              "battery_pct": lambda v: (usb and v is None) or (_number(v) and v <= 100),
              "report_interval_seconds": lambda v: _number(v) and v > 0,
              "telemetry_age_seconds": _number}
    invalid = [key for key, check in checks.items() if not check(data.get(key))]
    if shelly:
        if data.get("power_source") not in ("usb", "battery"):
            invalid.append("power_source")
        elif data.get("report_interval_seconds") != (300 if usb else 7200):
            invalid.append("report_interval_seconds")
    if invalid:
        return {"status": "unknown", "issues": ["invalid_data"], "invalid_fields": list(dict.fromkeys(invalid))}
    issues = []
    if not usb and data["battery_pct"] <= 20:
        issues.append("low_battery")
    age = data["telemetry_age_seconds"]
    if shelly:
        interval = 300 if usb else 7200
        deadline = interval + REPORT_GRACE_SECONDS
        # 배터리의 미연결은 보고 기한 안에서는 정상 대기와 양립한다. 실제 절전 확정은 아니다.
        waiting = not data["connected"] and age <= deadline and (
            not usb or (data.get("mode") == "sleeping" and _number(data.get("wake_in_seconds")) and data["wake_in_seconds"] > 0))
        policy = {"basis": "manufacturer_reporting_with_project_grace",
                  "source_url": SHELLY_MANUAL_URL, "max_report_interval_seconds": interval,
                  "grace_seconds": REPORT_GRACE_SECONDS, "delay_after_seconds": deadline,
                  "battery_threshold_origin": "project_policy"}
    else:
        # 이전 입력·일반 데모용 기준. Shelly 사양으로 설명하지 않는다.
        deadline = data["report_interval_seconds"] * 3
        waiting = data.get("mode") == "sleeping" and _number(data.get("wake_in_seconds")) and data["wake_in_seconds"] > 0
        policy = {"basis": "legacy_project_demo", "delay_after_seconds": deadline}
    if not waiting:
        if not data["connected"]:
            issues.append("offline")
        elif age > deadline:
            issues.append("telemetry_delayed")
    return {"status": "needs_attention" if issues else "healthy", "issues": issues,
            "operating_state": "sleeping" if waiting else "active", "reporting_policy": policy}


def can_recover(data, assessment=None):
    assessment = assessment or assess_device(data)
    scoped = data.get("model") != SHELLY_MODEL or (
        data.get("simulated") is True and data.get("recovery_scope") == "simulated_collector")
    battery = data.get("battery_pct")
    power_ok = (data.get("model") == SHELLY_MODEL and data.get("power_source") == "usb") or (
        _number(battery) and battery > 20)
    return (scoped and "telemetry_delayed" in assessment["issues"] and data.get("connected") is True
            and power_ok and "restart_collection" in data.get("supported_actions", [])
            and data.get("recovery_attempts", 0) == 0)


CAUTION = "현재 관측과 검색 문서만으로 고장 원인을 확정할 수 없습니다."
RECHECK_STEP = "상태를 다시 조회해 지연이 계속되는지 확인하세요."
COLLECTOR_RECOVERY_STEP = "가상 복구 버튼으로 수집기 재시작을 요청한 뒤 새 데이터 수신을 확인하세요."


def required_observation_explanation(assessment):
    """오해하면 원인·실제 절전 확정이 되는 관측 조합은 코드 문장으로 제한한다."""
    if assessment.get("operating_state") == "sleeping" and not assessment.get("issues"):
        return "정상 보고 대기 조건 안이며, 실제 절전 여부는 확인되지 않았습니다."
    if {"low_battery", "offline"} <= set(assessment.get("issues", [])):
        return "배터리 잔량 부족과 연결 불가가 함께 관측되었습니다. 두 상태의 인과관계는 확인되지 않았습니다."
    return None


def allowed_guidance(data, assessment, candidates):
    """실행 조건과 검색 문서에서 허용한 안내만 구성한다."""
    if assessment.get("operating_state") == "sleeping" and not assessment["issues"]:
        return ["전원 방식별 정상 보고 조건을 확인하고 다음 보고 기한 이후 새 데이터 수신 여부를 확인하세요."]
    if assessment.get("status") == "healthy":
        return ["연결과 데이터 수신 상태가 달라지는지 확인하세요."]
    if "invalid_data" in assessment["issues"]:
        return ["관측 데이터의 누락과 형식을 확인하고 상태를 다시 조회하세요."]
    if data.get("recovery_attempts", 0):
        steps = ["이미 복구를 시도했으므로 추가 재시작 대신 현장 점검을 진행하세요."]
    elif can_recover(data, assessment):
        steps = [RECHECK_STEP, COLLECTOR_RECOVERY_STEP]
    else:
        steps = ["현장에서 배터리·전원 접점과 연결 상태를 확인하세요.",
                 "연결이 회복되면 새 데이터가 수신되는지 확인하세요."]
    return list(dict.fromkeys(steps + [c["check"] for c in candidates]))
