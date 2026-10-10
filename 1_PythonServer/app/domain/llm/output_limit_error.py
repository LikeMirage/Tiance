from app.core.errors import UpstreamProviderError
from app.domain.llm.chat import ChatCompletionResult


class OutputLimitError(UpstreamProviderError):
    def __init__(self, result: ChatCompletionResult) -> None:
        super().__init__(
            "上游生成达到最大输出长度，回复未完成。",
            code="upstream_output_limit",
        )
        self.result = result
