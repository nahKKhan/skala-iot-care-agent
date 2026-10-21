"""복구 버튼의 API 계약과 프록시를 실제 MCP/가상 장치로 검증한다."""
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["LLM_BACKEND"] = "fake"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"

import httpx
from fastapi.testclient import TestClient
import server
import web_demo_server


class BackendRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        folder = self.stack.enter_context(tempfile.TemporaryDirectory())
        original_store = server.SqliteSessionStore
        self.stack.enter_context(patch.object(
            server, "SqliteSessionStore",
            lambda: original_store(Path(folder) / "sessions.db"),
        ))
        self.client = self.stack.enter_context(TestClient(server.app))

    def inspect(self, message):
        response = self.client.post("/chat", json={"message": message, "thread_id": "button-test"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_only_supported_delayed_connected_device_has_offer(self):
        for message in ("sensor-01 점검", "sensor-03 점검", "sensor-99 점검", "센서 점검", "sensor-01 sensor-02 점검"):
            with self.subTest(message=message):
                self.assertIsNone(self.inspect(message)["recovery"])
        offer = self.inspect("sensor-02 점검")["recovery"]
        self.assertEqual(offer["device_id"], "sensor-02")
        self.assertEqual(offer["action"], "restart_collection")
        self.assertIs(offer["simulated"], True)

    def test_sse_delivers_structured_offer(self):
        response = self.client.get("/chat/stream", params={"message": "sensor-02 점검", "thread_id": "sse-test"})
        self.assertEqual(response.status_code, 200)
        events = [json.loads(line[6:]) for line in response.text.splitlines()
                  if line.startswith("data: ") and line != "data: [DONE]"]
        final = next(event for event in events if event["type"] == "FinalAnswer")
        self.assertEqual(final["recovery"]["device_id"], "sensor-02")
        self.assertIn("데이터 수신 지연", final["reply"])
        self.assertIn("data: [DONE]", response.text)

    def test_recovery_updates_chat_and_rejects_repeat(self):
        self.assertIsNotNone(self.inspect("sensor-02 점검")["recovery"])
        response = self.client.post("/api/recover", json={"device_id": "sensor-02"})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertIs(result["recovery_verified"], True)
        self.assertEqual(result["before"]["telemetry_sequence"], 0)
        self.assertEqual(result["after"]["telemetry_sequence"], 1)
        self.assertEqual(result["after"]["telemetry_age_seconds"], 0)
        report = self.inspect("sensor-02 점검")
        self.assertIsNone(report["recovery"])
        self.assertIn("이상이 발견되지 않았습니다", report["reply"])
        repeated = self.client.post("/api/recover", json={"device_id": "sensor-02"})
        self.assertEqual(repeated.status_code, 409)
        self.assertIn("수신 지연이 없습니다", repeated.json()["detail"])

    def test_unsupported_targets_are_rejected(self):
        for device_id, status in (("sensor-01", 409), ("sensor-03", 409), ("sensor-99", 404)):
            with self.subTest(device_id=device_id):
                response = self.client.post("/api/recover", json={"device_id": device_id})
                self.assertEqual(response.status_code, status, response.text)


class RecoveryProxyTests(unittest.TestCase):
    def call_proxy(self, *, response=None, error=None):
        upstream = AsyncMock()
        upstream.post.return_value = response
        upstream.post.side_effect = error
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=upstream)
        context.__aexit__ = AsyncMock(return_value=False)
        with patch.object(web_demo_server.httpx, "AsyncClient", return_value=context):
            with TestClient(web_demo_server.app) as client:
                result = client.post("/api/recover", json={"device_id": "sensor-02"})
        self.assertEqual(upstream.post.await_count, 1)  # 복구 명령 자동 재전송 금지
        call = upstream.post.await_args
        self.assertEqual(call.args[0], "http://127.0.0.1:8100/api/recover")
        self.assertEqual(json.loads(call.kwargs["content"]), {"device_id": "sensor-02"})
        return result

    def test_preserves_backend_status_and_body(self):
        for status, payload in ((200, {"recovery_verified": True}), (409, {"detail": "실행 거부"}), (404, {"detail": "없는 장치"})):
            with self.subTest(status=status):
                result = self.call_proxy(response=httpx.Response(status, json=payload))
                self.assertEqual(result.status_code, status)
                self.assertEqual(result.json(), payload)

    def test_timeout_connection_error_and_invalid_json(self):
        for error, status in ((httpx.ReadTimeout("test timeout"), 504), (httpx.ConnectError("test connection"), 503)):
            with self.subTest(status=status):
                result = self.call_proxy(error=error)
                self.assertEqual(result.status_code, status)
                self.assertIn("detail", result.json())
        result = self.call_proxy(response=httpx.Response(200, text="not JSON"))
        self.assertEqual(result.status_code, 502)


    def test_bulk_reset_proxy_preserves_result_and_does_not_retry_on_timeout(self):
        for error, status in ((None, 200), (httpx.ReadTimeout("lost reset response"), 504)):
            upstream = AsyncMock()
            upstream.post.return_value = httpx.Response(200, json={"ok": True, "count": 6, "device_ids": ["sensor-01"]})
            upstream.post.side_effect = error
            context = MagicMock()
            context.__aenter__ = AsyncMock(return_value=upstream)
            context.__aexit__ = AsyncMock(return_value=False)
            with patch.object(web_demo_server.httpx, "AsyncClient", return_value=context):
                with TestClient(web_demo_server.app) as client:
                    result = client.post("/api/scenario/reset-all")
            self.assertEqual(result.status_code, status)
            self.assertEqual(upstream.post.await_count, 1)
            self.assertEqual(upstream.post.await_args.args[0], "http://127.0.0.1:8100/api/scenario/reset-all")
            if error is None:
                self.assertEqual(result.json()["count"], 6)


if __name__ == "__main__":
    unittest.main()
