"""IoT 그래프에서 실제로 사용하는 의존성."""
from dataclasses import dataclass
from typing import Any


@dataclass
class IoTDeps:
    quality_llm: Any
    mcp: Any
    session_store: Any
