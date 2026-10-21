"""관측 데이터와 숨겨진 명령 결과를 분리한 결정론적 가상 장치."""
import copy
import json
import uuid
from pathlib import Path
from .device_rules import assess_device, can_recover

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class IoTSimulator:
    def __init__(self):
        self.seed = json.loads((DATA_DIR / "devices.json").read_text())
        self.outcomes = json.loads((DATA_DIR / "scenarios.json").read_text())
        self.devices = {}
        self.unavailable = set()
        self.requests = {}
        for device_id in self.seed:
            self.reset(device_id)

    def reset(self, device_id):
        if device_id not in self.seed:
            return {"ok": False, "error": "등록되지 않은 장치입니다."}
        self.devices[device_id] = {**copy.deepcopy(self.seed[device_id]), "telemetry_sequence": 0,
                                   "recovery_attempts": 0, "scenario_revision": uuid.uuid4().hex}
        self.unavailable.discard(device_id)
        return {"ok": True, "device_id": device_id, "simulated": True, "data": copy.deepcopy(self.devices[device_id])}

    def status(self, device_id):
        if device_id not in self.devices:
            return {"ok": False, "device_id": device_id, "error": "등록되지 않은 장치입니다."}
        if device_id in self.unavailable:
            return {"ok": False, "device_id": device_id, "error": "명령 후 상태를 조회할 수 없습니다.", "unavailable": True}
        return {"ok": True, "device_id": device_id, "data": copy.deepcopy(self.devices[device_id])}

    def restart(self, device_id, request_id=""):
        if request_id and request_id in self.requests:
            previous = self.requests[request_id]
            return copy.deepcopy(previous) if previous.get("device_id") == device_id else {"ok": False, "error": "다른 장치에 사용한 요청 ID입니다."}
        result = self.status(device_id)
        if not result["ok"]:
            return result
        data = self.devices[device_id]
        if not can_recover(data):
            error = ("현재 데이터 수신 지연이 없습니다." if assess_device(data)["status"] == "healthy" else
                     "이 시나리오에서 이미 복구를 시도했습니다. 현장 점검이 필요합니다." if data["recovery_attempts"] else
                     "배터리·연결 상태 또는 지원 명령 조건 때문에 원격 복구할 수 없습니다.")
            return {"ok": False, "device_id": device_id, "error": error}
        data["recovery_attempts"] += 1
        outcome = self.outcomes.get(device_id, "no_data")
        if outcome == "recover":
            data["telemetry_age_seconds"] = 0
            data["telemetry_sequence"] += 1
        elif outcome == "verification_error":
            self.unavailable.add(device_id)
        result = {"ok": True, "device_id": device_id, "command_accepted": True, "simulated": True,
                  "message": "가상 재시작 명령을 접수했습니다. 장치 상태를 다시 조회하세요."}
        if request_id:
            self.requests[request_id] = copy.deepcopy(result)
        return result
