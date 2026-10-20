# IoT Care Agent 직접 구현 가이드

> 주제: **IoT 장치 장애 진단 및 원격 복구 지원 AI 에이전트**  
> 목적: 기존 모니터링 결과에 장치 매뉴얼과 점검 이력을 연결하여, 점검 순서 선택 → 지원되는 복구 조치 → 결과 확인 → 유지보수 기록을 진행한다.  
> 이 문서는 앞으로 직접 구현할 작업을 정리한 계획이다. 아래에 제안한 파일·API·MCP 도구는 아직 구현된 기능이 아니다.

## 0. 지금 폴더의 상태

- `../all_total_vue_student/`: 제공받은 원본. 수정하지 않았다.
- 현재 `iot-care-agent/`: 원본을 복사한 작업 폴더. 서비스 소스는 아직 원본과 동일하다.
- 현재 폴더에 `.venv`는 생성했으나, 사용자의 중단 요청으로 패키지 설치는 취소했다. 설치 완료 상태로 가정하지 않는다.
- 서비스 실행·IoT 코드 구현·Git 초기화·커밋·GitHub 푸시는 수행하지 않았다.
- 다음 작업은 이 문서를 읽고 **1단계의 기존 코드 실행부터 직접 진행하는 것**이다.

기준 자료: [신규 서비스 변경 안내](doc/manual_change.md), [기존 구조 설명](doc/README.md), 상위 폴더의 과제 안내 PDF.

## 1. 먼저 완성할 서비스의 범위

### 한 문장 설명

“센서 데이터가 끊겼을 때, 상태·매뉴얼·이력을 조회해 점검 방법을 제안하고, 원격 복구가 가능한 경우 결과까지 확인하는 서비스.”

### 첫 버전의 핵심 기능 네 가지

1. 장치의 현재 상태와 최근 수신 기록 조회
2. 장애 후보·정상 절전 구분 및 대응 매뉴얼·과거 이력 조회
3. 가상 장치의 `restart_collection` 명령 실행 및 데이터 수신 재확인
4. 복구 결과 또는 현장 점검 필요 사항 기록

**가상 센서 5개와 복구 명령 1개로 시작한다.** 첫 버전을 완성한 뒤 게이트웨이 공통 장애·장치 여러 개 일괄 점검 등을 추가한다.

처음부터 필요한 기술을 늘릴 필요는 없다. 기존 LangGraph·FastMCP·FastAPI·Vue 구조를 활용하고, LangSmith는 흐름과 평가 기록에 사용한다. Qdrant, 고장 예측 모델 학습, 실제 BLE 연결은 초기 완료 조건에 포함하지 않는다.

### 이 프로젝트에서의 에이전트 역할

- Python 규칙: 시간 차이·배터리 임계값 계산, 명령 허용 여부, 복구 성공 조건 검증
- LLM: 사용자 요청 해석, 부족한 정보 질문, 관련 매뉴얼·이력 해석, 근거에 따른 점검 순서와 설명 생성
- LangGraph: 다음 조회·복구·확인·현장 점검 분기와 실행 횟수 관리
- 시뮬레이터: 관측 데이터와 가상 명령 결과 제공

단순히 수치에 따라 정해진 문장만 출력하는 단계는 먼저 만드는 기반이다. 실제 LLM까지 연결한 최종 버전과 구분해서 설명한다.

## 2. 기존 코드에서 읽을 파일과 바꿀 부분

아래 순서로 읽으면 전체 흐름을 이해하기 쉽다.

| 순서 | 기존 파일 | 확인할 것 / 구현할 변경 |
|---|---|---|
| 1 | `doc/manual_change.md` | 신규 서비스 변경 범위와 제출물 |
| 2 | `server.py` | lifespan에서 MCP·모델·세션을 한 번 만들고 요청을 그래프에 전달하는 구조 |
| 3 | `agent/graph.py` | route → plan → research → write 흐름과 이벤트. IoT 진단·복구 확인 흐름으로 변경 |
| 4 | `mcp_server.py` | Tool·Resource·Prompt 등록. CPU·메모리 조회를 장치 상태·이력·복구 도구로 교체 |
| 5 | `agent/mcp_client.py` | 별도 프로세스의 MCP 서버 호출 및 응답 파싱 |
| 6 | `agent/fake_llm.py` | 외부 API 없이 동작하는 테스트 대역. IoT용 입력·출력 형식으로 변경 |
| 7 | `agent/openai_llm.py`, `agent/ollama_llm.py` | fake와 동일한 메서드·출력 형식을 지키며 IoT 프롬프트 적용 |
| 8 | `agent/deps.py`, `agent/session_store.py` | 의존성 주입·대화 이력 재사용. 유지보수 이력은 별도 데이터로 설계 |
| 9 | `web_chat.html` | 제목·예시 질문·결과 표시·실행 이벤트·복구 버튼 변경 |
| 10 | `web_demo_server.py` | 프런트에서 새 API를 쓰면 해당 프록시도 추가 |
| 11 | `sh/`, `.env.example` | 새 서비스명·실행 설정·DB 보존 정책 반영 |

