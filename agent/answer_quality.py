"""출처 ID·후보·수치·위험한 단정을 검사하는 제한된 코드 검수. 의미 정확성 보증은 아니다."""
import re
from .device_rules import (can_recover, allowed_guidance, CAUTION,
                           required_observation_explanation, RECHECK_STEP, COLLECTOR_RECOVERY_STEP)


def check_answer(answer, *, device_id, data, assessment, documents, candidates):
    errors = []
    source_ids = set(answer.get("source_ids", []))
    known_sources = {doc["source_id"] for doc in documents}
    if not source_ids or not source_ids <= known_sources:
        errors.append("검색된 문단 ID만 source_ids에 인용해야 합니다.")
    guidance = allowed_guidance(data, assessment, candidates)
    if any(step not in guidance for step in answer.get("next_steps", [])) or not answer.get("next_steps"):
        errors.append("next_steps는 현재 상태와 검색 문서에서 허용된 문장 중 선택해야 합니다.")
    steps = answer.get("next_steps", [])
    if len(steps) != len(set(steps)):
        errors.append("next_steps에 동일 조치를 중복하지 마세요.")
    if COLLECTOR_RECOVERY_STEP in steps and (
        RECHECK_STEP not in steps or steps.index(RECHECK_STEP) > steps.index(COLLECTOR_RECOVERY_STEP)):
        errors.append("수집기 재시작을 안내하려면 상태 재조회 문장을 먼저 포함해야 합니다.")
    required = required_observation_explanation(assessment)
    if required and answer.get("explanation") != required:
        errors.append("관측 한계가 중요한 상태입니다. required_explanation 문장을 그대로 사용하세요.")
    # 설명은 관측 사실 전용이다. 인과 추론은 미확정 후보 목록에서만 허용한다.
    explanation = re.sub(r"\s+", "", answer.get("explanation", ""))
    if re.search(r"때문|탓에|인해|인하여|로인한|따라서|그결과|초래|야기|"
                 r"부족(?:하여|해서|으로|하므로|하기에)|낮아서|방전(?:되어|돼서|으로)", explanation):
        errors.append("explanation에서는 동시 관측을 인과관계로 연결하지 말고 관측 사실만 설명하세요.")
    if answer.get("caution") != CAUTION:
        errors.append("caution은 제공된 확인 한계 문장을 그대로 사용해야 합니다.")
    selected = answer.get("candidate_ids", [])
    allowed = {c["id"]: c for c in candidates}
    if len(selected) != len(set(selected)) or any(key not in allowed for key in selected):
        errors.append("검색 근거에 있는 원인 후보 ID만 중복 없이 선택해야 합니다.")
    elif any(allowed[key]["source_id"] not in source_ids for key in selected):
        errors.append("선택한 원인 후보의 출처 문단을 source_ids에 포함해야 합니다.")
    if candidates and not selected:
        errors.append("가능성으로 검토할 원인 후보를 하나 이상 선택해야 합니다.")
    text = " ".join([answer.get("explanation", ""), *answer.get("next_steps", []), answer.get("caution", "")])
    prose_fields = [answer.get("explanation", ""), answer.get("caution", ""), *answer.get("next_steps", [])]
    if (len(re.findall(r"[가-힣A-Za-z]", answer.get("caution", ""))) < 5
        or any(re.search(r'(?:explanation|caution|next_steps|source_ids|candidate_ids)["\']?\s*:', field) for field in prose_fields)
        or any("\n" in step or re.match(r"^\s*\d+[.)]", step) for step in answer.get("next_steps", []))):
        errors.append("문장에 JSON 조각이나 여러 단계·번호를 넣지 말고 확인 한계를 완전한 문장으로 작성하세요.")
    normalized = re.sub(r"\s+", "", text)
    if any(target != device_id for target in re.findall(r"sensor-\d+", text)):
        errors.append("다른 장치의 상태를 설명하면 안 됩니다.")
    bad_claims = [r"전원.{0,12}(?:아닙|문제없|배제할수있)", r"재시작(?:되지않아|하지않아서)",
                  r"고장(?:입니다|이확실|으로확정)", r"(?:복구|재시작)(?:를|가|이)?(?:완료했|완료됐|했습니다)",
                  r"명령(?:을)?실행했", r"고장가능성.{0,5}배제", r"가능성이높",
                  r"수집작업이(?:중단된|멈춘)것으로판단", r"수집작업이정지하고있",
                  r"현재.{0,6}전원공급불안정"]
    if any(re.search(pattern, normalized) for pattern in bad_claims):
        errors.append("원인·원격 실행·복구 완료를 근거 없이 단정하지 마세요.")
    if data.get("model") == "shelly_ht_gen3" and re.search(r"Shelly|실제장치|실제제품", normalized, re.I) and re.search(r"재부팅|재시작", normalized):
        if not re.search(r"않|아니|불가|보류|가상", normalized):
            errors.append("실제 Shelly 장치 재부팅을 가상 수집기 복구와 혼동하면 안 됩니다.")
    if not can_recover(data, assessment):
        for sentence in re.split(r"[.!?。]|\n", text):
            if re.search(r"재시작|restart_collection", sentence) and not re.search(r"않|금지|불가|지원하지|필요없|하지|보류|어렵|권하지", sentence):
                errors.append("현재 상태에서 재시작을 제안할 수 없습니다.")
                break
    # 숫자 표현은 관측값 또는 문서의 값에 한정한다. 문장 의미 전체를 검사하지는 않는다.
    permitted = {"0", "1", "2", "3", "20", "100"}
    for value in data.values():
        if type(value) in (int, float):
            permitted.add(f"{value:g}")
    age, interval = data.get("telemetry_age_seconds"), data.get("report_interval_seconds")
    if type(age) in (int, float):
        permitted.add(f"{age/60:g}")
        if type(interval) in (int, float) and interval > 0:
            permitted.add(f"{age/interval:g}")
    for doc in documents:
        permitted.update(re.findall(r"\d+(?:\.\d+)?", doc["text"]))
    prose = re.sub(r"sensor-\d+", "", text)
    if any(f"{float(number):g}" not in permitted for number in re.findall(r"\d+(?:\.\d+)?", prose)):
        errors.append("입력이나 검색 문단에 없는 수치를 만들지 마세요.")
    return {"passed": not errors, "errors": errors, "method": "reference-and-policy-checks"}
