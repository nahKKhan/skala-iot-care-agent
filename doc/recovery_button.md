# 가상 복구 버튼 연결

## 바뀐 파일

- `server.py`: 조회한 장치 상태로 복구 가능 여부를 판단하고 `/chat` 및 SSE 최종 답변에 `recovery` 정보를 전달한다. 기존 복구 명령 API를 사용한다.
- `web_demo_server.py`: 화면의 `POST /api/recover`를 백엔드에 중계한다. 백엔드의 성공·거부 상태를 보존하며 복구 요청은 자동 재전송하지 않는다.
- `web_chat.html`: 점검 답변에 복구 가능한 장치의 버튼을 표시한다. 실행 중에는 중복 클릭과 새 채팅 전송을 막고, 결과에 따라 복구 확인·미복구·확인 불가를 구분한다.

## 화면에서 확인하기

1. 백엔드와 프런트엔드를 각각 종료 후 다시 실행한다.
2. 브라우저를 새로고침하고 `sensor-02 점검해줘`를 입력한다.
3. 답변 아래 **가상 복구 실행** 버튼을 누른다.
4. **가상 복구 완료**, 수신 지연 `600초 → 0초`, 수신 번호 `0 → 1`을 확인한다.
5. 다시 같은 장치를 점검하면 정상 안내가 나오고 새 복구 버튼은 표시되지 않는다.
6. 정상 장치(sensor-01), 연결 끊김·배터리 부족 장치(sensor-03), 없는 장치(sensor-99)에는 복구 버튼이 나오지 않는다.

현재 시뮬레이터의 상태는 MCP 프로세스 메모리에 있다. 백엔드를 재시작하면 초기 데이터로 돌아간다. 실제 기기를 제어하는 기능은 아니다.

## 실행 명령

프로젝트 폴더의 터미널 A:

```bash
LLM_BACKEND=fake SUPERVISOR_VERSION=v2 LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false .venv/bin/python server.py
```

터미널 B:

```bash
.venv/bin/python -m uvicorn web_demo_server:app --host 127.0.0.1 --port 8600
```

브라우저: http://localhost:8600

## 검증 명령

Python 검증은 별도 MCP 프로세스·임시 대화 DB를 사용하므로 사용 중인 장치 상태와 대화 DB를 바꾸지 않는다.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p 'test_recovery_button.py' -v
node --test tests/recovery_button_ui.test.cjs
```

Node 검증은 실제 화면 스크립트를 격리한 상태에서 실행해 중복 클릭·실패·통신 오류 처리를 확인한다. 실제 브라우저 렌더링 검증과는 구분한다.