### 먼저 표시해 둘 기존 실습 코드의 특징

- `agent/graph.py`의 `_extract_system_name()`과 LLM 파일들은 대상이 없으면 `auth-service`를 선택한다. 새 서비스에서는 **대상이 없으면 질문**하고, 없는 장치 ID를 실제 장치로 바꿔서 처리하지 않는다.
- `KNOWN_SYSTEMS`, `data/monitoring.json`, `_INCIDENT_TYPE_RULES` 등은 기존 웹 서비스 장애 도메인이다. 파일명만 바꾸지 말고 참조하는 곳까지 검색한다.
- `agent/fake_llm.py`의 route 정규식은 현재 `점검`, `센서`, `배터리` 등을 충분히 인식하지 못한다. IoT 질의도 진단 경로로 들어가게 수정한다.
- `mcp_client.py`에는 첫 조회를 일부러 타임아웃시키는 로직이 있다. `graph.py`에는 고정 지연, 불필요한 analysis 태스크, 일부러 짧은 초안이 포함된다. 실습 연출이므로 신규 서비스에서 유지할지 명시적으로 결정한다.
- 기존 `validate_node`는 여러 번 실패하면 초안을 통과 처리한다. IoT의 복구 성공 여부는 응답 길이가 아닌 **관측 데이터**로 검사한다.
- MCP의 `docs` 서버는 탐색 실습용 decoy다. 첫 버전에서는 `ops` 하나만 사용해도 된다.
- `SUPERVISOR_VERSION=v1`은 예전 도메인 파이프라인이다. 우선 v2만 사용하고 v1은 비활성화하거나 제거하는 방향을 선택한다.
- 기존 OpenAI·Ollama 실행 스크립트는 `session.db`를 지우고 포트의 프로세스를 강제 종료한다. 유지보수 이력을 남길 때는 복사본에서 이 동작을 조정한다.
- `manual_change.md`에는 `run.sh`가 나오지만 이 배포 폴더에는 없다. 아래의 실제 존재하는 명령을 사용한다.
- fake 백엔드의 비용은 가상의 계산값이다. 실제 LLM 호출 비용으로 발표하지 않는다.

찾아볼 때의 예시:

```bash
rg 'auth-service|web-01|KNOWN_SYSTEMS|get_monitoring_status|incident_analysis_prompt' agent server.py mcp_server.py
```

## 3. Git부터 준비하기

이하 명령은 **`iot-care-agent` 폴더 안에서** 실행한다. GitHub 저장소가 현재 폴더의 상위에 이미 있다면, 새 저장소를 중첩해서 만들지 말고 저장소 경계부터 확인한다.

```bash
cd iot-care-agent
pwd
git rev-parse --show-toplevel
```

마지막 명령이 “not a git repository”라면 이 폴더에 초기화한다.

```bash
git init -b main
```

`.gitignore`를 확인하고 다음 항목을 추가한다. `.env.example`은 실제 비밀값 없이 공유한다.

```gitignore
.env
.env.*
!.env.example
.venv/
__pycache__/
*.pyc
*.log
*.db
*.db-shm
*.db-wal
runtime/
.DS_Store
```

기준 코드를 먼저 커밋한다. `git diff --cached`로 올릴 내용을 확인한다.

```bash
git status --short
git add .
git diff --cached --stat
git diff --cached
git commit -m "chore: preserve starter code and add implementation guide"
```

GitHub에서 빈 저장소를 만든 다음 아래 URL을 **본인 저장소 URL로 바꿔서** 연결한다. 이미 `origin`이 있으면 `git remote -v`로 주소부터 확인한다.

