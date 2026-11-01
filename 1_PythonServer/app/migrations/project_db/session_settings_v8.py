"""Frozen v8 settings normalization for hash migration; never used by live reads."""

DEFAULT_OUTPUT_LIMIT_MESSAGE = (
    "上一轮生成达到单次输出上限，任务尚未完成。请根据当前会话中的已有内容和工具结果"
    "继续完成原任务，避免重复已完成的内容。未完整生成的工具调用没有执行，"
    "如仍需要，请重新生成完整调用。"
)

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

def _session_settings_from_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        payload = {}
    return dict(
        **output_limit_settings_from_payload(payload),
        global_memory_enabled=_optional_bool(payload.get("global_memory_enabled"), default_value=True),
        global_memory_extraction_enabled=_optional_bool(
            payload.get("global_memory_extraction_enabled"),
            default_value=True,
        ),
        memory_compression_enabled=_optional_bool(payload.get("memory_compression_enabled"), default_value=True),
        memory_context_token_trigger_threshold=_optional_int_in_range(
            payload.get("memory_context_token_trigger_threshold"),
            default_value=250000,
            minimum=1,
        ),
        memory_raw_context_token_reserve=_optional_int_in_range(
            payload.get("memory_raw_context_token_reserve"),
            default_value=30000,
            minimum=0,
        ),
        project_memory_enabled=_optional_bool(payload.get("project_memory_enabled"), default_value=True),
        project_memory_extraction_enabled=_optional_bool(
            payload.get("project_memory_extraction_enabled"),
            default_value=True,
        ),
        streaming_enabled=_optional_bool(payload.get("streaming_enabled"), default_value=True),
        auto_collapse_assistant_process=_optional_bool(
            payload.get("auto_collapse_assistant_process"),
            default_value=True,
        ),
        malformed_tool_call_recovery_enabled=_optional_bool(
            payload.get("malformed_tool_call_recovery_enabled"),
            default_value=True,
        ),
        upstream_retry_count=_optional_int_in_range(
            payload.get("upstream_retry_count"),
            default_value=1,
            minimum=0,
        ),
        inject_message_timestamps=_optional_bool(
            payload.get("inject_message_timestamps"),
            default_value=True,
        ),
        system_prompt=_normalize_system_prompt(payload.get("system_prompt")),
        max_output_tokens=_optional_int_in_range(
            payload.get("max_output_tokens"),
            default_value=32768,
            minimum=1,
        ),
        temperature=_optional_float(payload.get("temperature"), minimum=0),
        top_p=_optional_float(payload.get("top_p"), minimum=0),
        tools_enabled=_optional_bool(
            payload.get("tools_enabled"),
            default_value=True,
        ),
        enabled_tool_names=_optional_tool_names(
            payload.get("enabled_tool_names"),
            default_value=None,
        ),
        max_tool_calls=_optional_int_in_range(
            payload.get("max_tool_calls"),
            default_value=99999,
            minimum=1,
        ),
        tool_approval_mode=_optional_tool_approval_mode(
            payload.get("tool_approval_mode"),
            default_value="auto_allow_ask",
        ),
    )


def _optional_bool(value: object, *, default_value: bool) -> bool:
    return value if isinstance(value, bool) else default_value


def _optional_int_in_range(
    value: object,
    *,
    default_value: int,
    minimum: int,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool):
        return default_value
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default_value
    min_bounded = max(minimum, parsed)
    return min_bounded if maximum is None else min(maximum, min_bounded)


def _optional_float(
    value: object,
    *,
    minimum: float,
    maximum: float | None = None,
    default_value: float | None = None,
) -> float | None:
    if value is None:
        return default_value
    if isinstance(value, bool):
        return default_value
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default_value
    if parsed < minimum:
        return default_value
    if maximum is not None and parsed > maximum:
        return default_value
    return parsed


def _normalize_system_prompt(value: object, *, default_value: str = "") -> str:
    if not isinstance(value, str):
        return default_value
    return value


def _optional_tool_names(
    value: object,
    *,
    default_value: tuple[str, ...] | None,
) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        return default_value

    names: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if not name or name in seen:
            continue
        names.append(name)
        seen.add(name)
    return tuple(names)


def _optional_tool_approval_mode(
    value: object,
    *,
    default_value: str,
) -> str:
    if value in {"follow_tool_policy", "auto_allow_ask"}:
        return value
    return default_value
