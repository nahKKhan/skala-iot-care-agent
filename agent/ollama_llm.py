"""IoT 설명 전용 ollama 모델 어댑터. HTTP 요청과 검수 형식은 iot_llm에 둔다."""
from langsmith import traceable


class OllamaQualityLLM:
    def __init__(self, model: str):
        self.name = f"ollama:{model}"
        self.model = model

    @traceable(run_type="llm", name="ollama_quality.explain_device")
    async def explain_device(self, *, query, device_id, data, assessment, runbook,
                             documents=None, history=None, device_logs=None, cause_candidates=None, feedback=None):
        from .iot_llm import make_messages, request_explanation
        messages = make_messages(query, device_id, data, assessment, runbook,
                                 documents=documents, history=history, device_logs=device_logs,
                                 cause_candidates=cause_candidates, feedback=feedback)
        return await request_explanation(
            backend="ollama", model=self.model, messages=messages)
