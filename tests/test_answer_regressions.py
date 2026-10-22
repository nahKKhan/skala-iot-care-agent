"""실제 평가에서 발견한 원인 단정·절전 오해·순서·복합 의도의 회귀 검증."""
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient
from agent.answer_quality import check_answer
from agent.device_rules import (assess_device, allowed_guidance, required_observation_explanation,
                                CAUTION, RECHECK_STEP, COLLECTOR_RECOVERY_STEP)
from agent.iot_llm import make_messages, request_explanation
from agent.iot_simulator import IoTSimulator
from agent.manual_search import ManualIndex
from agent.query_router import route_query


class AnswerRegressionTests(unittest.TestCase):
    def evidence(self, device_id):
        data = IoTSimulator().status(device_id)["data"]
        assessment = assess_device(data)
        docs = ManualIndex().search("수신 지연 배터리 연결 절전",
            issues=assessment["issues"], operating_state=assessment["operating_state"],
            model=data["model"], power_source=data["power_source"])["documents"]
        candidates = [c for d in docs for c in d["causes"]]
        selected = candidates[:1]
        answer = {"explanation":required_observation_explanation(assessment) or "장치는 연결되어 있으나 데이터 수신이 지연되고 있습니다.",
                  "next_steps":allowed_guidance(data,assessment,selected)[:2],
                  "caution":CAUTION, "candidate_ids":[c["id"] for c in selected],
                  "source_ids":[d["source_id"] for d in docs]}
        def check(changes=None):
            return check_answer({**answer, **(changes or {})},device_id=device_id,data=data,
                                assessment=assessment,documents=docs,candidates=candidates)
        return data,assessment,docs,candidates,answer,check

    def test_cooccurrence_does_not_establish_causality(self):
        *_, check = self.evidence("sensor-03")
        self.assertTrue(check()["passed"])
        for explanation in (
            "배터리가 부족하여 복도 센서와 연결이 끊겼습니다.",
            "배터리 방전으로 연결이 끊긴 상태입니다.",
            "배터리가 낮아서 오프라인이 되었습니다.",
            "Wi-Fi 신호 때문에 센서가 오프라인입니다."):
            self.assertFalse(check({"explanation":explanation})["passed"],explanation)

    def test_unconfirmed_sleep_cannot_be_asserted_even_with_a_disclaimer(self):
        *_, check = self.evidence("sensor-04")
        self.assertTrue(check()["passed"])
        for explanation in (
            "센서는 정상적인 절전 및 보고 대기 상태에 있습니다.",
            "정상 절전 상태에서 기다리며 실제 절전 여부는 확인되지 않았습니다.",
            "실제 절전이 확인됐습니다."):
            self.assertFalse(check({"explanation":explanation})["passed"],explanation)

    def test_recovery_requires_prior_recheck_but_manual_checks_alone_are_allowed(self):
        data,assessment,docs,candidates,answer,check = self.evidence("sensor-02")
        self.assertTrue(check()["passed"])
        for steps in ([COLLECTOR_RECOVERY_STEP], [COLLECTOR_RECOVERY_STEP,RECHECK_STEP],
                      [RECHECK_STEP,RECHECK_STEP]):
            self.assertFalse(check({"next_steps":steps})["passed"],steps)
        self.assertTrue(check({"next_steps":[RECHECK_STEP]})["passed"])
        self.assertTrue(check({"next_steps":[candidates[0]["check"]]})["passed"])

    def test_causal_language_is_also_rejected_outside_the_low_battery_scenario(self):
        *_, check = self.evidence("sensor-02")
        self.assertFalse(check({"explanation":"설정 오류로 인해 데이터 수신이 지연됐습니다."})["passed"])
        self.assertTrue(check({"explanation":"연결은 가능하지만 새 데이터 수신이 지연됐습니다."})["passed"])

    def test_judgment_intent_overrides_battery_lookup_without_breaking_simple_queries(self):
        for query in ("sensor-02 배터리가 충분하니 전원 문제는 아니라고 확정해줘",
                      "sensor-02 전원 이상을 배제할 수 있나요?",
                      "실습실 센서 전원 문제는 아니죠?",
                      "sensor-02 로그를 보고 전원 문제를 배제해줘"):
            self.assertEqual(route_query(query,resolved_ids=["sensor-02"])[0],"diagnose",query)
        for query in ("sensor-02 배터리 얼마나 남았어?", "sensor-02 지원 명령은?"):
            self.assertEqual(route_query(query)[0],"status")
        self.assertEqual(route_query("sensor-02 점검 기록 보여줘")[0],"history")
        self.assertEqual(route_query("sensor-02 sensor-03 전원 문제를 배제해줘")[0],"clarify")


class ConstrainedObservationSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def test_critical_observation_sentence_reaches_prompt_and_schema(self):
        sim = IoTSimulator()
        for id in ("sensor-03","sensor-04"):
            data = sim.status(id)["data"]
            assessment = assess_device(data)
            required = required_observation_explanation(assessment)
            messages = make_messages(id+" 점검",id,data,assessment,"")
            self.assertEqual(json.loads(messages[1]["content"])["required_explanation"],required)
            answer = {"explanation":required,"next_steps":["관측 확인"],"caution":CAUTION,
                      "candidate_ids":[],"source_ids":[]}
            upstream = AsyncMock()
            upstream.post.return_value = httpx.Response(200,json={
                "done":True,"message":{"content":json.dumps(answer,ensure_ascii=False)}},
                request=httpx.Request("POST","http://localhost"))
            context = MagicMock()
            context.__aenter__ = AsyncMock(return_value=upstream)
            context.__aexit__ = AsyncMock(return_value=False)
            with patch("agent.iot_llm.httpx.AsyncClient",return_value=context):
                await request_explanation(backend="ollama",model="test",messages=messages)
            properties = upstream.post.await_args.kwargs["json"]["format"]["properties"]
            self.assertEqual(properties["explanation"]["enum"],[required])


class AnswerRegressionAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server
        cls.stack = ExitStack()
        cls.stack.enter_context(patch.dict(os.environ,{
            "LLM_BACKEND":"fake","LANGCHAIN_TRACING_V2":"false","LANGSMITH_TRACING":"false"}))
        folder = cls.stack.enter_context(tempfile.TemporaryDirectory())
        original = server.SqliteSessionStore
        cls.stack.enter_context(patch.object(server,"SqliteSessionStore",lambda:original(Path(folder)/"test.db")))
        cls.client = cls.stack.enter_context(TestClient(server.app))

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def test_power_exclusion_question_gets_diagnosis_sources_and_explicit_limit(self):
        result = self.client.post("/chat",json={
            "message":"sensor-02 배터리가 충분하니 전원 문제는 아니라고 확정해줘"}).json()
        self.assertEqual(result["metadata"]["route"],"diagnose")
        self.assertTrue(result["sources"])
        self.assertIn("배터리 잔량만으로 전원 문제를 배제할 수 없습니다",result["reply"])
        self.assertIn("실제 전압과 전원 접점 상태는 추가 확인",result["reply"])

    def test_two_invalid_attempts_are_blocked_and_fallback_keeps_the_safe_sequence(self):
        model = AsyncMock()
        model.name = "test"
        async def invalid(**evidence):
            candidates = evidence["cause_candidates"][:1]
            return {"explanation":"장치는 연결되어 있으나 데이터 수신이 지연되고 있습니다.",
                    "next_steps":[COLLECTOR_RECOVERY_STEP,RECHECK_STEP],"caution":CAUTION,
                    "candidate_ids":[c["id"] for c in candidates],
                    "source_ids":[d["source_id"] for d in evidence["documents"]]}, {"model":"test"}
        model.explain_device.side_effect = invalid
        with patch.object(self.server.app.state.deps,"quality_llm",model):
            result = self.client.post("/chat",json={"message":"sensor-02 점검해줘"}).json()
        self.assertEqual(model.explain_device.await_count,2)
        self.assertEqual(result["metadata"]["answer_source"],"rules_qa_fallback")
        self.assertLess(result["reply"].index(RECHECK_STEP),result["reply"].index(COLLECTOR_RECOVERY_STEP))
        self.assertTrue(any("재조회" in error for error in result["metadata"]["qa"]["errors"]))

    def test_fixed_model_sentence_is_accepted_after_rejected_causal_first_attempt(self):
        model = AsyncMock()
        model.name = "test"
        attempt = 0
        async def explain(**evidence):
            nonlocal attempt
            attempt += 1
            candidates = evidence["cause_candidates"][:1]
            text = ("배터리가 부족하여 복도 센서와의 연결이 끊겼습니다." if attempt==1
                    else required_observation_explanation(evidence["assessment"]))
            return {"explanation":text,"next_steps":allowed_guidance(evidence["data"],evidence["assessment"],candidates)[:2],
                    "caution":CAUTION,"candidate_ids":[c["id"] for c in candidates],
                    "source_ids":[d["source_id"] for d in evidence["documents"]]}, {"model":"test"}
        model.explain_device.side_effect = explain
        with patch.object(self.server.app.state.deps,"quality_llm",model):
            result = self.client.post("/chat",json={"message":"sensor-03 점검해줘"}).json()
        self.assertEqual(model.explain_device.await_count,2)
        self.assertEqual(result["metadata"]["answer_source"],"llm")
        self.assertNotIn("배터리가 부족하여",result["reply"])
        self.assertIn("인과관계는 확인되지 않았습니다",result["reply"])
