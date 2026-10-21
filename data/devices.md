# 장치 데이터 설명
- connected : 장치와 통신 가능한가
- battery_pct : 배터리 잔량 (%)
- report_interval_seconds : 데이터 전송 주기 (초)
- telemetry_age_seconds : 마지막 수신 이후 경과 시간 (초)
- supported_actions : 지원하는 원격 명령

# 장치 설명 
- sensor-01 : 정상적으로 데이터를 보내는 센서
- sensor-02 : 연결은 됐지만, 데이터 전송이 멈춘 센서 (10분째)
- sensor-03 : 배터리가 부족한 센서 (연결 끊김)

추가 관측 필드:
- mode / wake_in_seconds: 정상 절전과 가상 기상 예정 시간
- telemetry_sequence: 새 데이터 수신 번호
- recovery_attempts: 해당 시나리오에서 실행한 복구 횟수
- scenario_revision: 초기화·프로세스 시작마다 바뀌는 상태 버전

장치 04는 정상 절전, 05와 06은 지연 상태다. 명령 결과 설정은 별도 scenarios.json에 있고 get_device_status 또는 모델 입력에 포함되지 않는다. 자세한 시연 결과는 README를 참고한다.
