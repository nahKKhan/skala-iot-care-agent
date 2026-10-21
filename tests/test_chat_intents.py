"""한국어 조사와 소개·상태·이력·매뉴얼 질문의 분기 회귀 검사."""
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from agent.query_router import device_ids, route_query, find_named_devices


class KoreanQueryTests(unittest.TestCase):
    def test_device_ids_with_particles_and_invalid_boundaries(self):
        for query in ("sensor-02가 뭐더라", "sensor-02는 어떤 장치야?", "sensor-02를 점검해줘", "SENSOR-02의 배터리는?", "sensor-02랑 sensor-03"):
            self.assertIn("sensor-02", device_ids(query))
        for query in ("xsensor-02 점검", "sensor-02test", "sensor-02_extra", "sensor-020x"):
            self.assertEqual(device_ids(query), [])

    def test_routes_follow_question_intent(self):
        cases={"sensor-02가 뭐더라":"device_info", "sensor-02 이름 알려줘":"device_info",
               "sensor-02 배터리 얼마나 남았어":"status", "sensor-02 전송 주기":"status",
               "sensor-02 점검 기록 보여줘":"history", "sensor-02를 점검해줘":"diagnose",
               "sensor-02 왜 데이터가 안 와?":"diagnose", "sensor-02 배터리 부족해":"diagnose",
               "등록된 장치 목록 보여줘":"list_devices", "정상 절전과 수신 지연은 어떻게 달라?":"manual",
               "배터리가 부족할 때 재시작해도 돼?":"manual", "할 수 있는 일이 뭐야?":"help",
               "오늘 점심 뭐 먹지?":"help", "센서가 이상해요":"clarify", "sensor-01 sensor-02 점검":"clarify"}
        for query, expected in cases.items():
            with self.subTest(query=query):
                self.assertEqual(route_query(query)[0],expected)


    def test_registered_names_with_particles_and_exact_name_preference(self):
        devices = [{"device_id": "sensor-03", "name": "복도 온습도 센서"},
                   {"device_id": "sensor-07", "name": "복도 미세먼지 센서"},
                   {"device_id": "sensor-02", "name": "실습실 온습도 센서"},
                   {"device_id": "sensor-04", "name": "예약 절전 센서"}]
        self.assertEqual([d["device_id"] for d in find_named_devices("복도를 관리하는 센서가 뭐가 있더라", devices)], ["sensor-03", "sensor-07"])
        self.assertEqual([d["device_id"] for d in find_named_devices("복도온습도센서 점검해줘", devices)], ["sensor-03"])
        self.assertEqual([d["device_id"] for d in find_named_devices("실습실 센서 배터리는?", devices)], ["sensor-02"])
        self.assertEqual(find_named_devices("체육관 센서 뭐가 있어?", devices), [])
        self.assertEqual(find_named_devices("정상 절전과 수신 지연은 어떻게 달라?", devices), [])

    def test_name_resolution_keeps_action_intent_and_explicit_id_priority(self):
        self.assertEqual(route_query("실습실 센서 배터리 얼마야?", resolved_ids=["sensor-02"])[0], "status")
        self.assertEqual(route_query("복도를 관리하는 센서가 뭐가 있더라", resolved_ids=["sensor-03"])[0], "device_info")
        self.assertEqual(route_query("실습실 센서 점검해줘", resolved_ids=["sensor-02"])[0], "diagnose")
        self.assertEqual(route_query("복도 센서 로그 보여줘", resolved_ids=["sensor-03"])[0], "logs")
        self.assertEqual(route_query("sensor-99 복도 센서 점검", resolved_ids=["sensor-03"])[1], ["sensor-99"])


class ChatIntentAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        cls.stack=ExitStack()
        cls.stack.enter_context(patch.dict(os.environ,{"LLM_BACKEND":"fake","SUPERVISOR_VERSION":"v1","LANGCHAIN_TRACING_V2":"false","LANGSMITH_TRACING":"false"}))
        folder=cls.stack.enter_context(tempfile.TemporaryDirectory())
        original=server.SqliteSessionStore
        cls.stack.enter_context(patch.object(server,"SqliteSessionStore",lambda:original(Path(folder)/"intents.db")))
        cls.client=cls.stack.enter_context(TestClient(server.app))

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def chat(self,query):
        response=self.client.post("/chat",json={"message":query,"thread_id":"intent-test"})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_introduction_and_status_are_not_diagnoses(self):
        result=self.chat("sensor-02가 뭐더라")
        self.assertIn("실습실 온습도 센서",result["reply"])
        self.assertEqual(result["metadata"]["route"],"device_info")
        self.assertIsNone(result["recovery"])
        self.assertEqual(self.client.get("/api/maintenance").json()["records"],[])
        for query, expected in (("sensor-02의 배터리 얼마나 남았어?","80%"),("sensor-02 전송 주기는?","60초"),("sensor-02 지원 명령은?","restart_collection")):
            result=self.chat(query)
            self.assertIn(expected,result["reply"])
            self.assertIsNone(result["recovery"])
        diagnosed=self.chat("sensor-02를 점검해줘")
        self.assertEqual(diagnosed["recovery"]["device_id"],"sensor-02")

    def test_registry_history_help_and_unknown_device(self):
        self.assertIn("sensor-06",self.chat("등록된 장치 목록 보여줘")["reply"])
        self.assertIn("등록되지 않은 장치",self.chat("sensor-99가 뭐야?")["reply"])
        self.assertIn("IoT 장치",self.chat("오늘 점심 뭐 먹지?")["reply"])
        self.chat("sensor-01 점검해줘")
        history=self.chat("sensor-01 점검 기록 보여줘")
        self.assertIn("정상",history["reply"])
        self.assertEqual(history["metadata"]["route"],"history")
        self.assertIsNone(history["recovery"])

    def test_manual_question_has_sources_without_assuming_a_device(self):
        result=self.chat("정상 절전과 수신 지연은 어떻게 달라?")
        self.assertEqual(result["metadata"]["route"],"manual")
        self.assertTrue(result["sources"])
        self.assertIsNone(result["recovery"])
        self.assertIn("특정 장치의 현재 상태를 점검한 결과는 아닙니다",result["reply"])

    def test_sse_routes_the_same_introduction_question(self):
        response=self.client.get("/chat/stream",params={"message":"sensor-02가 뭐더라"})
        events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ") and line!="data: [DONE]"]
        final=next(e for e in events if e["type"]=="FinalAnswer")
        self.assertIn("실습실 온습도 센서",final["reply"])
        self.assertEqual(final["metadata"]["route"],"device_info")
        self.assertIsNone(final["recovery"])


    def test_stale_legacy_setting_cannot_bypass_iot_graph(self):
        health = self.client.get("/health").json()
        self.assertEqual(health["pipeline"], "iot")
        self.assertEqual(health["llm_backend"], "fake")
        self.assertEqual(health["quality_llm"], "rules")
        self.assertEqual(self.client.get("/health").json()["instance_id"], health["instance_id"])
        self.assertEqual(set(self.client.app.state.deps.mcp.sessions), {"ops"})
        result = self.chat("sensor-03 로그 보여줘")
        self.assertEqual(result["metadata"]["route"], "logs")
        self.assertEqual(result["metadata"]["pipeline"], "iot")
        self.assertTrue(result["device_logs"]["ok"])
        response = self.client.get("/chat/stream", params={"message": "sensor-03 로그 보여줘", "thread_id": "cleanup-sse"})
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ") and line != "data: [DONE]"]
        final = next(e for e in events if e["type"] == "FinalAnswer")
        self.assertEqual(final["reply"], result["reply"])
        self.assertEqual(final["device_logs"]["logs"], result["device_logs"]["logs"])
        self.assertEqual(final["metadata"]["pipeline"], "iot")
        stored = self.client.app.state.deps.session_store.conn.execute(
            "SELECT role,content FROM messages WHERE thread_id=? ORDER BY rowid", ("cleanup-sse",)).fetchall()
        self.assertEqual(stored, [("user", "sensor-03 로그 보여줘"), ("assistant", final["reply"])])


    def test_name_lookup_is_registry_based_without_model_or_diagnosis(self):
        model = AsyncMock()
        before = self.client.get("/api/maintenance").json()["records"]
        with patch.object(self.client.app.state.deps, "quality_llm", model):
            result = self.chat("복도를 관리하는 센서가 뭐가 있더라")
        self.assertEqual(result["device_id"], "sensor-03")
        self.assertEqual(result["metadata"]["route"], "device_info")
        self.assertIn("복도 온습도 센서", result["reply"])
        self.assertIn("등록된 장치 이름을 기준", result["reply"])
        self.assertIsNone(result["recovery"])
        model.explain_device.assert_not_awaited()
        self.assertEqual(self.client.get("/api/maintenance").json()["records"], before)
        self.assertIn("찾지 못했습니다", self.chat("체육관을 관리하는 센서가 뭐가 있어?")["reply"])
        self.assertEqual(self.chat("무엇을 할 수 있어?")["metadata"]["route"], "help")
        unknown = self.chat("sensor-99 복도 센서 점검")
        self.assertIn("등록되지 않은 장치", unknown["reply"])
        self.assertIsNone(unknown["recovery"])

    def test_named_status_logs_diagnosis_and_sse_keep_the_resolved_target(self):
        self.assertEqual(self.chat("실습실 센서 배터리 얼마나 남았어?")["device_id"], "sensor-02")
        logs = self.chat("복도 센서 로그 보여줘")
        self.assertEqual(logs["device_logs"]["device_id"], "sensor-03")
        diagnosis = self.chat("실습실 센서를 점검해줘")
        self.assertEqual(diagnosis["metadata"]["route"], "diagnose")
        self.assertEqual(diagnosis["recovery"]["device_id"], "sensor-02")
        response = self.client.get("/chat/stream", params={"message": "복도를 관리하는 센서가 뭐가 있더라"})
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ") and line != "data: [DONE]"]
        final = next(e for e in events if e["type"] == "FinalAnswer")
        self.assertEqual(final["device_id"], "sensor-03")
        self.assertEqual(final["metadata"]["route"], "device_info")
        self.assertIsNone(final["recovery"])

    def test_ambiguous_names_list_candidates_and_do_not_select_a_device_for_actions(self):
        mcp = self.client.app.state.deps.mcp
        original = mcp.call_tool
        calls = []
        async def call_tool(name, args, **kwargs):
            calls.append(name)
            if name == "list_devices":
                return {"devices": [{"device_id": "sensor-03", "name": "복도 온습도 센서"},
                                    {"device_id": "sensor-07", "name": "복도 미세먼지 센서"}]}
            return await original(name, args, **kwargs)
        with patch.object(mcp, "call_tool", side_effect=call_tool):
            listing = self.chat("복도를 관리하는 센서가 뭐가 있더라")
            self.assertEqual(listing["metadata"]["route"], "device_search")
            self.assertIn("sensor-03", listing["reply"])
            self.assertIn("sensor-07", listing["reply"])
            ambiguous = self.chat("복도 센서 점검해줘")
            self.assertEqual(ambiguous["metadata"]["route"], "clarify")
            self.assertIn("하나를 골라", ambiguous["reply"])
            self.assertIsNone(ambiguous["recovery"])
        self.assertEqual(set(calls), {"list_devices"})
