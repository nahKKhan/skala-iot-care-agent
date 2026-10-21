# Shelly Humidity 누락값과 오류 필드

<!-- meta: {"id": "data_integrity", "title": "Shelly Humidity 누락값과 오류 필드", "issues": ["invalid_data"], "tags": ["누락", "형식", "데이터", "불명", "습도", "null", "오류"], "version": "summary-2026-10-21", "origin": "Shelly 공식 문서 기반 한국어 요약", "source_type": "manufacturer_summary", "publisher": "Shelly", "source_url": "https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/Humidity/", "source_title": "Humidity", "source_section": "Status", "retrieved_at": "2026-10-21", "applicable_models": ["shelly_ht_gen3"], "causes": []} -->

> 공식 문서의 필요한 부분을 한국어로 요약했습니다. 원문 전체 번역이나 제조사가 작성한 한국어 매뉴얼은 아닙니다.
> 원문: [Humidity](https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/Humidity/) · 절: Status · 확인: 2026-10-21

## 유효하지 않은 측정값
Humidity.GetStatus의 rh는 상대습도이며 유효한 측정값을 얻지 못하면 null일 수 있다. 누락된 값을 정상 습도로 채우지 않는다.

## 오류 관측
errors에는 out_of_range 또는 read가 포함될 수 있다. 오류 필드와 측정값을 함께 확인한다.

## 프로젝트 적용 한계
현재 시뮬레이터는 상태·잔량·수신 경과 시간을 정규화해 사용한다. 이 입력의 형식 검사는 프로젝트 정책이며 실제 제조사 측정 오류를 직접 진단한 결과가 아니다.
