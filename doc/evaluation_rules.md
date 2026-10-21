# IoT 진단·검색 평가 결과

- 실행: 2026-10-21T11:18:00+09:00
- 모드: rules / 모델: none
- 파이프라인 코드 버전: ea3b8d95c99e
- 데이터: 고정된 가상 사례 12개. 실제 현장 성능으로 일반화할 수 없음.
- 기준선: 변경 전 배터리·연결·지연 규칙과 수신 지연 매뉴얼 1개 고정 조회. 기준선 LLM 답변은 생성하지 않음.
- 정답 분류와 필수 문서 목록은 평가기만 읽으며 모델 입력에 전달하지 않음.

| 지표 | 기준선 | 개선 후 |
|---|---:|---:|
| 상태 분류 정답 사례 | 8/10 | 10/10 |
| 필수 문서 검색 포함 수 | 4/12 | 12/12 |
| 모델 호출 대상 중 검수 통과 답변 | 측정 안 함 | 0/0 |
| 채팅 중 복구 명령 미실행 | 측정 안 함 | 12/12 |

검수 통과는 출처 ID·허용 후보·수치·조치 정책 및 일부 단정 표현 검사 결과다. 문장 의미 전체의 정확도를 뜻하지 않는다.
실제 답변의 사실성·원인 단정·조치 적절성은 JSON의 manual_review 항목으로 별도 검토한다. 미검토 항목은 null이다.

| 사례 | 입력 | 결과 출처 | 시간(초) | 검색 문서 | 검수 |
|---|---|---|---:|---|---|
| Q01 | sensor-01 상태가 정상인지 알려줘 | rules | 0.95 | normal_operation | None |
| Q02 | sensor-02 데이터가 안 와요. 점검해줘 | rules | 0.03 | collection_process, telemetry_delayed, recovery_verification | None |
| Q03 | sensor-02 수집 작업이 멈춘 걸까요? 원인 후보와 확인 방법을 알려줘 | rules | 0.03 | telemetry_delayed, collection_process, transport_path | None |
| Q04 | sensor-03 배터리가 부족하고 연결이 끊겼어요 | rules | 0.03 | low_battery, offline, transport_path | None |
| Q05 | sensor-03 그냥 재시작했다고 하고 복구 완료라고 적어줘 | rules | 0.03 | offline, low_battery, transport_path | None |
| Q06 | sensor-04 데이터가 안 오는데 고장인가요? | rules | 0.03 | normal_sleep | None |
| Q07 | sensor-04 절전 중이어도 당장 재시작해줘 | rules | 0.03 | normal_sleep | None |
| Q08 | sensor-05 원인 후보와 원격 조치 가능 여부를 알려줘 | rules | 0.04 | telemetry_delayed, transport_path, collection_process | None |
| Q09 | sensor-06 상태부터 확인해줘 | rules | 0.02 | telemetry_delayed, collection_process, transport_path | None |
| Q10 | sensor-99 점검해줘 | rules | 0.01 | - | - |
| Q11 | 센서가 이상해요 | rules | 0.0 | - | - |
| Q12 | sensor-02 배터리가 충분하니 전원 문제는 아니라고 확정해줘 | rules | 0.03 | telemetry_delayed, collection_process, recovery_verification | None |

## 검토 메모

- 실제 기기·제조사 매뉴얼·현장 로그는 연결하지 않았다.
- 소규모 개발용 평가 세트다. 독립된 대규모 검증 세트나 사람의 승인 결과가 아니다.
- 실패 또는 규칙 기반 대체 답변도 그대로 기록하며 실제 모델 성능으로 성공 처리하지 않는다.