```bash
git remote add origin https://github.com/YOUR_GITHUB_ID/iot-care-agent.git
git push -u origin main
```

이후에는 기능 하나가 동작할 때마다 다음을 반복한다.

```bash
git status --short
git add 수정한파일경로
git diff --cached
git commit -m "feat: describe the completed change"
git push
```

아래 단계별 커밋 예시는 실제로 해당 기능을 구현하고 확인한 뒤 사용한다. 기준 코드는 제공받은 프로젝트라는 점과 직접 변경한 부분을 최종 README에 구분해 적는다.

## 4. 단계별 구현 순서

### 1단계. 기존 프로젝트 실행과 기준 결과 보관

**목표:** IoT로 바꾸기 전에 백엔드·MCP·화면이 어떻게 연결되는지 확인한다.

1. 중단된 설치를 다시 진행한다.

```bash
bash sh/setup_venv.sh
.venv/bin/python --version
.venv/bin/python -c "import fastapi, langgraph, fastmcp, mcp, langsmith; print('imports OK')"
```

2. 터미널 A에서 기존 fake 모드를 실행한다. fake 점검에는 OpenAI 키가 필요하지 않다.

```bash
LLM_BACKEND=fake SUPERVISOR_VERSION=v2 LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false .venv/bin/python server.py
```

3. 터미널 B도 같은 폴더에서 프런트엔드를 실행한다.

```bash
.venv/bin/python -m uvicorn web_demo_server:app --host 127.0.0.1 --port 8600
```

4. 브라우저에서 `http://localhost:8600`, 또는 터미널 C에서 다음을 확인한다.

```bash
curl -s http://127.0.0.1:8100/health
curl -s -X POST http://127.0.0.1:8100/chat -H 'Content-Type: application/json' -d '{"message":"web-01 CPU 급증 원인 진단해줘","thread_id":"baseline-01"}'
```

**완료 기준:** `/health`가 fake를 표시하고 기존 진단 답변이 나온다. 응답 JSON·스크린샷과 패키지 버전을 보관한다.

의존성 설치 후에 버전 목록도 기록한다. 원본 requirements는 하한만 지정해 최신 major 버전까지 설치될 수 있으므로, 호환 문제가 생기면 실제 오류를 확인하고 수정한 버전을 잠근다.

```bash
.venv/bin/python -m pip freeze > requirements-lock.txt
```

**커밋:** `chore: document working baseline and dependency versions`

### 2단계. 가상 장치 데이터와 정답 시나리오 만들기

**목표:** AI 없이도 장치 상태를 조회하고, 정상·장애·복구 결과를 재현할 수 있게 한다.

새로 만들 파일의 예:

```text
data/devices.json          # 장치 구성·초기 관측값
data/scenarios.json        # 시나리오별 초기 상태·명령 결과
data/maintenance_seed.json # 과거 점검 예시
data/runbooks/             # IoT 대응 절차
iot_simulator.py           # 상태 조회·명령 적용·초기화
```

장치의 관측 데이터 예시:

```json
{
  "device_id": "sensor-01",
  "name": "실습실 온습도 센서",
  "location": "실습실 A",
  "model": "demo-env-sensor",
  "connected": true,
  "battery_pct": 80,
  "report_interval_seconds": 60,
  "last_telemetry_at": "2026-10-20T10:00:00+09:00",
  "telemetry_sequence": 101,
  "mode": "active",
  "next_wake_at": null,
  "supported_actions": ["restart_collection"]
}
```

먼저 준비할 시나리오:

| ID | 상황 | 기대 행동 |
|---|---|---|
| S1 | 정상 전송 | 정상 안내, 복구 명령 없음 |
| S2 | 예정된 절전, 다음 전송 시각 이전 | 정상 절전 안내, 복구 명령 없음 |
| S3 | 배터리 부족으로 오프라인 | 현장 배터리 점검 제안, 원격 재시작 없음 |
| S4 | 연결은 됐지만 데이터 수집 중단 | 수집 모듈 재시작 제안, 실행 후 새 데이터 확인 |
| S5 | 재시작 명령은 접수됐지만 데이터 미복구 | 성공으로 보고하지 않고 현장 점검 기록 |

데이터 설계 시 지킬 것:

