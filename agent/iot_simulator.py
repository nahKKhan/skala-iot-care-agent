"""관측 데이터와 숨겨진 명령 결과를 분리한 결정론적 가상 장치."""
import copy
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .device_rules import assess_device, can_recover

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class IoTSimulator:
    def __init__(self):
        self.seed = json.loads((DATA_DIR / "devices.json").read_text())
        self.outcomes = json.loads((DATA_DIR / "scenarios.json").read_text())
        self.log_seed = json.loads((DATA_DIR / "device_logs.json").read_text())
        self.logs = {}
        self.log_sequences = {}
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
        self.logs[device_id] = []
        self.log_sequences[device_id] = 0
        now = datetime.now(timezone.utc)
        for entry in sorted(self.log_seed.get(device_id, []), key=lambda row: row["offset_seconds"]):
            self._append_log(device_id, entry["level"], entry["component"], entry["code"], entry["message"],
                             entry.get("details"), now + timedelta(seconds=entry["offset_seconds"]))
        return {"ok": True, "device_id": device_id, "simulated": True, "data": copy.deepcopy(self.devices[device_id])}

    def reset_all(self):
        """등록된 모든 가상 장치와 로그를 초기화한다. 요청 중복 방지 기록은 유지한다."""
        device_ids = list(self.seed)
        for device_id in device_ids:
            self.reset(device_id)
        return {"ok": True, "simulated": True, "device_ids": device_ids, "count": len(device_ids)}

    def _append_log(self, device_id, level, component, code, message, details=None, timestamp=None):
        self.log_sequences[device_id] += 1
        self.logs[device_id].append({
            "id": f"{self.devices[device_id]['scenario_revision']}:{self.log_sequences[device_id]}",
            "timestamp": (timestamp or datetime.now(timezone.utc)).isoformat(timespec="milliseconds"),
            "level": level, "component": component, "code": code, "message": message,
            "details": copy.deepcopy(details or {}),
        })
        self.logs[device_id] = self.logs[device_id][-200:]

    def get_logs(self, device_id, limit=10, level=None):
        """가상 수집 버퍼의 최근 이벤트. 조회는 장치나 로그를 변경하지 않는다."""
        if device_id not in self.devices:
            return {"ok": False, "device_id": device_id, "error": "등록되지 않은 장치입니다."}
        if type(limit) is not int or not 1 <= limit <= 100:
            return {"ok": False, "device_id": device_id, "error": "limit은 1~100 사이 정수여야 합니다."}
        if level is not None and level not in ("INFO", "WARN", "ERROR"):
            return {"ok": False, "device_id": device_id, "error": "level은 INFO, WARN, ERROR 중 하나여야 합니다."}
        records = [entry for entry in self.logs[device_id] if level is None or entry["level"] == level]
        return {"ok": True, "device_id": device_id, "simulated": True, "origin": "simulated_event_buffer",
                "scenario_revision": self.devices[device_id]["scenario_revision"],
                "device_available": device_id not in self.unavailable and self.devices[device_id]["connected"],
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "count": len(records[-limit:]), "matching_count": len(records), "total_count": len(self.logs[device_id]),
                "logs": copy.deepcopy(records[-limit:])}

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
            self._append_log(device_id, "WARN", "gateway", "RESTART_REJECTED", error)
            return {"ok": False, "device_id": device_id, "error": error}
        data["recovery_attempts"] += 1
        self._append_log(device_id, "INFO", "gateway", "RESTART_REQUEST_ACCEPTED", "수집 모듈 재시작 요청을 접수했습니다. 새 데이터 수신은 별도 확인이 필요합니다.")
        outcome = self.outcomes.get(device_id, "no_data")
        if outcome == "recover":
            data["telemetry_age_seconds"] = 0
            data["telemetry_sequence"] += 1
            self._append_log(device_id, "INFO", "gateway", "TELEMETRY_RECEIVED", "재시작 요청 이후 새 센서 데이터를 수신했습니다.", {"telemetry_sequence": data["telemetry_sequence"]})
        elif outcome == "verification_error":
            self.unavailable.add(device_id)
            self._append_log(device_id, "ERROR", "gateway", "STATUS_READ_FAILED", "명령 접수 후 장치 상태를 확인할 수 없습니다. 복구 결과는 미확인입니다.")
        else:
            self._append_log(device_id, "WARN", "gateway", "TELEMETRY_STILL_MISSING", "명령 접수 후 새 데이터 수신이 관측되지 않았습니다.")
        result = {"ok": True, "device_id": device_id, "command_accepted": True, "simulated": True,
                  "message": "가상 재시작 명령을 접수했습니다. 장치 상태를 다시 조회하세요."}
        if request_id:
            self.requests[request_id] = copy.deepcopy(result)
        return result
