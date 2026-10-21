"""문서 검색·정상 절전·미복구·확인 불가·영속 이력·중복 실행 방지 검증."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from agent.manual_search import ManualIndex
from agent.device_rules import assess_device, can_recover, CAUTION
from agent.iot_simulator import IoTSimulator
from agent.session_store import SqliteSessionStore
from agent.answer_quality import check_answer
from agent.openai_llm import OpenAIQualityLLM


class RetrievalPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = ManualIndex()

    def test_distinct_documents_and_no_irrelevant_filler(self):
        self.assertEqual(len({c["document_id"] for c in self.index.chunks}), 10)
        self.assertEqual(len(self.index.chunks), 30)
        self.assertEqual(self.index.search("케이크 레시피")["documents"], [])
        cases = [("배터리 방전 교체", ["low_battery"], "low_battery"),
                 ("게이트웨이 통신 연결 끊김", ["offline"], "transport_path"),
                 ("데이터 갱신 멈춤 수신 지연", ["telemetry_delayed"], "telemetry_delayed")]
        for query, issues, wanted in cases:
            docs = self.index.search(query, issues=issues)["documents"]
            self.assertIn(wanted, [d["document_id"] for d in docs])
            self.assertEqual(len(docs), len({d["document_id"] for d in docs}))
            self.assertTrue(all(d["source_id"] and d["text"] and d["score"] > 0 for d in docs))

    def test_sleeping_and_boundaries(self):
        data = IoTSimulator().status("sensor-04")["data"]
        assessment = assess_device(data)
        self.assertEqual(assessment["issues"], [])
        self.assertEqual(assessment["operating_state"], "sleeping")
        self.assertFalse(can_recover(data))
        docs = self.index.search("절전 기상 sleeping", issues=[], operating_state="sleeping")["documents"]
        self.assertIn("normal_sleep", [d["document_id"] for d in docs])
        self.assertNotIn("normal_operation", [d["document_id"] for d in docs])
        base = IoTSimulator().status("sensor-02")["data"]
        for battery, age, issues in [(20,360,["low_battery"]),(21,360,[]),(21,361,["telemetry_delayed"])]:
            self.assertEqual(assess_device({**base,"model":"legacy_demo","report_interval_seconds":120,"battery_pct":battery,"telemetry_age_seconds":age})["issues"], issues)
        self.assertEqual(assess_device({**base,"report_interval_seconds":0})["issues"], ["invalid_data"])

    def test_no_recovery_on_bad_observation_or_sleep(self):
        base = IoTSimulator().status("sensor-02")["data"]
        for changes in ({"battery_pct":False},{"battery_pct":101},{"connected":"true"},{"telemetry_age_seconds":-1}):
            self.assertFalse(can_recover({**base,**changes}))

    def test_sources_candidates_and_unsupported_claims_are_checked(self):
        data=IoTSimulator().status("sensor-02")["data"]
        assessment=assess_device(data)
        docs=self.index.search("telemetry_delayed",issues=assessment["issues"])["documents"]
        candidates=[c for d in docs for c in d["causes"]]
        answer={"explanation":"추가 점검이 필요합니다.","next_steps":[candidates[0]["check"]],"caution":CAUTION,
                "candidate_ids":[candidates[0]["id"]],"source_ids":[candidates[0]["source_id"]]}
        def check(value):
            return check_answer(value,device_id="sensor-02",data=data,assessment=assessment,documents=docs,candidates=candidates)["passed"]
        self.assertTrue(check(answer))
        for changes in ({"source_ids":["nonexistent#1"]},{"candidate_ids":["invented_cause"]},
                        {"explanation":"배터리가 충분하므로 전원 문제는 아닙니다."},
                        {"explanation":"원격 복구를 완료했습니다."},{"explanation":"배터리는 77%입니다."},
                        {"caution":"]"},{"next_steps":['caution": ']},
                        {"explanation":"현재 수집 작업이 중단된 것으로 판단됩니다."},
                        {"explanation":"고장 가능성은 배제됩니다."},
                        {"explanation":"현재는 전원 공급 불안정 및 오프라인 상태입니다."}):
            self.assertFalse(check({**answer,**changes}), changes)


class SimulatorStoreTests(unittest.TestCase):
    def test_command_acceptance_is_not_recovery(self):
        sim=IoTSimulator()
        for device_id, expected in (("sensor-02",True),("sensor-05",False),("sensor-06",None)):
            before=sim.status(device_id)["data"]
            command=sim.restart(device_id, device_id+"-request")
            self.assertTrue(command["command_accepted"])
            after=sim.status(device_id)
            verified=(after["data"]["telemetry_sequence"] > before["telemetry_sequence"]) if after["ok"] else None
            self.assertIs(verified,expected)
            self.assertNotIn("outcome", before)
            self.assertNotIn("scenario", before.get("name", ""))
        self.assertFalse(sim.restart("sensor-05","new-request")["ok"])
        self.assertEqual(sim.restart("sensor-02","sensor-02-request")["command_accepted"],True)
        self.assertEqual(sim.status("sensor-02")["data"]["telemetry_sequence"],1)

    def test_persistent_history_deduplication_and_request_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"test.db"
            store=SqliteSessionStore(path)
            evidence={"data":{"sample":1},"assessment":{"issues":[]}}
            first=store.record_maintenance("sensor-01","inspection","normal","정상",evidence)
            self.assertEqual(first,store.record_maintenance("sensor-01","inspection","normal","정상",evidence))
            self.assertIsNone(store.reserve_recovery("request-1",{"device_id":"sensor-02"}))
            self.assertEqual(store.reserve_recovery("request-1",{"device_id":"sensor-02"})["http_status"],409)
            store.finish_recovery("request-1",{"recovery_verified":False})
            store.close()
            store=SqliteSessionStore(path)
            try:
                self.assertEqual(len(store.maintenance_history()),1)
                self.assertEqual(store.reserve_recovery("request-1",{"device_id":"sensor-02"})["body"],{"recovery_verified":False})
                self.assertEqual(store.reserve_recovery("request-1",{"device_id":"sensor-03"})["http_status"],409)
            finally:
                store.close()


class IoTDepthAPITests(unittest.TestCase):
    def setUp(self):
        import server
        self.server=server
        self.stack=ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ,{"LLM_BACKEND":"fake","LANGCHAIN_TRACING_V2":"false","LANGSMITH_TRACING":"false"}))
        folder=self.stack.enter_context(tempfile.TemporaryDirectory())
        original=server.SqliteSessionStore
        self.stack.enter_context(patch.object(server,"SqliteSessionStore",lambda:original(Path(folder)/"test.db")))
        self.client=self.stack.enter_context(TestClient(server.app))

    def inspect(self,id):
        result=self.client.post("/chat",json={"message":id+" 점검"})
        self.assertEqual(result.status_code,200,result.text)
        return result.json()

    def test_outcomes_are_recorded_and_not_retried(self):
        for id,expected,status in (("sensor-02",True,"resolved"),("sensor-05",False,"needs_visit"),("sensor-06",None,"verification_pending")):
            report=self.inspect(id)
            offer=report["recovery"]
            payload={"device_id":id,"request_id":"recover-"+id,"scenario_revision":offer["scenario_revision"],"expected_sequence":offer["expected_sequence"]}
            response=self.client.post("/api/recover",json=payload)
            self.assertEqual(response.status_code,200,response.text)
            self.assertIs(response.json()["recovery_verified"],expected)
            self.assertEqual(response.json()["status"],status)
            self.assertEqual(self.client.post("/api/recover",json=payload).json(),response.json())
            repeated=self.client.post("/api/recover",json={**payload,"request_id":"another-"+id})
            self.assertEqual(repeated.status_code,409)
            records=self.client.get("/api/maintenance",params={"device_id":id}).json()["records"]
            self.assertEqual(len([r for r in records if r["kind"]=="recovery"]),1)
            self.assertTrue(any(r["status"]==status for r in records))

    def test_reset_rejects_old_offer_and_keeps_records(self):
        offer=self.inspect("sensor-02")["recovery"]
        self.client.post("/api/scenario/reset",json={"device_id":"sensor-02"})
        response=self.client.post("/api/recover",json={"device_id":"sensor-02","scenario_revision":offer["scenario_revision"],"expected_sequence":0})
        self.assertEqual(response.status_code,409)
        self.assertIn("상태가 바뀌",response.json()["detail"])
        self.assertEqual(len(self.client.get("/api/maintenance").json()["records"]),1)
        self.assertIsNotNone(self.inspect("sensor-02")["recovery"])

    def test_sleep_sources_and_deduplicated_inspection_history(self):
        result=self.inspect("sensor-04")
        self.assertIsNone(result["recovery"])
        self.assertIn("정상 절전",result["reply"])
        self.assertIn("normal_sleep",[s["document_id"] for s in result["sources"]])
        self.inspect("sensor-04")
        self.assertEqual(len(self.client.get("/api/maintenance").json()["records"]),1)
        self.assertEqual(len(self.client.get("/api/devices").json()["devices"]),6)

    def test_qa_rewrites_once_then_blocks_unsupported_output(self):
        answer={"explanation":"배터리가 충분하므로 전원 문제는 아닙니다.","next_steps":[],"caution":"고장입니다.","candidate_ids":[],"source_ids":["madeup#1"]}
        model=AsyncMock()
        model.name="test-model"
        model.explain_device.return_value=(answer,{"model":"test-model","input_tokens":10,"output_tokens":10,"total_tokens":20})
        self.server.app.state.deps.quality_llm=model
        result=self.inspect("sensor-02")
        self.assertEqual(model.explain_device.await_count,2)
        self.assertEqual(result["metadata"]["answer_source"],"rules_qa_fallback")
        self.assertFalse(result["metadata"]["qa"]["passed"])
        self.assertNotIn("전원 문제는 아닙니다",result["reply"])
        self.assertEqual(result["metadata"]["llm_usage"]["total_tokens"],40)

    def test_retrieval_failure_does_not_generate_unfounded_model_answer(self):
        model=AsyncMock()
        model.name="test-model"
        self.server.app.state.deps.quality_llm=model
        mcp=self.server.app.state.deps.mcp
        original=mcp.call_tool
        async def call_tool(name,args,**kwargs):
            if name=="search_iot_manuals":
                raise RuntimeError("simulated retrieval failure")
            return await original(name,args,**kwargs)
        with patch.object(mcp,"call_tool",side_effect=call_tool):
            result=self.inspect("sensor-02")
        model.explain_device.assert_not_awaited()
        self.assertEqual(result["metadata"]["answer_source"],"rules_no_evidence")
        self.assertIn("검색 근거가 부족",result["reply"])


    def test_bulk_reset_restores_every_device_and_preserves_history_and_request_ledger(self):
        offers = {id: self.inspect(id)["recovery"] for id in ("sensor-02", "sensor-05", "sensor-06")}
        payloads = {}
        for id, offer in offers.items():
            payloads[id] = {"device_id": id, "request_id": "bulk-"+id, "scenario_revision": offer["scenario_revision"], "expected_sequence": 0}
            self.assertEqual(self.client.post("/api/recover", json=payloads[id]).status_code, 200)
        before = self.client.get("/api/maintenance").json()["records"]
        response = self.client.post("/api/scenario/reset-all")
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["count"], 6)
        seed = IoTSimulator()
        self.assertEqual(set(result["device_ids"]), set(seed.seed))
        self.assertEqual(self.client.get("/api/maintenance").json()["records"], before)
        for id, offer in offers.items():
            stale = self.client.post("/api/recover", json={**payloads[id], "request_id": "stale-"+id})
            self.assertEqual(stale.status_code, 409)
            self.assertIn("상태가 바뀌", stale.json()["detail"])
        # 중복 요청 기록은 초기화하지 않는다. 이전 request_id는 재실행 없이 과거 결과를 반환한다.
        self.assertTrue(self.client.post("/api/recover", json=payloads["sensor-02"]).json()["recovery_verified"])
        for id in result["device_ids"]:
            report = self.inspect(id)
            records = self.client.get("/api/maintenance", params={"device_id": id}).json()["records"]
            observation = next(record for record in records if record["id"] == report["metadata"]["maintenance_id"])["evidence"]
            data = observation["data"]
            for key, value in seed.seed[id].items():
                self.assertEqual(data[key], value, (id, key))
            self.assertEqual(data["telemetry_sequence"], 0)
            self.assertEqual(data["recovery_attempts"], 0)
            self.assertEqual(observation["device_logs"]["scenario_revision"], data["scenario_revision"])
            if id in offers:
                self.assertNotEqual(data["scenario_revision"], offers[id]["scenario_revision"])
            if id == "sensor-06":
                self.assertIsNotNone(report["recovery"])