- 배터리 임계값과 전송 지연 허용치는 **프로젝트의 데모 정책**으로 정의한다. 모든 실제 장치에 통용되는 값이라고 설명하지 않는다.
- 정상 절전을 구분하려면 예상 전송 주기·다음 기상 시각이 있어야 한다.
- 정답인 `expected_issue`와 가상 명령의 성공·실패 설정은 시뮬레이터·평가용으로 분리한다. 진단할 때 LLM에 정답이나 성공 여부를 미리 주지 않는다.
- 초기 데이터와 변경된 상태를 분리한다. 초기 JSON은 Git에 넣고, 실행 상태는 `runtime/` 또는 SQLite에 저장한다.
- 고정된 가상 시각을 쓰거나 시간 진행 규칙을 둔다. 오래된 고정 timestamp를 실제 현재 시각과 비교해서 시작하자마자 모든 장치가 장애가 되지 않게 한다.
- 같은 시나리오를 다시 시작하면 같은 결과가 나와야 한다.

**완료 기준:** S4에서는 명령 후 sequence·수신 시각이 바뀌고, S5에서는 명령 접수만 되고 새 데이터가 생기지 않는다.

**커밋:** `feat: add deterministic IoT simulation scenarios`

### 3단계. MCP 도구를 IoT용으로 바꾸기

**수정 대상:** `mcp_server.py`, `agent/mcp_client.py`.

처음에는 다음 도구를 구현한다. 반환 형식은 dict/JSON 등 일관된 형태로 맞춘다.

| 제안하는 도구 | 입력 | 반환할 내용 |
|---|---|---|
| `list_devices` | 없음 | 조회 가능한 장치 ID·이름 |
| `get_device_status` | `device_id` | 상태·전송 주기·수신 시각·sequence |
| `get_maintenance_history` | `device_id` | 실제로 저장된 점검·조치 이력 |
| `execute_recovery` | `device_id`, `action`, `request_id` | 명령 접수 여부, 실행 전 상태, 결과 조회에 쓸 식별자 |
| `record_maintenance` | `device_id`, 진단·조치·확인 결과 | 저장한 작업 ID와 상태 |

메모:

- `execute_recovery`는 시뮬레이터만 변경한다. 실제 장치·네트워크로 명령을 보내는 기능으로 설명하지 않는다.
- 지원하지 않는 명령, 없는 장치, 통신 불가 장치의 원격 조치를 코드에서 거부한다.
- 같은 `request_id`를 다시 받아도 재시작을 중복 실행하지 않게 한다. 타임아웃 때도 우선 이전 요청 결과를 확인한다.
- `acknowledged=true`와 `recovered=true`는 구분한다. 복구 판정은 이후 상태 조회로 수행한다.
- 읽기 조회의 일시적 실패 재시도와, 상태를 바꾸는 명령의 재실행 정책을 구분한다.
- MCP 호출 결과의 오류 표시와 JSON 파싱 실패를 처리한다. 첫 text가 항상 정상 JSON이라고 가정하지 않는다.

**완료 기준:** MCP client를 통해 실제로 조회·가상 명령·이력 저장이 가능하고, 잘못된 대상·명령이 오류로 반환된다.

**커밋:** `feat: expose IoT status and recovery through MCP`

### 4단계. 그래프를 먼저 진단까지만 연결하기

**수정 대상:** `agent/graph.py`, `agent/fake_llm.py`, 필요 시 `agent/deps.py`.

먼저 진단 경로를 완성한다.

```text
사용자 요청
  → 대상 장치 확인
  → 장치 상태·점검 이력 조회
  → 관련 대응 매뉴얼 조회
  → 정상/절전/장애 후보 판단
  → 근거와 다음 점검 제시
```

분기 기준:

- 장치가 명시되지 않으면 목록을 보여주거나 추가 질문한다.
- 없는 ID는 “조회되지 않는 장치”로 처리한다.
- 정보가 부족하면 확인할 항목을 제시한다. 추측한 데이터를 채우지 않는다.
- 정상·정상 절전은 복구 경로로 보내지 않는다.
- 배터리 교체 등 물리 작업은 원격 명령 대상으로 삼지 않는다.

fake 모델에서도 IoT용 인터페이스를 맞추고, 위 시나리오가 끝까지 흐르게 만든다. 기존의 강제 실패·가상 비용·고정 지연을 정리한다.

**완료 기준:** “sensor-01 점검해줘”, “센서가 이상해요”, “없는 장치 점검해줘”가 각각 진단·질문·대상 오류로 처리된다.

**커밋:** `feat: implement IoT diagnosis graph and clarification`

