# 명령 접수와 복구 검증

<!-- meta: {"id": "recovery_verification", "title": "명령 접수와 복구 검증", "issues": ["telemetry_delayed", "recovery_failed", "verification_pending"], "tags": ["복구", "확인", "재시작", "접수", "sequence", "검증"], "version": "1.0", "origin": "프로젝트 작성 시뮬레이션 점검 절차", "causes": []} -->

> 가상 IoT 데모용 절차입니다. 실제 제조사 매뉴얼 또는 검증된 현장 고장 진단서가 아닙니다.

## 판별 근거
command_accepted=true는 명령 접수만 의미한다. 복구 성공은 실행 전보다 telemetry_sequence가 증가하고 다시 조회한 상태가 정상일 때만 판정한다. 기존 패킷이나 접수 메시지를 새 데이터로 취급하지 않는다.

## 원인 후보와 확인 한계
명령 후 새 데이터가 없으면 미복구이다. 실행 후 조회 자체가 실패하면 확인 불가이다. 미복구와 확인 불가는 다른 상태이며 둘 다 성공이라고 설명하지 않는다.

## 조치와 결과 확인
복구 확인 시 resolved, 새 데이터가 없으면 needs_visit, 재조회 실패 시 verification_pending으로 기록한다. 시뮬레이터의 성공·실패 설정은 진단 입력에 노출하지 않는다.

