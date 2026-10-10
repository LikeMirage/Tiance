from dataclasses import dataclass
from typing import Literal


OutputLimitAction = Literal["stop", "retry", "send_message"]
DEFAULT_OUTPUT_LIMIT_MESSAGE = (
    "上一轮生成达到单次输出上限，任务尚未完成。请根据当前会话中的已有内容和工具结果"
    "继续完成原任务，避免重复已完成的内容。未完整生成的工具调用没有执行，"
    "如仍需要，请重新生成完整调用。"
)
OUTPUT_LIMIT_MESSAGE_PREFIX = "【天策自动续接通知】\n"
OUTPUT_LIMIT_TOLERANCE = 0.05


def output_limit_settings_from_payload(payload: dict | None, current: object = None) -> dict:
    defaults = {
        "output_limit_action": "retry",
        "output_limit_save_partial": False,
        "output_limit_message": DEFAULT_OUTPUT_LIMIT_MESSAGE,
        "output_limit_max_recoveries": None,
    }
    if current is not None:
        defaults = {key: getattr(current, key) for key in defaults}
    if not isinstance(payload, dict):
        return defaults
    action = payload.get("output_limit_action")
    if isinstance(action, str) and action in {"stop", "retry", "send_message"}:
        defaults["output_limit_action"] = action
    keep = payload.get("output_limit_save_partial")
    if isinstance(keep, bool):
        defaults["output_limit_save_partial"] = keep
    message = payload.get("output_limit_message")
    if isinstance(message, str):
        defaults["output_limit_message"] = message
    if "output_limit_max_recoveries" in payload:
        maximum = payload["output_limit_max_recoveries"]
        if maximum is None or (type(maximum) is int and maximum >= 0):
            defaults["output_limit_max_recoveries"] = maximum
    return defaults


@dataclass(slots=True)
class OutputLimitRecoveryBudget:
    """Shared by all model rounds and automatic messages in one user task."""

    used: int = 0
    last_round_usage_recorded: bool = False

    def consume(self, maximum: int) -> bool:
        if self.used >= maximum:
            return False
        self.used += 1
        return True