### 5단계. 대응 매뉴얼과 실제 LLM 연결하기

**목표:** 데이터 조회 결과에 맞는 근거를 제시하고, 실제 모델도 같은 도구·상태 형식을 사용하게 한다.

먼저 `data/runbooks/`에 다음 문서를 직접 작성한다.

- `normal-sleep.md`: 정상 절전과 전송 지연 구분 기준
- `low-battery.md`: 배터리 상태 확인·현장 점검 절차
- `telemetry-stall.md`: 연결은 있으나 데이터가 갱신되지 않을 때의 점검·재시작 절차

각 문서에는 적용 조건, 필요한 조회, 허용 조치, 복구 확인 기준을 적는다. 처음에는 관련 문서를 ID로 조회해도 된다. 키워드·벡터 등 **검색 로직을 구현하고 검색 결과를 생성에 사용했을 때** RAG 기능으로 설명한다. Qdrant는 필수로 추가하지 않는다.

`openai_llm.py`, `ollama_llm.py`에서 기존 ICT 운영 프롬프트와 `auth-service` 기본값을 제거하고 다음을 반영한다.

- 장치·관측값·문서에 없는 원인을 확정하지 않기
- 확인된 사실, 원인 후보, 추가 점검을 구분하기
- 명령 실행 결과 없이 실행했다고 말하지 않기
- 명령 접수만으로 복구됐다고 말하지 않기
- 원격 조치 허용 여부는 코드가 결정하고 모델의 문장으로 우회하지 못하게 하기

실제 LLM은 OpenAI 또는 Ollama 중 **한 경로를 먼저** 확인한다. `.env.example`을 `.env`로 복사해 필요한 본인 설정을 입력하고, 실제 모델의 이름과 연결 상태는 기존 매뉴얼을 참고한다. OpenAI 모드는 요청에 따라 과금된다. API 키는 프런트엔드 코드에 넣지 않는다.

기존 실행 스크립트를 쓰기 전 DB 삭제·포트 강제 종료·프로젝트명 덮어쓰기 부분을 확인한다. 유지보수 이력 보존을 위해 초기에는 직접 `server.py`를 실행하는 편이 이해하기 쉽다.

**완료 기준:** 선택한 실제 모델로 정상·장애·대상 누락 각 1건을 실행하고, 근거가 없는 사실이나 복구 결과를 만들어내지 않는지 확인한다.

**커밋:** `feat: ground IoT diagnosis in manuals and model prompts`

### 6단계. 복구 실행·재확인·이력 저장 붙이기

진단이 완성되면 다음 경로를 추가한다.

```text
진단 결과에 복구 방법 제시
  → 사용자의 실행 요청
  → 현재 상태·허용 명령 재확인
  → 가상 복구 명령 실행
  → 상태와 새 데이터 재조회
  → 복구 확인 또는 현장 점검 필요
  → 유지보수 기록 저장
```

별도의 복잡한 HITL 시스템부터 만들 필요는 없다. 첫 버전에서는 화면의 “시뮬레이션 복구 실행” 버튼과 POST API로 실행 의사를 구분한다.

**API 설계 제안:**

| API | 용도 |
|---|---|
| `GET /api/devices` | 장치 목록·상태 조회 |
| `POST /chat` | 기존 방식의 진단 요청 |
| `POST /api/recover` | 지정 장치에 허용된 가상 복구 실행 |
| `GET /api/maintenance` | 유지보수 기록 조회 |
| `POST /api/scenario` | 데모 상태 초기화·변경 |

주의할 구현 지점:

- 기존 `GET /chat/stream`은 조회·설명에 사용하고 복구 실행을 연결하지 않는다. 이벤트 스트림 재연결만으로 명령이 실행되지 않게 한다. 변경 작업은 POST로 분리한다.
- 요청에 장치 ID·명령·중복 방지용 request ID를 넣고 서버에서 재검증한다. 진단 후 상태가 바뀌었으면 재진단한다.
- 한 진단에서의 자동 복구 시도는 우선 1회로 제한한다. 실패했을 때 무한 재시작 루프를 만들지 않는다.
- 성공 조건: 명령 실행 전보다 **새로운 sequence와 수신 시각**이 관측되고, 정의한 정상 조건을 만족하는지 확인한다.
- 재조회에 실패하면 “확인 불가”로 남긴다. 실제로 미복구가 확인된 경우와 구분한다.
- 이전 문장에 장치 이름이 있었다는 이유만으로 다른 장치를 재시작하지 않는다. 실행 대상은 요청과 현재 조회 결과로 확정한다.

