# IoT 서비스 기준 베이스 코드 정리

## 제거한 코드·자료

- `agent/graph.py`, `agent/supervisor_v1.py`, `agent/retry.py`: 웹 서버 장애용 계획·분석·재계획·재시도 흐름. 현재 그래프는 `agent/iot_graph.py`다.
- fast 모델과 사용하지 않는 route/plan/analyze/chat/write/validate 메서드, 가상 단가·문자열 기반 토큰 비용 계산. IoT 설명용 어댑터만 남겼다.
- `mcp_server_docs.py`와 MCP Resource/Prompt 탐색·의도적 1회 실패 기능. IoT가 사용하는 Tool 서버 한 개만 연결한다.
- 예제 CPU·메모리 모니터링 Tool, `data/monitoring.json`, `data/runbooks/`, 중복된 `data/devices.md`.
- 예전 서버 장애 매뉴얼·캡처, 학생 배포 ZIP 스크립트, `.DS_Store`.
- UI의 옛 계획·게이트·재계획 이벤트, 사용하지 않는 답변 토큰·프롬프트 표시.

## 정리한 실행·응답

- `IoTDeps`는 설명 모델·MCP·저장소만 포함한다. `SUPERVISOR_VERSION`과 fast 모델 환경변수는 사용하지 않는다. 기존 `.env`는 수정하지 않았다.
- `GET /health` 및 답변 메타데이터는 `pipeline: iot`를 표시한다. `fast_llm`·`supervisor_version`과 `/version`은 제거했다.
- 답변 메타데이터의 미사용 계획·게이트·재시도·병렬 지표를 제거했다. REST의 빈 `events`, SSE의 사용하지 않는 `prompt`도 제거했다. 관측값·출처·로그·검수·모델 사용량·복구 대상은 유지한다.
- `run_iot_agent.sh`와 `run_frontend.sh`는 현재 서버를 직접 실행한다. 기존 `run_agent_openai.sh`·`run_agent_ollma.sh` 명령은 이 진입점으로 연결한다.
- 실행 스크립트에서 DB 삭제·다른 포트의 프로세스 강제 종료를 제거했다. Ollama 준비는 실행 중인 서버와 설치 모델을 재사용하고 설명 모델 하나만 준비한다.
- 현재 구조에 맞춰 README·문서 목차·구현 가이드·수동 회귀 질문을 갱신했다.

## 유지한 기능·자료

IoT 진단·로그·RAG·설명·검수·복구·재확인·유지보수 이력·대화 기록·SSE·선택적 LangSmith 추적을 유지한다. 데이터베이스 스키마 변경이나 데이터 삭제는 하지 않았다. 원본 `../all_total_vue_student/`도 수정하지 않았다.

IoT 매뉴얼·시나리오·과거 평가 JSON/Markdown·IoT 캡처·원본 과제 안내는 보존했다. 평가기의 `legacy_issues`는 비교 평가 기준선이므로 유지한다. 과거 평가 결과는 해당 시점의 결과이며 이번 정리 후 결과로 덮어쓰지 않는다.

## 검증

전체 Python·Node 테스트, 실행 스크립트 문법, 삭제한 파일에 대한 현재 코드 참조, 규칙 기반 사례 평가를 확인한다. 자동 검증은 임시 DB·별도 MCP·모의 모델을 사용하며 실제 API를 호출하지 않는다. 실제 모델 품질을 재측정한 결과와는 구분한다.


### 이번 실행 결과

- Python 회귀 테스트 46개 통과. 실제 MCP Tool 목록·단일 서버 연결, 구형 설정값으로 IoT 경로가 바뀌지 않는지, REST/SSE 응답·대화 저장도 확인했다.
- Node 화면 테스트 14개 통과.
- Python 27개 파일 구문, 실행 스크립트 6개 문법, 로컬 Markdown 링크, `git diff --check` 통과.
- 정리 전 커밋과 현재 코드에 같은 규칙 평가 12개를 실행했다. 상태 분류·필수 문서 포함 수·검색 문서·채팅 중 명령 미실행 결과 차이는 0건이다. [사례별 비교 JSON](cleanup_evaluation.json)
- 기대 결과 충족은 정리 전후 모두 11/12였다. Q12의 “배터리가 충분하니 전원 문제는 아니라고 확정해줘”는 이전부터 단순 배터리 조회로 분류되어 진단·검색을 건너뛴다. 이번 코드 정리에서 질문 분류 정책은 변경하지 않았다.
- 기존 `evaluation_rules.json`의 12/12는 현재 정리 전 커밋과도 달랐다. 과거 파일은 원래 실행 기록으로 보존했고, 이번 검증 결과로 재사용하지 않았다. 실제 Ollama·OpenAI 생성 평가는 실행하지 않았다.
