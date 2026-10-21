# Shelly Wi-Fi 연결과 전송 경로 확인

<!-- meta: {"id": "transport_path", "title": "Shelly Wi-Fi 연결과 전송 경로 확인", "issues": ["telemetry_delayed", "offline"], "tags": ["전송", "게이트웨이", "무선", "네트워크", "통신", "경로", "클라우드"], "version": "summary-2026-10-21", "origin": "Shelly 공식 문서 기반 한국어 요약", "source_type": "manufacturer_summary", "publisher": "Shelly", "source_url": "https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/WiFi/", "source_title": "WiFi", "source_section": "Status / Notifications", "retrieved_at": "2026-10-21", "applicable_models": ["shelly_ht_gen3"], "causes": [{"id": "transport_delay", "title": "Wi-Fi 연결·IP 확보 단계 이상 가능성", "check": "현장에서 Wifi.GetStatus의 status·sta_ip·rssi와 연결 해제 이벤트를 확인한다."}]} -->

> 공식 문서의 필요한 부분을 한국어로 요약했습니다. 원문 전체 번역이나 제조사가 작성한 한국어 매뉴얼은 아닙니다.
> 원문: [WiFi](https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/WiFi/) · 절: Status / Notifications · 확인: 2026-10-21

## 연결 관측값
Wifi.GetStatus에는 연결 단계 status, IP 주소 sta_ip, SSID, RSSI 등이 있다. status에는 disconnected, connecting, connected, got ip가 정의돼 있다.

## 원인 후보와 확인 한계
Wi-Fi 연결·IP 확보 단계 이상은 추가 확인할 후보이다. 연결 해제 이벤트의 reason 값을 수집하지 않았다면 해제 원인을 특정할 수 없다.

## 전송 경로 추가 확인
Wi-Fi 연결 상태는 무선 구간의 관측값이다. 서버의 새 데이터 수신까지 보장하는 값으로 사용하지 않는다. 현재 가상 데이터에는 RSSI·IP·reason이 없으므로 추가 조회가 필요하다.
