# IoT Care Agent

가상 IoT 장치의 상태·매뉴얼·이력을 바탕으로 원인 후보와 점검 순서를 안내하고, 사용자가 요청한 가상 복구의 실제 데이터 수신 여부까지 확인하는 서비스.

## 주요 기능

1. **관측 상태 진단**: 연결, 배터리, 수신 주기를 확인하고 정상 절전과 수신 지연을 구분한다.
2. **RAG 매뉴얼 검색**: IoT 매뉴얼 10종·30문단을 BM25와 한국어 단어·문자 2-gram으로 검색한다. 실제 검색 문단을 모델에 전달하며 제목·문단 ID·본문을 화면에서 확인할 수 있다.
3. **원인 후보 분석**: 검색 문서의 후보 중 모델이 가능한 원인을 선택하고 추가 점검을 안내한다. 원인 확률이나 확정 고장 진단으로 해석하지 않도록 후보로 표시한다.
4. **답변 검수**: 인용 문단·허용 후보·수치·조치 정책과 일부 근거 없는 단정 표현을 검사한다. 허용 후보·출처·조치 문구를 생성 스키마에도 제한한다. 실패하면 최대 한 번 재작성하고, 다시 실패하면 규칙 기반 안내로 대체한다.
5. **사용자 실행형 가상 복구**: 버튼으로 수집 모듈을 재시작한다. 명령 접수와 새 데이터 수신을 구분해 복구 확인·미복구·확인 불가를 판정한다.
6. **유지보수 이력**: 진단과 조치 전후 상태·출처·결과를 SQLite에 저장하고 다음 점검과 화면에서 조회한다. 동일 상태의 점검 기록은 갱신하고 중복 복구 request_id는 재실행하지 않는다.

검색은 임베딩 기반 의미 검색이 아닌 **키워드 기반 RAG**이다. 매뉴얼은 프로젝트에서 작성한 가상 장치 점검 절차이며 실제 제조사 문서가 아니다. [RAG 구현과 품질 검증 설명](doc/rag_and_quality.md)

## 실행

최초 환경 준비가 필요하면 `bash sh/setup_venv.sh`를 실행한다. 기존 `.venv`가 있으면 재설치할 필요 없다.

터미널 A — Ollama 서버와 모델:

```bash
ollama serve
# 모델이 없을 때만 별도 터미널에서: ollama pull qwen3.5:2b
```

터미널 B — 백엔드(기존 8100 서버는 Ctrl+C로 먼저 종료):

```bash
bash sh/run_iot_agent.sh ollama
```

터미널 C — 웹 화면(기존 8600 서버도 변경 코드 반영을 위해 재시작):

```bash
.venv/bin/python web_demo_server.py
```

http://localhost:8600 에서 장치를 선택하거나 `sensor-02 점검해줘`를 입력한다. 변경된 프런트는 브라우저에서 새로고침한다.

- 기본 Ollama 모델: `qwen3.5:2b`. 변경: `OLLAMA_QUALITY_MODEL=모델명 bash sh/run_iot_agent.sh ollama`
- 모델 없는 코드 시연: `bash sh/run_iot_agent.sh fake`
- OpenAI: `.env` 또는 환경변수에 유효한 `OPENAI_API_KEY`를 설정하고 `bash sh/run_iot_agent.sh openai`. API 요금이 발생할 수 있다.
- `.env`는 Git에서 제외된다. 샘플은 `.env.example`이다. LangSmith 추적은 기본 비활성화이며 키 없이 실행 가능하다.
- 실행 스크립트는 대화 DB를 삭제하거나 다른 서버를 강제 종료하지 않는다.

## 채팅에서 물어볼 수 있는 질문

- `sensor-02가 뭐더라?`: 등록된 장치 소개. 한글 조사가 붙어도 ID를 인식한다.
- `sensor-02 배터리 얼마나 남았어?`, `sensor-02 전송 주기는?`: 필요한 현재 관측값 조회.
- `sensor-02 점검해줘`: 기존 RAG 진단·원인 후보·복구 가능 여부.
- `sensor-02 점검 기록 보여줘`: 저장된 유지보수 이력 조회.
- `등록된 장치 목록 보여줘`: 장치 ID와 이름.
- `정상 절전과 수신 지연은 어떻게 달라?`: 장치 ID 없이 관련 매뉴얼 문단 조회.
- `무엇을 할 수 있어?`: 서비스 범위와 질문 예시.

일반 매뉴얼 답변과 특정 장치의 현재 상태 진단은 구분한다. 소개·간단한 상태·이력·매뉴얼 조회는 실제 데이터로 바로 응답하며 모델을 호출하지 않는다. 점검 설명과 후보 분석은 기존 실제 모델 흐름을 사용한다.

## 시연 장치