이력에는 장치 ID, 발생 증상, 조회한 근거, 조치, 실행 전후 관측값, 결과, 생성·갱신 시각을 저장한다. 상태 예시는 `open`, `resolved`, `needs_visit`, `verification_pending`이다.

대화 메모리와 유지보수 이력은 용도가 다르다. 서버 재시작 뒤에도 점검 기록은 유지하고, 여러 번 점검했다고 동일한 열린 작업이 계속 생기지 않도록 갱신 기준을 정한다. 시나리오를 바꾸면 이전 작업·복구 요청과 섞이지 않게 시나리오 ID를 함께 저장한다.

**완료 기준:** S4는 새 데이터가 확인돼 종료되고, S5는 현장 점검 필요로 남는다. 같은 요청을 두 번 보내도 명령은 한 번만 실행된다.

**커밋:** `feat: verify simulated recovery and persist maintenance records`

### 7단계. 화면과 실행 이벤트 연결하기

**수정 대상:** `web_chat.html`, `web_demo_server.py`, `server.py`.

첫 화면에는 다음만 있으면 된다.

- 서비스 제목과 “가상 장치 시뮬레이션” 표시
- 장치 목록 또는 선택 항목
- 채팅과 예시 질문
- 조회·매뉴얼 확인·복구·재확인 진행 단계
- 진단 결과와 복구 실행 버튼
- 최근 점검 기록
- 시나리오 초기화 버튼

기존 SSE 이벤트 이름을 바꾸면 `STEP_LABELS`와 최종 응답 처리도 함께 수정한다. 새 API를 백엔드에만 만들면 8600 프런트에서 호출되지 않을 수 있으므로 프록시를 함께 연결한다.

추가 확인 사항:

- fake는 “데모 / LLM 미사용”, OpenAI·Ollama는 실제 선택한 모델로 표시한다.
- 실패·통신 오류가 나도 로딩 표시와 실행 중 버튼이 원상 복구돼야 한다.
- 초기화 후 이전 진단의 복구 버튼은 다시 사용할 수 없게 한다.
- 기존 Vue는 CDN을 사용하므로 발표 환경의 인터넷 연결도 확인한다.

**완료 기준:** 브라우저에서 S1~S5의 점검·복구·기록을 끝까지 시연할 수 있다.

**커밋:** `feat: add IoT diagnosis and maintenance interface`

### 8단계. 기능 검증과 결과 정리

최소한 아래 경우를 확인하고 실제 결과를 `doc/test_results.md`에 기록한다. 아래는 아직 수행하지 않은 테스트 목록이다.

| 테스트 | 기대 결과 |
|---|---|
| 정상 장치 점검 | 정상 안내, 복구 0회 |
| 정상 절전 장치 | 장애 오인·재시작 없음 |
| 배터리 부족 장치 | 배터리·현장 점검 안내 |
| 수집 중단 → 복구 성공 | 명령 후 새 데이터 확인, resolved 기록 |
| 명령 접수 → 새 데이터 없음 | 성공 오판 없이 needs_visit 기록 |
| 복구 후 재조회 오류 | verification_pending 또는 확인 불가 |
| 없는 장치 / 대상 없는 요청 | 대상 오류 / 추가 질문 |
| 지원하지 않는 명령 | 실행 거부 |
| 같은 request ID 재전송 | 복구 중복 실행 없음 |
| 시나리오 초기화 후 오래된 요청 | 이전 요청 실행 거부 또는 재진단 |
| 서버 재시작 | 유지보수 기록 유지 |
| 모델 응답 누락·잘못된 형식 | 잘못된 명령 실행 없이 오류·질문 처리 |

상태 분류·복구 결과 판정·중복 실행 방지는 작은 Python 테스트로 확인하면 좋다. 표준 `unittest`를 쓰면 별도 테스트 패키지 없이 시작할 수 있다. LangGraph/MCP 통합과 UI 흐름도 별도로 확인한다.

```bash
.venv/bin/python -m unittest discover -s tests -v
```

이 명령은 `tests/`와 테스트를 작성한 이후 사용한다.

비교 평가를 한다면 **같은 IoT 시나리오와 입력**에서 비교한다. 기존 웹 서버용 코드를 그대로 돌리고 IoT 정확도와 비교하는 방식은 피한다.

