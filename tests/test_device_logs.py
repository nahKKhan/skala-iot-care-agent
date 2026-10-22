"""실제 MCP stdio 도구·조회 전용 경로·진단 근거·복구 후 로그를 검증한다."""
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from agent.iot_simulator import IoTSimulator
from agent.query_router import route_query
from agent.device_rules import CAUTION, allowed_guidance, required_observation_explanation
from agent.mcp_client import MCPClient
from agent.openai_llm import OpenAIQualityLLM
from agent.ollama_llm import OllamaQualityLLM


class DeviceLogTests(unittest.TestCase):
    def test_logs_are_read_only_isolated_and_filterable(self):
        sim = IoTSimulator()
        before = sim.status("sensor-03")
        all_logs = sim.get_logs("sensor-03")
        self.assertEqual(sim.status("sensor-03"), before)
        self.assertFalse(all_logs["device_available"])
        self.assertEqual(all_logs["logs"][-1]["code"], "DEVICE_UNREACHABLE")
        self.assertEqual(sim.get_logs("sensor-03", limit=1)["logs"], all_logs["logs"][-1:])
        errors = sim.get_logs("sensor-03", level="ERROR")
        self.assertEqual(errors["count"], 1)
        self.assertTrue(all(row["level"] == "ERROR" for row in errors["logs"]))
        all_logs["logs"][0]["message"] = "changed by caller"
        self.assertNotEqual(sim.get_logs("sensor-03")["logs"][0]["message"], "changed by caller")
        self.assertEqual(sim.get_logs("sensor-01", level="ERROR")["logs"], [])
        self.assertNotIn("outcome", json.dumps(sim.get_logs("sensor-02")))
        for device_id in ("sensor-02", "sensor-05", "sensor-06"):
            self.assertEqual([e["code"] for e in sim.get_logs(device_id)["logs"]],
                             ["TELEMETRY_RECEIVED", "REPORT_DEADLINE_MISSED", "COLLECTION_INPUT_MISSING"])

    def test_invalid_input_and_reset_revisions(self):
        sim = IoTSimulator()
        self.assertFalse(sim.get_logs("sensor-99")["ok"])
        for limit in (0, -1, 101, True, "10"):
            self.assertFalse(sim.get_logs("sensor-02", limit=limit)["ok"])
        self.assertFalse(sim.get_logs("sensor-02", level="DEBUG")["ok"])
        before = sim.get_logs("sensor-02")
        sim.restart("sensor-02", "restart")
        sim.reset("sensor-02")
        after = sim.get_logs("sensor-02")
        self.assertNotEqual(before["scenario_revision"], after["scenario_revision"])
        self.assertEqual(len(after["logs"]), len(before["logs"]))
        self.assertTrue(set(e["id"] for e in before["logs"]).isdisjoint(e["id"] for e in after["logs"]))

    def test_recovery_outcomes_do_not_turn_acceptance_into_success(self):
        sim = IoTSimulator()
        for device_id, expected in (("sensor-02", "TELEMETRY_RECEIVED"),
                                    ("sensor-05", "TELEMETRY_STILL_MISSING"),
                                    ("sensor-06", "STATUS_READ_FAILED")):
            self.assertTrue(sim.restart(device_id, device_id)["ok"])
            logs = sim.get_logs(device_id)
            self.assertEqual(logs["logs"][-2]["code"], "RESTART_REQUEST_ACCEPTED")
            self.assertEqual(logs["logs"][-1]["code"], expected)
            sim.restart(device_id, device_id)
            self.assertEqual(sim.get_logs(device_id)["logs"], logs["logs"])
        self.assertTrue(sim.get_logs("sensor-06")["ok"])
        self.assertFalse(sim.get_logs("sensor-06")["device_available"])
        self.assertFalse(sim.status("sensor-06")["ok"])

    def test_log_queries_are_not_maintenance_history_or_execution_requests(self):
        for query, expected in (("sensor-03 로그 보여줘", "logs"),
                                ("sensor-03 로그 기록 보여줘", "logs"),
                                ("sensor-03 로그로 원인을 분석해줘", "diagnose"),
                                ("sensor-03 로그 보고 재시작해줘", "diagnose"),
                                ("로그 보여줘", "clarify"),
                                ("sensor-02 sensor-03 로그", "clarify")):
            self.assertEqual(route_query(query)[0], expected, query)


class MCPDeviceLogTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_tool_limit_filter_and_unknown_device(self):
        client = MCPClient(
                           extra_env={"LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false", "PYTHONDONTWRITEBYTECODE": "1"})
        await client.start()
        try:
            self.assertEqual(set(client.sessions), {"ops"})
            tools = await client.sessions["ops"].list_tools()
            self.assertEqual({tool.name for tool in tools.tools}, {
                "list_devices", "get_device_status", "get_device_logs", "restart_collection",
                "reset_device_scenario", "reset_all_device_scenarios", "search_iot_manuals", "get_maintenance_history"})
            result = await client.call_tool("get_device_logs", {"device_id": "sensor-03", "limit": 1, "level": "ERROR"})
            self.assertTrue(result["ok"])
            self.assertTrue(result["simulated"])
            self.assertEqual(result["logs"][0]["code"], "DEVICE_UNREACHABLE")
            unknown = await client.call_tool("get_device_logs", {"device_id": "sensor-99"})
            self.assertFalse(unknown["ok"])
            self.assertEqual(unknown["logs"] if "logs" in unknown else [], [])
        finally:
            await client.stop()

    async def test_both_model_adapters_receive_observed_logs(self):
        evidence = {"query": "sensor-03 로그 기반 원인 분석", "device_id": "sensor-03",
                    "data": {"battery_pct": 5, "connected": False}, "assessment": {"issues": ["low_battery", "offline"]},
                    "runbook": "절차", "device_logs": IoTSimulator().get_logs("sensor-03")}
        for model in (OpenAIQualityLLM("test"), OllamaQualityLLM("test")):
            with patch("agent.iot_llm.request_explanation", new=AsyncMock(return_value=({}, {}))) as request:
                await model.explain_device(**evidence)
                sent = json.loads(request.await_args.kwargs["messages"][1]["content"])
                self.assertEqual(sent["device_logs"], evidence["device_logs"])
                self.assertFalse(sent["command_executed"])


class DeviceLogAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server
        cls.stack = ExitStack()
        cls.stack.enter_context(patch.dict(os.environ, {"LLM_BACKEND": "fake", "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false"}))
        folder = cls.stack.enter_context(tempfile.TemporaryDirectory())
        original = server.SqliteSessionStore
        cls.stack.enter_context(patch.object(server, "SqliteSessionStore", lambda: original(Path(folder)/"logs.db")))
        cls.client = cls.stack.enter_context(TestClient(server.app))

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def chat(self, query):
        response = self.client.post("/chat", json={"message": query, "thread_id": "logs-test"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_direct_query_unknown_and_sse_include_structured_logs(self):
        self.client.post("/api/scenario/reset", json={"device_id": "sensor-03"})
        count = len(self.client.get("/api/maintenance").json()["records"])
        result = self.chat("sensor-03 로그 기록 보여줘")
        self.assertEqual(result["metadata"]["route"], "logs")
        self.assertIn("DEVICE_UNREACHABLE", result["reply"])
        self.assertTrue(result["device_logs"]["ok"])
        self.assertIsNone(result["recovery"])
        self.assertEqual(len(self.client.get("/api/maintenance").json()["records"]), count)
        self.assertIn("등록되지 않은 장치", self.chat("sensor-99 로그 보여줘")["reply"])
        response = self.client.get("/chat/stream", params={"message": "sensor-03 로그 보여줘"})
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ") and line != "data: [DONE]"]
        final = next(e for e in events if e["type"] == "FinalAnswer")
        self.assertEqual(final["device_logs"]["logs"], result["device_logs"]["logs"])
        self.assertIsNone(final["recovery"])

    def test_diagnosis_passes_logs_to_model_and_archives_evidence(self):
        async def explain(**evidence):
            candidates = evidence["cause_candidates"][:2]
            return {"explanation": required_observation_explanation(evidence["assessment"]) or "현재 관측 상태에 대한 추가 점검이 필요합니다.",
                    "next_steps": allowed_guidance(evidence["data"], evidence["assessment"], candidates)[:2],
                    "caution": CAUTION, "candidate_ids": [c["id"] for c in candidates],
                    "source_ids": [d["source_id"] for d in evidence["documents"]]}, {"model": "test", "total_tokens": 1}
        model = AsyncMock()
        model.name = "test"
        model.explain_device.side_effect = explain
        with patch.object(self.server.app.state.deps, "quality_llm", model):
            result = self.chat("sensor-03 로그로 원인을 분석해줘")
        evidence = model.explain_device.await_args.kwargs
        self.assertEqual(result["device_logs"], evidence["device_logs"])
        self.assertEqual(result["metadata"]["answer_source"], "llm")
        self.assertIn("DEVICE_UNREACHABLE", result["reply"])
        self.assertIsNone(result["recovery"])
        records = self.client.get("/api/maintenance", params={"device_id": "sensor-03"}).json()["records"]
        self.assertEqual(records[0]["evidence"]["device_logs"], result["device_logs"])

    def test_recovery_events_are_visible_and_repeated_requests_do_not_duplicate(self):
        self.client.post("/api/scenario/reset", json={"device_id": "sensor-02"})
        offer = self.chat("sensor-02 점검해줘")["recovery"]
        payload = {"device_id": "sensor-02", "request_id": "logs-recover", "scenario_revision": offer["scenario_revision"], "expected_sequence": 0}
        self.assertTrue(self.client.post("/api/recover", json=payload).json()["recovery_verified"])
        result = self.chat("sensor-02 로그 보여줘")
        self.assertEqual(result["device_logs"]["logs"][-1]["details"]["telemetry_sequence"], 1)
        self.client.post("/api/recover", json=payload)
        self.assertEqual(self.chat("sensor-02 로그 보여줘")["device_logs"]["logs"], result["device_logs"]["logs"])

    def test_log_tool_failure_is_explicit_and_diagnosis_continues(self):
        mcp = self.server.app.state.deps.mcp
        original = mcp.call_tool
        async def call_tool(name, args, **kwargs):
            if name == "get_device_logs":
                raise RuntimeError("private upstream failure")
            return await original(name, args, **kwargs)
        with patch.object(mcp, "call_tool", side_effect=call_tool):
            result = self.chat("sensor-01 점검해줘")
            direct = self.chat("sensor-01 로그 보여줘")
        self.assertFalse(result["device_logs"]["ok"])
        self.assertIn("로그 조회 실패", result["reply"])
        self.assertIn("로그 조회 실패", direct["reply"])
        self.assertNotIn("private upstream failure", result["reply"])
        self.assertIsNone(result["recovery"])
