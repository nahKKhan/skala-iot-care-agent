"""IoT 설명 전용 openai 모델 어댑터. HTTP 요청과 검수 형식은 iot_llm에 둔다."""
import os
from langsmith import traceable


class OpenAIQualityLLM:
    def __init__(self, model: str):
        self.name = f"openai:{model}"
        self.model = model
        self.api_key = os.environ.get("OPENAI_API_KEY", "")

    @traceable(run_type="llm", name="openai_quality.explain_device")
    async def explain_device(self, *, query, device_id, data, assessment, runbook,
                             documents=None, history=None, device_logs=None, cause_candidates=None, feedback=None):
        from .iot_llm import make_messages, request_explanation
        messages = make_messages(query, device_id, data, assessment, runbook,
                                 documents=documents, history=history, device_logs=device_logs,
                                 cause_candidates=cause_candidates, feedback=feedback)
        return await request_explanation(
            backend="openai", model=self.model, messages=messages, api_key=self.api_key)
