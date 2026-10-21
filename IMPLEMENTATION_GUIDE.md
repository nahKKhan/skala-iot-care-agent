# IoT Care 구현 가이드

현재 구현을 수정할 때 찾을 위치를 정리한다. 설치·실행 명령은 [README](README.md), 모델 연결은 [LLM 안내](doc/llm_connection.md)를 참고한다.

## 실행 흐름

`Vue 화면 → FastAPI → LangGraph → MCP 상태·로그·매뉴얼·이력 조회 → 모델 설명 → 코드 검수 → 유지보수 기록`

복구는 사용자가 버튼을 눌렀을 때 별도 API로 실행한다. 코드가 실행 조건·요청 중복·시나리오 버전을 검사하고 명령 전후 수신 번호·정상 상태로 결과를 판정한다.

## 기능별 수정 위치

| 기능 | 파일 |
|---|---|
| 질문 분류·장치 ID 추출 | `agent/query_router.py` |
| 진단·검색·설명·검수·기록 흐름 | `agent/iot_graph.py` |
| 배터리·연결·절전·수신 지연 규칙 | `agent/device_rules.py` |
| 가상 상태·로그·복구 이벤트 | `agent/iot_simulator.py`, `agent/device_logs.py` |
| 초기 관측·로그·명령 후 결과 | `data/devices.json`, `data/device_logs.json`, `data/scenarios.json` |
| MCP 도구·연결 | `mcp_server.py`, `agent/mcp_client.py` |
| 매뉴얼·BM25 검색 | `data/iot_manuals/`, `agent/manual_search.py` |
| 설명 프롬프트·구조화 출력·모델 HTTP 요청 | `agent/iot_llm.py` |
| OpenAI·Ollama 어댑터 | `agent/openai_llm.py`, `agent/ollama_llm.py` |
| 모델 미사용 시연 | `agent/fake_llm.py` |
| 출처·후보·조치 정책 검수 | `agent/answer_quality.py` |
| API·SSE·복구 요청 처리 | `server.py` |
| 대화·유지보수·중복 방지 저장 | `agent/session_store.py` |
| 화면·API 프록시 | `web_chat.html`, `web_demo_server.py` |
| 자동 테스트·사례 평가 | `tests/`, `scripts/evaluate_iot.py` |

`IoTDeps`에는 설명 모델·MCP·저장소만 둔다. 질문 분류와 상태 판정에 별도의 fast 모델을 생성하지 않는다. 실행 그래프는 IoT 하나이며 구형 supervisor 버전 전환은 없다.

## 기능을 변경하는 순서

1. 필요한 관측값·이벤트와 기대 결과를 정한다. 장치 상태와 숨겨진 명령 후 결과를 분리한다.
2. 데이터·시뮬레이터를 변경하고 필요한 MCP Tool을 연결한다. 조회만으로 명령을 실행하지 않는다.
3. `iot_graph.py`에서 새 근거를 조회·모델에 전달·이력에 저장한다. 조회 실패를 정상으로 해석하지 않는다.
4. API 응답을 바꾸면 REST와 SSE를 같이 변경한다. 새 API를 만들면 화면 프록시도 연결한다.
5. 의미 있는 정상·실패·중복 요청 사례로 검증하고 문서를 갱신한다.

## 검증

```bash
LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/recovery_button_ui.test.cjs
```

자동 테스트는 임시 DB·독립 MCP·모의 모델을 사용한다. 실제 Ollama·OpenAI 품질 평가는 별도로 수행한다. 평가 데이터·기준은 재사용할 수 있지만 모델이 달라지면 답변 품질·시간·비용을 다시 측정한다.

MCP만 직접 확인하려면 `check_mcp.py`, `check_device_logs.py`, `check_recovery.py`를 실행한다. 복구 확인 스크립트는 별도 MCP 프로세스의 가상 장치만 변경한다.

## 수정 시 유지할 조건

- 실제 명령 실행 가능 여부와 복구 판정은 코드로 결정한다.
- 명령 접수·미복구·확인 불가를 구분한다. 불확실한 요청을 자동 재실행하지 않는다.
- 상태·매뉴얼·로그·이력을 구분하고 원인 후보를 확정 진단으로 표현하지 않는다.
- 매뉴얼 출처와 원인 후보의 ID를 실제 검색 결과에 한정한다.
- `.env`·DB·가상환경을 Git에 넣지 않는다. 실행 스크립트는 기존 DB나 다른 프로세스를 삭제·강제 종료하지 않는다.

원본 과제 안내는 `doc/manual_change.md`, 정리된 베이스 코드 목록은 [정리 보고서](doc/code_cleanup.md)에 있다.
