# Shelly DevicePower 배터리와 외부 전원 상태

<!-- meta: {"id": "low_battery", "title": "Shelly DevicePower 배터리와 외부 전원 상태", "issues": ["low_battery"], "tags": ["배터리", "전원", "잔량", "방전", "교체"], "version": "summary-2026-10-21", "origin": "Shelly 공식 문서 기반 한국어 요약", "source_type": "manufacturer_summary", "publisher": "Shelly", "source_url": "https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/DevicePower/", "source_title": "DevicePower", "source_section": "Status", "retrieved_at": "2026-10-21", "applicable_models": ["shelly_ht_gen3"], "causes": [{"id": "battery_supply", "title": "배터리·전원 상태 추가 확인 필요", "check": "현장에서 DevicePower의 배터리 전압·잔량과 외부 전원 유무를 확인한다."}]} -->

> 공식 문서의 필요한 부분을 한국어로 요약했습니다. 원문 전체 번역이나 제조사가 작성한 한국어 매뉴얼은 아닙니다.
> 원문: [DevicePower](https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/DevicePower/) · 절: Status · 확인: 2026-10-21

## 관측 필드
DevicePower 상태는 battery.V 전압, battery.percent 잔량, 지원되는 경우 external.present 외부 전원 연결 여부를 제공한다.

## 원인 후보와 확인 한계
유효한 전압이나 잔량을 얻지 못하면 해당 값은 null일 수 있다. 배터리·전원 상태를 추가 확인하되 잔량만으로 접촉 불량을 확정하지 않는다.

## 프로젝트 적용
잔량 20% 이하 주의는 프로젝트 정책이며 제조사가 제시한 고장 임계값이 아니다. USB 사용 시 배터리 잔량만으로 외부 전원 이상을 판단하지 않는다.