| ID | 초기 상황 | 기대 결과 |
|---|---|---|
| sensor-01 | 정상 수신 | 정상 안내, 복구 버튼 없음 |
| sensor-02 | 연결됨·데이터 지연 | 실행 후 새 수신 확인·복구 확인 기록 |
| sensor-03 | 배터리 부족·오프라인 | 현장 점검, 원격 재시작 금지 |
| sensor-04 | 예정된 절전 | 정상 절전 안내, 불필요한 재시작 없음 |
| sensor-05 | 연결됨·데이터 지연 | 명령 접수 후 새 데이터 없음·현장 점검 기록 |
| sensor-06 | 연결됨·데이터 지연 | 명령 후 재조회 실패·확인 불가 기록 |

`가상 상태 초기화`는 선택 장치만 초기화하며 유지보수 기록은 보존한다. 이전 상태의 복구 버튼은 사용할 수 없다. 실제 복구 성공·실패 설정은 `data/scenarios.json`에 분리되어 진단 입력에 노출되지 않는다.

절전의 `wake_in_seconds`와 수신 경과 시간은 고정 가상 관측값이며 실제 시간에 따라 자동 갱신되지 않는다. 실제 기기를 제어하지 않는다.

## 구조

```text
Vue 화면 (:8600)
  → FastAPI (:8100)
    → LangGraph: 대상 → 상태 → 매뉴얼 검색·이력 → 설명 → 검수 → 기록
      → MCP: 장치 조회·문단 검색·이력 조회·가상 복구·초기화
      → Ollama / OpenAI: 근거 기반 설명과 후보 선택
    → SQLite: 대화·유지보수·복구 요청 결과
```

현재 IoT 경로는 `agent/iot_graph.py`다. 원본 `agent/graph.py`와 v1은 기존 웹 서버 장애 실습 코드이며 IoT 기능 설명의 근거로 사용하지 않는다.

## API

| 경로 | 용도 |
|---|---|
| `GET /health` | 설정된 모델·백엔드 확인. 실제 모델 응답 성공을 보장하지 않음 |
| `POST /chat`, `GET /chat/stream` | 진단·설명·검색 근거·검수 결과 |
| `GET /api/devices` | 가상 장치 목록 |
| `POST /api/recover` | 장치 ID·request_id·시나리오 버전·수신 번호로 가상 복구 요청 |
| `GET /api/maintenance` | 점검·조치 이력. `device_id`로 필터 가능 |
| `POST /api/scenario/reset` | 선택 가상 장치 초기화 |

## 테스트와 평가

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/recovery_button_ui.test.cjs
.venv/bin/python scripts/evaluate_iot.py --backend rules --output doc/evaluation_rules.json
.venv/bin/python scripts/evaluate_iot.py --backend ollama --model qwen3.5:2b --output doc/evaluation_ollama.json
```

자동 테스트의 모의 모델 응답과 실제 Ollama 평가를 구분한다. 평가기는 독립 MCP 프로세스·임시 DB를 사용한다. 평가 정답은 모델에 전달되지 않는다.

- [규칙·검색 평가 결과](doc/evaluation_rules.md)
- [실제 Ollama 평가 결과](doc/evaluation_ollama.md)
- [첫 평가에서 발견한 실패 사례와 보조 검토](doc/evaluation_ollama_initial.md)
- [구현·검증 정리](doc/quality_report.md)
- [5분 시연 순서](doc/demo_script.md)

## 기존 코드에서 변경한 부분

FastAPI 수명 관리, MCP stdio 연결, Vue 채팅·SSE, 모델 어댑터, SQLite 대화 저장 구조를 재사용했다.
새로 구현한 부분은 IoT 관측·절전 규칙, 명령 결과를 분리한 시뮬레이터, 매뉴얼 10종과 문단 검색,
출처를 붙인 후보 분석·검수 그래프, 복구 API와 중복 방지, 영속 유지보수 이력 및 화면, 고정 사례 평가기다.

`doc/manual_change.md`는 제공 과제 안내이며 `doc/manual_openai.md`, `doc/manual_ollma.md`, `doc/README.md`의 기존 실습 예시는 현재 IoT 기능 전체를 설명하지 않는다. 현재 실행·구현 범위는 이 README를 기준으로 한다. 원본 `../all_total_vue_student/`는 수정하지 않았다.

## 확인된 한계

- 가상 장치와 프로젝트 작성 매뉴얼로 검증했다. 실제 BLE·MQTT 장치, 현장 전압·신호·게이트웨이 로그는 미연동이다.
- 소규모 개발 사례 평가이며 새로운 현장 문제에 대한 정확도 수치가 아니다.
- 출처·정책 검수는 문장 의미 전체의 근거 일치를 보장하지 않는다. 실제 답변 보조 검토에서 배터리와 연결 끊김의 인과 단정 등 보완할 표현이 남아 있다. [품질 검증 정리](doc/quality_report.md)를 참고한다.
- 모델 응답 시간이 길어질 수 있으며 생성·검수 최대 2회 이후에는 확인된 사실로 안내한다.
- 장치 상태는 MCP 메모리여서 백엔드 재시작 시 초기화된다. 유지보수 이력과 요청 결과는 DB에 남는다.
- 오래된 시나리오 방지는 버전 정보를 포함한 요청에 적용된다. 호환성을 위해 버전 없는 직접 API 요청도 현재 상태를 재검증해 처리한다.