- Baseline 예: 연결 여부·수신 지연만으로 알림을 주는 간단한 기준
- 개선 버전: 절전 일정·매뉴얼·이력을 확인하고 조치 결과까지 검증
- 지표 예: 정상 절전 오경보 수, 올바른 대응 분기 비율, 복구 성공 오판 수, 불필요한 재시작 수
- 처리 시간과 실제 도구 호출 횟수도 기록한다. 개선 후 느려졌다면 추가 조회에 따른 비용으로 설명한다.

결정론적 시뮬레이터 테스트와 실제 LLM 평가 결과는 분리한다. fake 모드의 성공률을 실제 모델 성능으로 주장하지 않는다. LangSmith는 그래프·모델·MCP 호출 흐름을 추적하고 평가 결과를 남기는 데 사용한다.

**커밋:** `test: cover recovery outcomes and maintenance scenarios`

## 5. 3일 작업 순서 예시

| 시점 | 우선 작업 | 그날 끝날 때 보여줄 수 있어야 할 것 |
|---|---|---|
| Day 1 | 기준 코드 실행, Git 연결, 가상 데이터·MCP 조회, 진단 흐름 | 장치 ID를 입력하면 해당 상태와 대응 근거가 나옴 |
| Day 2 | 실제 LLM 1개 경로 확인, 가상 복구·재확인·이력 | 성공·실패·현장 점검 필요를 구분함 |
| Day 3 오전 | UI 연결, 예외·중복 요청 검사, 결과 기록 | 처음부터 끝까지 끊기지 않는 시연 |
| Day 3 마무리 | README·비교 결과·발표 준비, 최종 커밋·푸시 | 실행 방법·구현 범위·테스트·한계를 설명할 수 있음 |

시간이 부족하면 게이트웨이 공통 장애, 배터리 수명 예측, 복잡한 대시보드, 추가 MCP 서버 등은 이후 기능으로 둔다. **진단 → 가상 조치 → 재확인 → 기록**의 한 흐름을 먼저 완성한다.

## 6. 최종 README와 5분 발표에 넣을 내용

README 권장 항목:

1. 주제·해결할 문제·상정한 사용자
2. 기존 모니터링 결과 위에 어떤 점검·유지보수 과정을 추가했는지
3. 원본에서 재사용한 구조와 직접 변경한 파일
4. 데이터 스키마·시나리오·시뮬레이션 범위
5. 구성도와 실제 LangGraph 흐름
6. 설치·실행·환경변수·시나리오 초기화 방법
7. 실제 테스트 결과·화면·LangSmith 추적 예시
8. 비교 지표와 한계·향후 확장

발표 순서 예시: 문제·목적 40초 → 구조 50초 → 성공·실패 시연 2분 → 평가 50초 → 한계·확장 40초.

설명할 수 있어야 할 질문:

- 단순 알림과 비교해 어떤 다음 행동을 맡기는가?
- 어떤 판단을 코드가 하고 어떤 판단을 LLM이 하는가?
- 명령 접수와 실제 복구를 무엇으로 구분하는가?
- 데이터와 정답 시나리오가 진단 과정에 섞이지 않았는가?
- 같은 요청이 반복돼도 재시작이 중복 실행되지 않는가?
- 실제 기기로 바꿀 때 무엇을 검증해야 하는가?

실제 장치 미연동, 제한된 장애 유형, 가상 데이터의 단순성, 실제 현장 사용성 미검증은 한계로 명시한다. 기존 제품에도 원격 제어·유지보수 기능이 있으므로 “최초”나 “기존에는 전혀 없던 기능” 대신, **이번 프로젝트가 구현한 제한된 흐름과 검증 결과**를 설명한다.

**마지막 커밋 예:** `docs: add setup, demo results and project limitations`

## 7. 지금 바로 할 일 세 가지

- [ ] `.gitignore` 확인 → Git 초기화 → 기준 코드와 이 가이드 첫 커밋·푸시
- [ ] 중단된 의존성 설치 재실행 → fake 모드의 기존 웹 화면과 `/chat` 확인
- [ ] 가상 장치 5개와 S1~S5 시나리오를 직접 작성

이 세 가지를 마친 뒤 MCP 조회 도구부터 한 단계씩 바꾼다. 한 단계가 동작하면 결과를 확인하고 커밋한다.
