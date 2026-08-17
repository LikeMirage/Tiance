from __future__ import annotations

from app.domain.project.project_conversation import ProjectConversationSessionSettings


def _session_settings_from_payload(payload: object) -> ProjectConversationSessionSettings:
    if not isinstance(payload, dict):
        return ProjectConversationSessionSettings()
    return ProjectConversationSessionSettings(
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
        return_cancelled_messages=_optional_bool(
            payload.get("return_cancelled_messages"),
            default_value=True,
        ),
        return_user_before_cancelled=_optional_bool(
            payload.get("return_user_before_cancelled"),
            default_value=True,
        ),
        streaming_enabled=_optional_bool(payload.get("streaming_enabled"), default_value=True),
        auto_collapse_assistant_process=_optional_bool(
            payload.get("auto_collapse_assistant_process"),
            default_value=True,
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
    )


def _merge_session_settings(
    current: ProjectConversationSessionSettings,
    payload: dict | None,
) -> ProjectConversationSessionSettings:
    if not isinstance(payload, dict):
        return current
    return ProjectConversationSessionSettings(
        global_memory_enabled=_optional_bool(
            payload.get("global_memory_enabled"),
            default_value=current.global_memory_enabled,
        ),
        global_memory_extraction_enabled=_optional_bool(
            payload.get("global_memory_extraction_enabled"),
            default_value=current.global_memory_extraction_enabled,
        ),
        memory_context_token_trigger_threshold=(
            _optional_int_in_range(
                payload.get("memory_context_token_trigger_threshold"),
                default_value=current.memory_context_token_trigger_threshold,
                minimum=1,
            )
            if "memory_context_token_trigger_threshold" in payload
            else current.memory_context_token_trigger_threshold
        ),
        memory_compression_enabled=_optional_bool(
            payload.get("memory_compression_enabled"),
            default_value=current.memory_compression_enabled,
        ),
        memory_raw_context_token_reserve=(
            _optional_int_in_range(
                payload.get("memory_raw_context_token_reserve"),
                default_value=current.memory_raw_context_token_reserve,
                minimum=0,
            )
            if "memory_raw_context_token_reserve" in payload
            else current.memory_raw_context_token_reserve
        ),
        project_memory_enabled=_optional_bool(
            payload.get("project_memory_enabled"),
            default_value=current.project_memory_enabled,
        ),
        project_memory_extraction_enabled=_optional_bool(
            payload.get("project_memory_extraction_enabled"),
            default_value=current.project_memory_extraction_enabled,
        ),
        return_cancelled_messages=_optional_bool(
            payload.get("return_cancelled_messages"),
            default_value=current.return_cancelled_messages,
        ),
        return_user_before_cancelled=_optional_bool(
            payload.get("return_user_before_cancelled"),
            default_value=current.return_user_before_cancelled,
        ),
        streaming_enabled=_optional_bool(
            payload.get("streaming_enabled"),
            default_value=current.streaming_enabled,
        ),
        auto_collapse_assistant_process=_optional_bool(
            payload.get("auto_collapse_assistant_process"),
            default_value=current.auto_collapse_assistant_process,
        ),
        inject_message_timestamps=_optional_bool(
            payload.get("inject_message_timestamps"),
            default_value=current.inject_message_timestamps,
        ),
        system_prompt=_normalize_system_prompt(
            payload.get("system_prompt"),
            default_value=current.system_prompt,
        ),
        max_output_tokens=(
            _optional_int_in_range(
                payload.get("max_output_tokens"),
                default_value=current.max_output_tokens,
                minimum=1,
            )
            if "max_output_tokens" in payload
            else current.max_output_tokens
        ),
        temperature=(
            _optional_float(payload.get("temperature"), minimum=0)
            if "temperature" in payload
            else current.temperature
        ),
        top_p=(
            _optional_float(payload.get("top_p"), minimum=0)
            if "top_p" in payload
            else current.top_p
        ),
        tools_enabled=_optional_bool(
            payload.get("tools_enabled"),
            default_value=current.tools_enabled,
        ),
        enabled_tool_names=(
            _optional_tool_names(
                payload.get("enabled_tool_names"),
                default_value=current.enabled_tool_names,
            )
            if "enabled_tool_names" in payload
            else current.enabled_tool_names
        ),
        max_tool_calls=(
            _optional_int_in_range(
                payload.get("max_tool_calls"),
                default_value=current.max_tool_calls,
                minimum=1,
            )
            if "max_tool_calls" in payload
            else current.max_tool_calls
        ),
    )


def _session_settings_to_payload(settings: ProjectConversationSessionSettings) -> dict:
    payload = {
        "global_memory_enabled": settings.global_memory_enabled,
        "global_memory_extraction_enabled": settings.global_memory_extraction_enabled,
        "memory_compression_enabled": settings.memory_compression_enabled,
        "memory_context_token_trigger_threshold": (
            settings.memory_context_token_trigger_threshold
        ),
        "memory_raw_context_token_reserve": settings.memory_raw_context_token_reserve,
        "project_memory_enabled": settings.project_memory_enabled,
        "project_memory_extraction_enabled": settings.project_memory_extraction_enabled,
        "return_cancelled_messages": settings.return_cancelled_messages,
        "return_user_before_cancelled": settings.return_user_before_cancelled,
        "streaming_enabled": settings.streaming_enabled,
        "auto_collapse_assistant_process": settings.auto_collapse_assistant_process,
        "inject_message_timestamps": settings.inject_message_timestamps,
        "system_prompt": settings.system_prompt,
        "max_output_tokens": settings.max_output_tokens,
        "temperature": settings.temperature,
        "top_p": settings.top_p,
        "tools_enabled": settings.tools_enabled,
        "enabled_tool_names": list(settings.enabled_tool_names)
        if settings.enabled_tool_names is not None
        else None,
        "max_tool_calls": settings.max_tool_calls,
    }
    return payload


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
