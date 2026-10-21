"""실제 모델을 호출하지 않는 규칙 기반 시연 모드.

explain_device를 제공하지 않으면 IoT 그래프가 관측값과 검색 근거로 안내한다.
토큰 수나 비용을 생성하지 않는다.
"""


class RuleBasedLLM:
    def __init__(self, name="rules"):
        self.name = name
