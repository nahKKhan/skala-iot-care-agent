"""한국어 조사와 소개·상태·이력·매뉴얼 질문의 분기 회귀 검사."""
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from agent.query_router import device_ids, route_query


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


class ChatIntentAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        cls.stack=ExitStack()
        cls.stack.enter_context(patch.dict(os.environ,{"LLM_BACKEND":"fake","SUPERVISOR_VERSION":"v2","LANGCHAIN_TRACING_V2":"false","LANGSMITH_TRACING":"false"}))
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
