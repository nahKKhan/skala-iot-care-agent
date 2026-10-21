# 공식 문서 기반 매뉴얼 적용

적용 브랜치: mock. 원문 확인 날짜: 2026-10-21.

## 자료의 성격

RAG 자료를 프로젝트가 만든 일반 장애 설명에서 **Shelly H&T Gen3 공식 문서를 근거로 정리한 한국어 요약**으로 바꿨다.
원문 전체를 복사하거나 제조사 공인 번역으로 표시하지 않는다.
실제 제품 연결·제조사 RPC 실행은 없으며, 관측과 복구는 계속 가상이다.

검색 대상은 제조사 문서 기반 요약 8개(24문단)와 프로젝트 복구 정책 2개(6문단)이다.
8개 요약의 원문은 아래 공식 페이지 6개이며, 독립된 제조사 원문 8개라는 뜻은 아니다.

## 원문 목록과 적용 범위

| 로컬 요약 | 제조사 원문 | 참고 절 |
|---|---|---|
| normal_operation, normal_sleep | [Shelly H&T Gen3](https://kb.shelly.cloud/knowledge-base/shelly-h-t-gen3) | Measuring and reporting |
| telemetry_delayed, offline | [Web interface guide](https://kb.shelly.cloud/knowledge-base/shelly-h-t-gen3-web-interface-guide) | Networks / MQTT; Connecting your device to a Wi-Fi network; Device settings |
| low_battery | [DevicePower](https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/DevicePower/) | Status |
| transport_path | [WiFi](https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/WiFi/) | Status / Notifications |
| collection_process | [Temperature](https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/Temperature/) | Status |
| data_integrity | [Humidity](https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/Humidity/) | Status |

각 요약의 HTML 주석에 원문 URL·절·확인 날짜·적용 모델·버전을 보관한다.
source_type=manufacturer_summary와 project_policy를 API·프롬프트·화면에서 구분한다.
이력에도 검색 당시의 본문·버전·출처를 저장해 이후 매뉴얼 변경으로 과거 근거가 바뀌지 않도록 한다.
원인 후보와 추가 확인 안내는 프로젝트의 해석이며, 제조사가 현재 가상 장치의 원인을 판정한 결과가 아니다.

## 제조사 동작 조건과 프로젝트 판정의 경계

- USB: 최대 보고 간격 300초.
- 배터리: 변화량에 따라 보고하며 변화가 없어도 최대7200초에 상태를 보고한다.
- 수신 여유60초와 배터리 주의20% 이하는 **프로젝트 운영 정책**이다. 제조사의 고장 기준이 아니다.
- 최대 보고 간격+60초를 판정에 사용한다. USB360초, 배터리7260초를 넘긴 연결 중 미수신을 지연으로 분류한다.
- 배터리의 미연결이 기한 안이라면 정상 보고 대기와 양립한다고 안내한다. 실제 절전이나 무고장을 보장하지 않는다.
- 보고 기한을 넘기면 sleeping 플래그가 있어도 문제를 숨기지 않는다.
- USB에서는 배터리 잔량 저하만으로 외부 전원 이상을 판단하지 않는다. null을0으로 바꾸지 않는다.

## 가상 장치와 조치

| ID | 참고 프로필 | 초기 상태 |
|---|---|---|
| sensor-01 | Shelly H&T Gen3 / USB | 수신10초 전, 정상 |
| sensor-02 | 동일 / USB | 수신600초 전, 지연. 가상 복구 후 새 데이터 수신 |
| sensor-03 | 동일 / 배터리 | 잔량5%, 수신8100초 전, 연결 불가 |
| sensor-04 | 동일 / 배터리 | 수신600초 전, 정상 보고 대기 조건 안 |
| sensor-05 | 동일 / USB | 지연. 명령 접수 후에도 새 데이터 없음 |
| sensor-06 | 동일 / USB | 지연. 명령 접수 후 상태 확인 불가 |

restart_collection은 프로젝트의 **가상 수집기** 재시작이며 Shelly의 Reboot RPC가 아니다.
recovery_verification과 repeated_failure는 data/iot_policies/로 분리했다.
실제 장치 재부팅·공장 초기화·네트워크 설정 변경을 실행하지 않는다.

## 실행과 갱신

백엔드(MCP 자식 프로세스 포함)를 재시작하고 화면을 새로고침한다.
기존 SQLite 이력은 삭제하지 않는다. 전체 상태 초기화 후 새 점검을 실행한다.
공식 문서 요약은 시작할 때 로컬에서 색인한다. 질문마다 외부 사이트를 가져오거나 자동 동기화하지 않는다.
원문 갱신 시 내용을 확인하고 버전·확인 날짜·관련 검사를 함께 갱신한다.

확인할 질문:

- sensor-04 점검해줘: 정상 보고 대기 조건, 복구 버튼 없음.
- sensor-02 점검해줘: USB 지연 판정, 원문 링크, 가상 수집기 복구 구분.
- 배터리 측정 보고 주기 매뉴얼 알려줘: 원문과 근거 문단 표시.
- sensor-03 점검해줘: 낮은 배터리와 보고 기한 초과, 원인 미확정.

기존 실제 모델 평가·화면 캡처·외부 발표 자료는 변경 전 자료이다.
이번 문서 교체 후의 실제 모델 답변 품질을 보증하지 않는다. 사용할 모델로 재평가가 필요하다.

## 이번 변경의 검증 기록

- 기록 시각: 2026-10-21T17:43:31+09:00
- Python unittest: 64개 통과(26.185초), 독립 MCP와 임시 DB, 모의 모델 사용.
- Node 화면 로직: 23개 통과. 기존 복구·초기화·이력 처리와 공식 원문 링크 검사 포함.
- 합계87개는 자동 기능 검사 수이며 실제 장치·실제 모델 정확도87건을 뜻하지 않는다.
- 공식 출처 필드 누락 거부, 모델·전원별 문서 적용, USB360초/배터리7260초 경계,
  보고 대기 중 낮은 잔량, USB null 잔량 표시, 원문 출처의 모델 입력·API·이력 저장을 검증했다.
- 규칙 평가: 기대 결과11/12, 필수 문서 검색11/12, 채팅 중 명령 미실행12/12.
- Q12는 복합 질문을 단순 배터리 조회로 분류하는 기존 제한이다.
- 실제 Ollama/OpenAI 생성은 이번 작업에서 호출하지 않았다.
- 평가 코드 버전: ebb0daffb7d1, 문서 색인 버전: 88f03f8b6989.
- 원시 결과: [JSON](evaluation_shelly_rules.json) / [평가 요약](evaluation_shelly_rules.md).

기존 이력과 원본 베이스는 보존했다. 변경은 mock 브랜치의 작업 파일에만 반영했으며 커밋·푸시는 수행하지 않았다.
