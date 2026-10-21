# Shelly H&T Gen3 데이터 수신 지연 점검

<!-- meta: {"id": "telemetry_delayed", "title": "Shelly H&T Gen3 데이터 수신 지연 점검", "issues": ["telemetry_delayed"], "tags": ["데이터", "수신", "지연", "갱신", "멈춤", "전송", "보고"], "version": "summary-2026-10-21", "origin": "Shelly 공식 문서 기반 한국어 요약", "source_type": "manufacturer_summary", "publisher": "Shelly", "source_url": "https://kb.shelly.cloud/knowledge-base/shelly-h-t-gen3-web-interface-guide", "source_title": "Shelly H&T Gen3 web interface guide", "source_section": "Networks / MQTT; Device settings", "retrieved_at": "2026-10-21", "applicable_models": ["shelly_ht_gen3"], "causes": [{"id": "report_config", "title": "보고·전송 설정 불일치 가능성", "check": "현장에서 전원 방식과 보고 임계값, MQTT 사용 여부와 상태 알림 설정을 확인한다."}]} -->

> 공식 문서의 필요한 부분을 한국어로 요약했습니다. 원문 전체 번역이나 제조사가 작성한 한국어 매뉴얼은 아닙니다.
> 원문: [Shelly H&T Gen3 web interface guide](https://kb.shelly.cloud/knowledge-base/shelly-h-t-gen3-web-interface-guide) · 절: Networks / MQTT; Device settings · 확인: 2026-10-21

## 데이터 갱신 확인
제조사 웹 설정에는 MQTT 사용 여부와 상태 알림 설정이 있다. 서버 갱신이 멈췄다면 사용 중인 전송 경로의 설정을 확인할 수 있다.

## 원인 후보와 확인 한계
보고·전송 설정 불일치는 추가 확인할 후보이다. 현재 상태에 MQTT 설정값이 없으므로 잘못 설정됐다고 단정하지 않는다.

## 조치 구분
웹 설정의 Reboot는 장치 재부팅 기능이다. 이 프로젝트의 restart_collection은 가상 수집기 동작이며 제조사 재부팅 API가 아니다. 제조사 재부팅이나 초기화는 실행하지 않는다.
