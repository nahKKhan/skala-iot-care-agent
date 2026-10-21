# Shelly Temperature 센서 읽기 상태 점검

<!-- meta: {"id": "collection_process", "title": "Shelly Temperature 센서 읽기 상태 점검", "issues": ["telemetry_delayed"], "tags": ["수집", "샘플", "센서", "읽기", "오류", "중단", "온도"], "version": "summary-2026-10-21", "origin": "Shelly 공식 문서 기반 한국어 요약", "source_type": "manufacturer_summary", "publisher": "Shelly", "source_url": "https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/Temperature/", "source_title": "Temperature", "source_section": "Status", "retrieved_at": "2026-10-21", "applicable_models": ["shelly_ht_gen3"], "causes": [{"id": "sensor_read", "title": "온도 센서 읽기 오류 가능성", "check": "현장에서 Temperature.GetStatus의 tC와 errors를 확인한다."}]} -->

> 공식 문서의 필요한 부분을 한국어로 요약했습니다. 원문 전체 번역이나 제조사가 작성한 한국어 매뉴얼은 아닙니다.
> 원문: [Temperature](https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/Temperature/) · 절: Status · 확인: 2026-10-21

## 센서 상태 조회
Temperature.GetStatus의 tC는 섭씨 측정값이다. 유효한 값을 얻지 못하면 null일 수 있다.

## 원인 후보와 확인 한계
오류 배열에는 out_of_range 또는 read가 포함될 수 있다. 온도 센서 읽기 오류는 확인할 후보이며 서버 수신 지연만으로 센서 오류를 확정하지 않는다.

## 추가 확인
현장에서 온도 상태와 errors를 조회한다. 현재 프로젝트의 로그는 제조사 RPC 응답을 녹화한 자료가 아니라 가상 수집 기록이다.
