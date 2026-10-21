# 반복 재시작 방지와 현장 점검

<!-- meta: {"id": "repeated_failure", "title": "반복 재시작 방지와 현장 점검", "issues": ["telemetry_delayed", "recovery_failed"], "tags": ["반복", "이력", "실패", "현장", "재시도", "중복"], "version": "2.0", "origin": "프로젝트 가상 복구 정책", "causes": [], "source_type": "project_policy", "publisher": "IoT Care Agent", "source_url": null, "source_section": null, "retrieved_at": null, "applicable_models": []} -->

> 프로젝트의 가상 수집기 복구 정책입니다. Shelly 제조사 매뉴얼이나 실제 장치 재부팅 기능이 아닙니다.

## 판별 근거
이전 복구 결과가 미복구 또는 확인 불가이면 동일 상태에서 추가 재시작을 자동 실행하지 않는다. 본 데모는 장치별 시나리오당 복구 명령을 최대 한 번 허용한다.

## 원인 후보와 확인 한계
유지보수 이력에는 진단 근거, 명령, 실행 전후 상태, 결과를 남긴다. 과거 미복구 이력은 현재 원인을 확정하지 않으며 후속 현장 점검의 참고 자료이다.

## 조치와 결과 확인
같은 request_id는 저장된 결과를 돌려주고 명령을 다시 실행하지 않는다. 데모 상태를 초기화하면 scenario_revision이 바뀌므로 이전 진단의 복구 버튼은 거부한다.

