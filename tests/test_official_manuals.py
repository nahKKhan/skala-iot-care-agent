"""공식 출처·모델 적용 범위와 실제 보고 조건을 반영한 가상 진단 계약."""
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

from fastapi.testclient import TestClient
from agent.device_rules import assess_device, can_recover, REPORT_GRACE_SECONDS, SHELLY_MANUAL_URL
from agent.iot_simulator import IoTSimulator
from agent.manual_search import ManualIndex, source_description


class OfficialManualTests(unittest.TestCase):
    def setUp(self):
        self.index = ManualIndex()

    def test_sources_are_auditable_and_policies_are_separate(self):
        result = self.index.search("수신 지연")
        self.assertEqual((result["manufacturer_document_count"], result["policy_document_count"]), (8, 2))
        official = [d for d in self.index.chunks if d["source_type"] == "manufacturer_summary"]
        self.assertEqual(len(official), 24)
        self.assertEqual(len({d["source_url"] for d in official}), 6)
        for d in official:
            self.assertIn(urlparse(d["source_url"]).hostname, {"kb.shelly.cloud", "shelly-api-docs.shelly.cloud"})
            self.assertEqual(d["publisher"], "Shelly")
            self.assertTrue(d["source_section"] and d["retrieved_at"] and d["source_title"])
            self.assertEqual(d["applicable_models"], ["shelly_ht_gen3"])
            self.assertIn(d["source_url"], source_description(d))
        for d in self.index.chunks:
            if d["source_type"] == "project_policy":
                self.assertIsNone(d["source_url"])
                self.assertIn("프로젝트", source_description(d))

    def test_reporting_facts_can_be_retrieved_without_device_state(self):
        docs = self.index.search("배터리 측정 보고 주기 2시간", model="shelly_ht_gen3")["documents"]
        d = next(d for d in docs if d["document_id"] == "normal_operation")
        self.assertIn("2시간", d["text"])
        self.assertIn("0.5", d["text"])
        self.assertEqual(d["source_url"], SHELLY_MANUAL_URL)

    def test_other_models_do_not_receive_shelly_manuals(self):
        result = self.index.search("데이터 수신 지연 복구", issues=["telemetry_delayed"], model="other_sensor")
        self.assertTrue(all(d["source_type"] == "project_policy" for d in result["documents"]))
        self.assertEqual(self.index.search("배터리", issues=["low_battery"], model="other_sensor")["documents"], [])

    def test_invalid_official_provenance_fails_instead_of_pretending_to_be_official(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"bad.md"
            path.write_text('# bad\n<!-- meta: {"source_type":"manufacturer_summary","source_url":"https://example.com/fake"} -->\n## test\ntext')
            with self.assertRaisesRegex(ValueError, "출처 정보"):
                ManualIndex(folder)


class ManufacturerReportingTests(unittest.TestCase):
    def setUp(self):
        self.seed = IoTSimulator().seed

    def test_usb_reporting_boundary_and_project_grace(self):
        base = self.seed["sensor-02"]
        for age, expected in ((300, []), (360, []), (361, ["telemetry_delayed"])):
            result = assess_device({**base, "telemetry_age_seconds": age})
            self.assertEqual(result["issues"], expected)
            self.assertEqual(result["reporting_policy"]["max_report_interval_seconds"], 300)
            self.assertEqual(result["reporting_policy"]["grace_seconds"], REPORT_GRACE_SECONDS)
            self.assertEqual(result["reporting_policy"]["source_url"], SHELLY_MANUAL_URL)

    def test_battery_silence_is_not_automatically_offline_or_a_confirmed_sleep(self):
        base = self.seed["sensor-04"]
        for age in (600, 7200, 7260):
            result = assess_device({**base, "telemetry_age_seconds": age})
            self.assertEqual(result["issues"], [])
            self.assertEqual(result["operating_state"], "sleeping")
            self.assertFalse(can_recover({**base, "telemetry_age_seconds": age}))
        expired = {**base, "telemetry_age_seconds": 7261, "wake_in_seconds": 999}
        self.assertEqual(assess_device(expired)["issues"], ["offline"])
        self.assertEqual(assess_device({**expired, "connected": True})["issues"], ["telemetry_delayed"])
        self.assertEqual(assess_device({**base, "battery_pct": 5})["issues"], ["low_battery"])

    def test_usb_battery_is_not_external_supply_and_null_is_not_zero(self):
        base = self.seed["sensor-02"]
        for battery in (None, 0, 5):
            self.assertEqual(assess_device({**base, "battery_pct": battery})["issues"], ["telemetry_delayed"])
            self.assertTrue(can_recover({**base, "battery_pct": battery}))

    def test_bad_profile_values_and_real_device_recovery_are_rejected(self):
        base = self.seed["sensor-02"]
        for changes in ({"power_source":"unknown"}, {"report_interval_seconds":60},
                        {"telemetry_age_seconds":float("nan")}, {"battery_pct":float("inf")}):
            self.assertEqual(assess_device({**base, **changes})["issues"], ["invalid_data"])
            self.assertFalse(can_recover({**base, **changes}))
        for changes in ({"simulated":False}, {"recovery_scope":"device_reboot"}):
            self.assertFalse(can_recover({**base, **changes}))


class OfficialManualAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        cls.stack = ExitStack()
        cls.stack.enter_context(patch.dict(os.environ, {
            "LLM_BACKEND":"fake", "LANGCHAIN_TRACING_V2":"false", "LANGSMITH_TRACING":"false"}))
        folder = cls.stack.enter_context(tempfile.TemporaryDirectory())
        original = server.SqliteSessionStore
        cls.stack.enter_context(patch.object(server, "SqliteSessionStore", lambda: original(Path(folder)/"test.db")))
        cls.client = cls.stack.enter_context(TestClient(server.app))

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def test_chat_citations_and_saved_evidence_retain_original_sources(self):
        result = self.client.post("/chat", json={"message":"sensor-02 점검해줘"}).json()
        sources = result["sources"]
        official = [d for d in sources if d["source_type"] == "manufacturer_summary"]
        self.assertTrue(official, result["reply"])
        self.assertIn("300초", result["reply"])
        self.assertIn("실제 Shelly 장치를 재부팅하지 않습니다", result["reply"])
        for d in official:
            self.assertIn(d["source_url"], result["reply"])
        records = self.client.get("/api/maintenance", params={"device_id":"sensor-02"}).json()["records"]
        record = next(r for r in records if r["id"] == result["metadata"]["maintenance_id"])
        self.assertEqual(record["evidence"]["manual_sources"], sources)
        self.assertTrue(record["evidence"]["manual_index_version"])

    def test_sleeping_device_and_general_manual_keep_provenance(self):
        result = self.client.post("/chat", json={"message":"sensor-04 점검해줘"}).json()
        self.assertIsNone(result["recovery"])
        self.assertIn("실제 절전 여부는 미확인", result["reply"])
        self.assertIn("7200초", result["reply"])
        general = self.client.post("/chat", json={"message":"배터리 측정 보고 주기 매뉴얼 알려줘"}).json()
        self.assertEqual(general["metadata"]["route"], "manual")
        self.assertTrue(general["sources"])
        self.assertTrue(any(d.get("source_url") for d in general["sources"]))
        self.assertIn("원문:", general["reply"])

    def test_nullable_battery_and_low_battery_waiting_do_not_hide_observations(self):
        import server
        mcp = server.app.state.deps.mcp
        original = mcp.call_tool
        async def call_tool(name, args, **kwargs):
            result = await original(name, args, **kwargs)
            if name == "get_device_status" and result.get("ok"):
                result["data"]["battery_pct"] = None if args["device_id"] == "sensor-02" else 5
            return result
        with patch.object(mcp, "call_tool", side_effect=call_tool):
            usb = self.client.post("/chat", json={"message":"sensor-02 점검해줘"}).json()
            self.assertIn("배터리: 미확인", usb["reply"])
            self.assertNotIn("None%", usb["reply"])
            waiting = self.client.post("/chat", json={"message":"sensor-04 점검해줘"}).json()
            self.assertIn("배터리 부족", waiting["reply"])
            self.assertIn("현장 점검", waiting["reply"])
            self.assertNotIn("다음 조치: 전원 방식별 보고 조건", waiting["reply"])
            self.assertIsNone(waiting["recovery"])
