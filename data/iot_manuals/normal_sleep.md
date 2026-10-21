# Shelly H&T Gen3 절전과 정상 보고 대기

<!-- meta: {"id": "normal_sleep", "title": "Shelly H&T Gen3 절전과 정상 보고 대기", "issues": ["sleeping"], "tags": ["절전", "기상", "예약", "정상", "대기", "배터리"], "version": "summary-2026-10-21", "origin": "Shelly 공식 문서 기반 한국어 요약", "source_type": "manufacturer_summary", "publisher": "Shelly", "source_url": "https://kb.shelly.cloud/knowledge-base/shelly-h-t-gen3", "source_title": "Shelly H&T Gen3", "source_section": "Measuring and reporting / On batteries; On USB power supply", "retrieved_at": "2026-10-21", "applicable_models": ["shelly_ht_gen3"], "causes": [], "section_power_sources": {"2": ["battery"]}} -->

> 공식 문서의 필요한 부분을 한국어로 요약했습니다. 원문 전체 번역이나 제조사가 작성한 한국어 매뉴얼은 아닙니다.
> 원문: [Shelly H&T Gen3](https://kb.shelly.cloud/knowledge-base/shelly-h-t-gen3) · 절: Measuring and reporting / On batteries; On USB power supply · 확인: 2026-10-21

## 정상 절전 근거
배터리 동작에는 자가 발열을 줄이기 위한 5분 냉각 구간이 있다. USB에서도 보고 후 5분 절전한다.

## 보고 대기와 장애 구분
배터리 센서가 10분 동안 새 값을 전송하지 않았다는 사실만으로 장애를 판단할 수 없다. 변화량 기준과 2시간 상태 보고 조건을 함께 본다.

## 추가 확인
기상 예정값은 프로젝트의 가상 관측값이다. 실제 장치의 기상이나 절전을 직접 측정한 증거로 취급하지 않는다. 보고 기한이 지났다면 정상 절전이라는 이유로 계속 숨기지 않는다.
