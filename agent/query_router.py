"""IoT 범위의 질문 의도를 구분한다. 명령 실행은 이 라우터에서 하지 않는다."""
import re

# Python의 \b는 한글 조사도 단어 문자로 취급하므로 영문/숫자 경계를 직접 확인한다.
DEVICE_PATTERN = r"(?<![A-Za-z0-9_])sensor-\d+(?![A-Za-z0-9_-])"


def device_ids(query):
    return list(dict.fromkeys(re.findall(DEVICE_PATTERN, query.lower())))


def is_device_discovery(query):
    compact = re.sub(r"\s+", "", query.lower())
    if re.search(r"점검|진단|고장|이상|원인|왜|재시작|복구|배터리|잔량|주기|로그|이력|기록|연결상태", compact):
        return False
    return bool(re.search(r"뭐가|무엇|어떤|무슨|뭐더라|뭐였|뭐야|뭐지|찾|목록|관리하는|담당|설치된|센서.*있|장치.*있", compact))


def find_named_devices(query, devices):
    """등록 이름의 부분 문자열로 검색한다. 주소·관리 구역·동의어는 추측하지 않는다."""
    compact = re.sub(r"\s+", "", query.lower())
    exact = [device for device in devices if device.get("name") and
             re.sub(r"\s+", "", device["name"].lower()) in compact]
    if exact:
        return exact
    generic = {"센서", "장치", "온습도", "온도", "습도", "예약", "절전", "정상", "무선", "유선", "iot"}
    discovery = is_device_discovery(query)
    matches = []
    for device in devices:
        words = re.findall(r"[가-힣]+|[a-z0-9]+", device.get("name", "").lower())
        meaningful = [word for word in words if len(word) >= 2 and word not in generic]
        # 일반 매뉴얼의 '절전' 같은 단어로 특정 장치를 임의 선택하지 않는다.
        if any(word in compact for word in meaningful):
            matches.append(device)
        elif discovery and any(word in compact for word in words if word in generic - {"센서", "장치", "iot"}):
            matches.append(device)
    return matches


def route_query(query, resolved_ids=None):
    explicit_ids = device_ids(query)
    ids = explicit_ids or list(resolved_ids or [])
    compact = re.sub(r"\s+", "", query.lower())
    if len(ids) > 1:
        return "clarify", ids
    wants_logs = bool(re.search(r"로그|logs?", compact))
    if not ids and wants_logs:
        return "clarify", ids
    if not ids:
        if re.search(r"장치목록|센서목록|등록된장치|등록된센서|어떤장치|어떤센서|센서들|장치들", compact):
            return "list_devices", ids
        if re.search(r"점검해(?:줘|주세요|라|$)|진단해(?:줘|주세요|라|$)|재시작해(?:줘|주세요|라|$)|복구해(?:줘|주세요|라|$)|센서.{0,6}(?:이상|고장)|센서점검", compact):
            return "clarify", ids
        if re.search(r"매뉴얼|메뉴얼|배터리|절전|수신|지연|오프라인|게이트웨이|전송|수집|복구|재시작|원인", compact):
            return "manual", ids
        return "help", ids
    if wants_logs and not re.search(r"분석|진단|원인|왜|점검해|재시작|복구", compact):
        return "logs", ids
    if wants_logs:
        return "diagnose", ids
    if re.search(r"이력|기록|지난점검|이전점검|과거|최근조치", compact):
        return "history", ids
    if re.search(r"점검|진단|고장|이상|원인|왜|재시작|복구|안와|안오|멈|끊|부족|방전", compact):
        return "diagnose", ids
    if re.search(r"배터리|잔량|전송주기|수신주기|간격|지원명령|무슨명령|연결상태|지원기능", compact):
        return "status", ids
    if re.search(r"뭐더라|뭐였|뭐야|뭐지|뭐가|무엇|어떤장치|어떤센서|무슨장치|무슨센서|소개|이름|어디|설명", compact) or compact == ids[0]:
        return "device_info", ids
    if resolved_ids and not explicit_ids and not re.search(r"상태|어때", compact):
        return "device_info", ids
    return "diagnose", ids


HELP = """IoT 장치의 소개·상태·점검, 유지보수 이력과 매뉴얼 질문에 답할 수 있어요.
예를 들어 이렇게 물어보세요.
- sensor-02가 뭐더라?
- 복도를 관리하는 센서가 뭐가 있더라?
- 실습실 센서 점검해줘
- sensor-02 배터리 얼마나 남았어?
- sensor-02 점검해줘
- sensor-02 점검 기록 보여줘
- sensor-03 로그 보여줘
- 등록된 장치 목록 보여줘
- 정상 절전과 수신 지연은 어떻게 달라?
복구 명령은 채팅만으로 실행하지 않고 점검 결과의 버튼에서 요청합니다."""
