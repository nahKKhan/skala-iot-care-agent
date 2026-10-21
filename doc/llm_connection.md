# IoT 점검 LLM 연결

## 동작

`장치 ID 추출 → MCP 상태 조회 → 코드 판단 → RAG 매뉴얼 검색·이력 조회 → LLM 설명·후보 선택 → 검수 → 기록`

- OpenAI·Ollama의 quality 모델이 실제로 호출된다. fast 모델은 이 IoT 흐름에서 호출하지 않는다.
- 상태, 배터리, 수신 시간은 코드가 그대로 표시하고, LLM은 의미·다음 점검·확인 한계를 설명한다.
- 복구 버튼 표시, 명령 실행 조건, 새 데이터로 복구 확인은 기존 코드가 담당한다. 채팅으로 재시작을 요구해도 명령을 자동 실행하지 않는다.
- 모델 응답은 JSON 스키마와 Pydantic으로 형식을 검사한 뒤 표시한다. 형식 검사는 설명 내용의 정확성까지 보장하지 않으므로 실제 원인은 추가 점검이 필요하다.
- 키 누락, 인증·한도 오류, 연결 실패, 모델 호출당 90초 응답 제한, 잘못된 모델 출력이면 오류 사실과 기존 조회 결과·매뉴얼을 표시한다.
- `/chat` 및 SSE `FinalAnswer`의 `metadata.answer_source`: `llm`, `rules`, `rules_fallback`, `rules_qa_fallback`, `rules_no_evidence`. `llm_usage`는 실제 응답의 모델·토큰 수이며 청구 금액을 추정하지 않는다.
- 설명은 완성 후 한 번에 표시한다. 모델 작성 중에는 진행 문구가 표시된다.

## OpenAI 실행

기존 8100 백엔드는 해당 터미널에서 Ctrl+C로 종료한다. 다른 프로세스를 강제 종료하거나 대화 DB를 삭제할 필요는 없다.

프로젝트 루트에 `.env`를 만들고 다음을 입력한다. 이미 환경변수로 키를 설정했다면 다시 적을 필요 없다. 키는 채팅이나 Git에 올리지 않는다.

```dotenv
OPENAI_API_KEY=본인의_API_키
OPENAI_QUALITY_MODEL=gpt-4o
```

OpenAI 모드에서는 장치 조회 결과와 매뉴얼이 API로 전달되며 API 사용 요금이 발생할 수 있다.

```bash
bash sh/run_iot_agent.sh openai
```

다른 터미널에서 화면 서버가 실행 중이 아니라면:

```bash
.venv/bin/python web_demo_server.py
```

http://localhost:8600 에서 새로고침 후 `sensor-02 점검해줘. 왜 이상하고 무엇부터 확인해야 해?` 입력.
답변 끝에 `설명 모델: openai:...`가 나오고 점검 설명·다음 조치·확인 한계가 보이면 모델이 실제 응답한 것이다.
`/health`의 모델 이름은 설정 확인용이며 실제 호출 성공을 보장하지 않는다.

`.env`의 값보다 같은 이름의 현재 터미널 환경변수가 우선한다. 기본 모델은 기존 코드의 gpt-4o이며 `.env`에서 변경할 수 있다.

## Ollama / 데모

Ollama 요청은 `think: false`로 thinking을 끄고 생성 예산을 640토큰으로 제한한다. 짧은 점검 설명을 우선하며 모델 호출당 응답 제한 시간은 90초다. 검수 재작성 시 최대 두 번 호출하므로 전체 시간은 더 길어질 수 있다. 모델 초기 적재나 장비 부하에 따라 시간은 달라진다.
참고: [Ollama thinking 설정](https://docs.ollama.com/capabilities/thinking).

이 환경에 설치된 모델은 `qwen3.5:2b`이므로 다음처럼 실행한다.

```bash
OLLAMA_QUALITY_MODEL=qwen3.5:2b bash sh/run_iot_agent.sh ollama
```

모델 이름은 설치 목록(`ollama list`)과 일치해야 한다. 코드 수정 후에는 기존 백엔드를 Ctrl+C로 종료하고 다시 실행한다.

```bash
# Ollama 서버와 해당 모델 설치가 먼저 필요하다.
bash sh/run_iot_agent.sh ollama
# 실제 모델 호출 없이 기존 데모 사용
bash sh/run_iot_agent.sh fake
```

## 검증

자동 테스트는 모의 모델 응답을 사용하며 API 과금이 없다.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/recovery_button_ui.test.cjs
```

구현: `agent/iot_llm.py`(프롬프트·HTTP·형식 검사), `agent/iot_graph.py`(설명 노드),
`agent/openai_llm.py`·`agent/ollama_llm.py`(기존 어댑터 확장).

API 형식 참고: [OpenAI 공식 Structured Outputs 문서](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat).
