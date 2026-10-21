# Shelly H&T Gen3 측정과 보고 주기

<!-- meta: {"id": "normal_operation", "title": "Shelly H&T Gen3 측정과 보고 주기", "issues": ["healthy"], "tags": ["정상", "주기", "측정", "전송", "보고", "USB", "배터리"], "version": "summary-2026-10-21", "origin": "Shelly 공식 문서 기반 한국어 요약", "source_type": "manufacturer_summary", "publisher": "Shelly", "source_url": "https://kb.shelly.cloud/knowledge-base/shelly-h-t-gen3", "source_title": "Shelly H&T Gen3", "source_section": "Measuring and reporting", "retrieved_at": "2026-10-21", "applicable_models": ["shelly_ht_gen3"], "causes": [], "section_power_sources": {"1": ["battery"], "2": ["usb"]}} -->

> 공식 문서의 필요한 부분을 한국어로 요약했습니다. 원문 전체 번역이나 제조사가 작성한 한국어 매뉴얼은 아닙니다.
> 원문: [Shelly H&T Gen3](https://kb.shelly.cloud/knowledge-base/shelly-h-t-gen3) · 절: Measuring and reporting · 확인: 2026-10-21

## 전원별 보고 조건
배터리에서는 매분 측정하지만 변화량 기준을 충족할 때 전송한다. 기본 보고 기준은 온도 0.5°C 또는 습도 5% 변화이며, 변화가 없어도 2시간마다 상태를 보고한다.

## USB와 배터리 구분
USB 전원에서는 5분마다 측정·화면 갱신·보고 후 절전한다. 측정 주기와 서버 수신 주기를 같은 값으로 가정하지 않는다.

## 진단 적용 범위
이 요약은 Shelly H&T Gen3에 적용한다. 보고 간격만으로 원인을 확정하지 않으며, 전원 방식과 현재 설정을 함께 확인한다.
