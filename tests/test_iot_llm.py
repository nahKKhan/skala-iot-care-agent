"""실제 과금 없이 IoT 모델 호출 계약과 그래프·SSE 연결을 검증한다."""
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from agent.iot_llm import ExplanationError, make_messages, request_explanation
from agent.device_rules import allowed_guidance, CAUTION
from agent.openai_llm import OpenAIQualityLLM
from agent.ollama_llm import OllamaQualityLLM

ANSWER = {"explanation": "관측 상태에 맞춰 추가 점검이 필요합니다.",
          "next_steps": ["상태를 다시 조회해 지연이 계속되는지 확인하세요."],
          "caution": "현재 정보만으로 고장 원인을 확정할 수 없습니다.",
          "candidate_ids": [], "source_ids": ["telemetry_delayed#1"]}
USAGE = {"model": "openai:test-model", "input_tokens": 100,
         "output_tokens": 50, "total_tokens": 150}


def completion(content=None, **kwargs):
    choice = {"finish_reason": "stop", "message": {"content": json.dumps(ANSWER if content is None else content, ensure_ascii=False)}}
    choice.update(kwargs)
    return {"choices": [choice], "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}


class ExplanationTransportTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, body=None, *, status=200, error=None, backend="openai"):
        upstream = AsyncMock()
        upstream.post.return_value = httpx.Response(status, json=body, request=httpx.Request("POST", "https://example.invalid"))
        upstream.post.side_effect = error
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=upstream)
        context.__aexit__ = AsyncMock(return_value=False)
        with patch("agent.iot_llm.httpx.AsyncClient", return_value=context):
            result = await request_explanation(backend=backend, model="test-model", messages=[{"role": "user", "content": "test"}], api_key="test-secret")
        self.assertEqual(upstream.post.await_count, 1)
        return result, upstream.post.await_args

    async def test_openai_uses_schema_and_real_token_usage(self):
        (answer, usage), call = await self.request(completion())
        self.assertEqual(answer, ANSWER)
        self.assertEqual(usage, USAGE)
        self.assertNotIn("usd", usage)
        self.assertNotIn("think", call.kwargs["json"])
        self.assertEqual(call.args[0], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(call.kwargs["json"]["response_format"]["json_schema"]["strict"], True)

    async def test_json_schema_limits_ids_to_retrieved_sources_and_candidates(self):
        context=MagicMock()
        upstream=AsyncMock()
        upstream.post.return_value=httpx.Response(200,json={"done":True,"message":{"content":json.dumps(ANSWER)}},request=httpx.Request("POST","http://localhost"))
        context.__aenter__=AsyncMock(return_value=upstream)
        context.__aexit__=AsyncMock(return_value=False)
        evidence={"documents":[{"source_id":"telemetry_delayed#1"}],"candidate_catalog":[{"id":"collection_stall"}]}
        with patch("agent.iot_llm.httpx.AsyncClient",return_value=context):
            await request_explanation(backend="ollama",model="test",messages=[{"content":json.dumps(evidence)}])
        properties=upstream.post.await_args.kwargs["json"]["format"]["properties"]
        self.assertEqual(properties["source_ids"]["items"]["enum"],["telemetry_delayed#1"])
        self.assertEqual(properties["candidate_ids"]["items"]["enum"],["collection_stall"])

    async def test_ollama_uses_local_structured_output(self):
        (answer, usage), call = await self.request({"done": True, "message": {"content": json.dumps(ANSWER)}, "prompt_eval_count": 10, "eval_count": 20}, backend="ollama")
        self.assertEqual(answer, ANSWER)
        self.assertEqual(usage["total_tokens"], 30)
        self.assertTrue(call.args[0].startswith("http://127.0.0.1:11434/"))
        self.assertNotIn("Authorization", call.kwargs["headers"])
        self.assertIs(call.kwargs["json"]["think"], False)
        self.assertEqual(call.kwargs["json"]["options"]["num_predict"], 640)

    async def test_rejects_invalid_refused_and_truncated_results(self):
        cases = [completion({"explanation": "불완전"}), completion(finish_reason="length"),
                 completion(message={"refusal": "refused", "content": None}), {},
                 completion({**ANSWER, "execute": "restart_collection"}),
                 completion({**ANSWER, "explanation": "  "})]
        for body in cases:
            with self.subTest(body=body), self.assertRaises(ExplanationError):
                await self.request(body)

    async def test_errors_are_actionable_and_hide_secrets(self):
        for status in (401, 403, 404, 429, 500):
            with self.subTest(status=status), self.assertRaises(ExplanationError) as caught:
                await self.request({"error": "test-secret"}, status=status)
            self.assertNotIn("test-secret", str(caught.exception))
        for error in (httpx.ReadTimeout("test-secret"), httpx.ConnectError("test-secret")):
            with self.assertRaises(ExplanationError) as caught:
                await self.request(error=error)
            self.assertNotIn("test-secret", str(caught.exception))

    async def test_missing_key_does_not_send_request(self):
        with patch("agent.iot_llm.httpx.AsyncClient") as client:
            with self.assertRaisesRegex(ExplanationError, "OPENAI_API_KEY"):
                await request_explanation(backend="openai", model="test", messages=[], api_key="")
            client.assert_not_called()

    async def test_both_adapters_forward_iot_evidence(self):
        evidence = {"query": "sensor-02 왜 늦어?", "device_id": "sensor-02",
                    "data": {"telemetry_age_seconds": 600},
                    "assessment": {"issues": ["telemetry_delayed"]}, "runbook": "점검 매뉴얼"}
        for model in (OpenAIQualityLLM("test"), OllamaQualityLLM("test")):
            with patch("agent.iot_llm.request_explanation", new=AsyncMock(return_value=(ANSWER, USAGE))) as request:
                await model.explain_device(**evidence)
                sent = json.loads(request.await_args.kwargs["messages"][1]["content"])
                self.assertEqual(sent["device"], evidence["data"])
                self.assertEqual(sent["assessment"], evidence["assessment"])
                self.assertEqual(sent["manual"], "점검 매뉴얼")
                self.assertIs(sent["command_executed"], False)


class LLMChatIntegrationTests(unittest.TestCase):
    def setUp(self):
        import server
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"LLM_BACKEND": "openai", "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false"}))
        folder = self.stack.enter_context(tempfile.TemporaryDirectory())
        original_store = server.SqliteSessionStore
        self.stack.enter_context(patch.object(server, "SqliteSessionStore", lambda: original_store(Path(folder) / "sessions.db")))
        async def explain(**kwargs):
            candidates = kwargs.get("cause_candidates", [])[:2]
            answer = {**ANSWER, "candidate_ids": [c["id"] for c in candidates],
                      "next_steps": allowed_guidance(kwargs["data"], kwargs["assessment"], candidates)[:2], "caution": CAUTION,
                      "source_ids": [d["source_id"] for d in kwargs.get("documents", [])]}
            return answer, USAGE
        self.explain = self.stack.enter_context(patch.object(OpenAIQualityLLM, "explain_device", new=AsyncMock(side_effect=explain)))
        self.client = self.stack.enter_context(TestClient(server.app))

    def test_chat_passes_facts_manual_and_never_executes_recovery(self):
        result = self.client.post("/chat", json={"message": "sensor-02 재시작해줘"}).json()
        self.assertEqual(result["metadata"]["answer_source"], "llm")
        self.assertEqual(result["metadata"]["llm_usage"], USAGE)
        self.assertIsNone(result["metadata"]["cost_usd"])
        self.assertEqual(result["recovery"]["device_id"], "sensor-02")
        args = self.explain.await_args.kwargs
        self.assertEqual(args["data"]["telemetry_age_seconds"], 600)
        self.assertEqual(args["assessment"]["issues"], ["telemetry_delayed"])
        self.assertTrue(args["documents"])
        self.assertIn("telemetry_delayed", args["runbook"])
        self.assertIn(ANSWER["explanation"], result["reply"])
        # 채팅은 재시작하지 않았으므로 다음 조회에서도 수신 번호가 동일하다.
        self.client.post("/chat", json={"message": "sensor-02 점검"})
        self.assertEqual(self.explain.await_args.kwargs["data"]["telemetry_sequence"], 0)

    def test_healthy_and_offline_keep_code_assessment(self):
        for device_id, issues in (("sensor-01", []), ("sensor-03", ["low_battery", "offline"])):
            result = self.client.post("/chat", json={"message": device_id + " 점검"}).json()
            self.assertIsNone(result["recovery"])
            self.assertEqual(self.explain.await_args.kwargs["assessment"]["issues"], issues)
            self.assertTrue(self.explain.await_args.kwargs["documents"])

    def test_invalid_target_skips_llm(self):
        for message in ("센서 점검", "sensor-99 점검", "sensor-01 sensor-02"):
            self.client.post("/chat", json={"message": message})
        self.explain.assert_not_awaited()

    def test_model_failure_keeps_facts_and_recovery_offer(self):
        self.explain.side_effect = ExplanationError("모델 서버에 연결하지 못했습니다.")
        result = self.client.post("/chat", json={"message": "sensor-02 점검"}).json()
        self.assertEqual(result["metadata"]["answer_source"], "rules_fallback")
        self.assertIsNone(result["metadata"]["llm_usage"])
        self.assertIn("600초", result["reply"])
        self.assertIn("LLM 설명을 생성하지 못해", result["reply"])
        self.assertIsNotNone(result["recovery"])

    def test_sse_delivers_model_answer_metadata_and_offer(self):
        response = self.client.get("/chat/stream", params={"message": "sensor-02 점검"})
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ") and line != "data: [DONE]"]
        self.assertTrue(any(e["type"] == "DeviceExplanationStarted" for e in events))
        final = next(e for e in events if e["type"] == "FinalAnswer")
        self.assertEqual(final["metadata"]["answer_source"], "llm")
        self.assertEqual(final["recovery"]["device_id"], "sensor-02")
        self.assertIn(ANSWER["explanation"], final["reply"])
