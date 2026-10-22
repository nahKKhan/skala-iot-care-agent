"""실제 과금 없이 평가 실행기 선택·시도 기록·오류 보존·보고서를 검증한다."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

SPEC = importlib.util.spec_from_file_location("evaluation_runner", Path(__file__).resolve().parents[1]/"scripts/evaluate_iot.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class EvaluationConfigurationTests(unittest.TestCase):
    def test_cli_and_model_defaults_keep_backend_distinct(self):
        args = runner.build_parser().parse_args(["--backend","openai"])
        self.assertIsNone(args.model)
        with patch.dict(os.environ, {"OPENAI_QUALITY_MODEL":"configured-openai", "OLLAMA_QUALITY_MODEL":"configured-ollama"}):
            self.assertEqual(runner.configured_model(args.backend,args.model), "configured-openai")
            self.assertEqual(runner.configured_model("ollama"), "configured-ollama")
            self.assertEqual(runner.configured_model("openai","explicit-model"), "explicit-model")
            self.assertEqual(runner.configured_model("rules"), "none")

    def test_factory_does_not_silently_use_rules_for_unknown_backend(self):
        self.assertIsInstance(runner.build_evaluation_model("openai","test").model, runner.OpenAIQualityLLM)
        self.assertIsInstance(runner.build_evaluation_model("ollama","test").model, runner.OllamaQualityLLM)
        self.assertFalse(hasattr(runner.build_evaluation_model("rules","none"),"explain_device"))
        with self.assertRaises(ValueError):
            runner.build_evaluation_model("mistyped","test")

    def test_empty_or_partial_report_keeps_execution_status(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"report.json"
            report = {"created_at":"test", "backend":"openai", "model":"test",
                      "run_status":"stopped_on_access_error", "requested_case_count":12,
                      "not_run_case_ids":["Q02"], "cases":[]}
            runner.write_report(report,path)
            self.assertEqual(json.loads(path.read_text())["run_status"], "stopped_on_access_error")
            self.assertIn("stopped_on_access_error",path.with_suffix(".md").read_text())
            self.assertIn("미실행 사례: Q02",path.with_suffix(".md").read_text())


class GenerationRecordingTests(unittest.IsolatedAsyncioTestCase):
    async def test_records_each_attempt_and_does_not_capture_adapter_secrets(self):
        output = {"explanation":"관측 사실"}
        usage = {"model":"test","total_tokens":7}
        inner = SimpleNamespace(name="test",api_key="not-to-be-recorded",
                                explain_device=AsyncMock(return_value=(output,usage)))
        model = runner.RecordingModel(inner)
        data = {"documents":[{"source_url":"https://kb.shelly.cloud/","source_id":"doc#1"}]}
        self.assertEqual(await model.explain_device(**data),(output,usage))
        await model.explain_device(**data,feedback="재작성")
        data["documents"][0]["source_id"] = "changed"
        output["explanation"] = "changed"
        self.assertEqual(len(model.calls),2)
        self.assertEqual(model.calls[0]["input"]["documents"][0]["source_id"],"doc#1")
        self.assertEqual(model.calls[0]["output"]["explanation"],"관측 사실")
        self.assertEqual(model.calls[1]["input"]["feedback"],"재작성")
        self.assertNotIn("not-to-be-recorded",json.dumps(model.calls))
        self.assertGreaterEqual(model.calls[0]["elapsed_seconds"],0)

    async def test_failed_generation_is_recorded_and_reraised_without_automatic_retry(self):
        inner = SimpleNamespace(name="test", explain_device=AsyncMock(
            side_effect=runner.ExplanationError("모델 API 사용 한도 또는 요청 제한을 확인해 주세요.")))
        model = runner.RecordingModel(inner)
        with self.assertRaises(runner.ExplanationError):
            await model.explain_device(query="실제 질문")
        self.assertEqual(inner.explain_device.await_count,1)
        self.assertIsNone(model.calls[0]["output"])
        self.assertIn("사용 한도",model.calls[0]["error"])
