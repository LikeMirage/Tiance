"""Repair only hashes proving that a role used unchanged legacy settings."""

from copy import deepcopy
from hashlib import sha256
from json import dumps

from app.migrations.project_db.session_settings_v8 import _session_settings_from_payload


def _digest(payload: dict) -> str:
    return sha256(dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


def migrated_role_hash(payload: dict) -> str | None:
    stored = payload.get("settings")
    original = payload.get("role_configuration_hash")
    if not payload.get("role_project_id") or not original or not isinstance(stored, dict):
        return original
    removed = ("return_cancelled_messages", "return_user_before_cancelled")
    added = ("output_limit_action", "output_limit_save_partial", "output_limit_message", "output_limit_max_recoveries")
    if not (any(key in stored for key in removed) or any(key not in stored for key in added)):
        return original
    settings = _session_settings_from_payload(stored)
    if isinstance(settings.get("enabled_tool_names"), tuple):
        settings["enabled_tool_names"] = sorted(settings["enabled_tool_names"])
    current = {key: payload.get(key) if isinstance(payload.get(key), str) else None
               for key in ("provider_id", "model_id", "reasoning_mode")}
    if current["reasoning_mode"] not in {"default", "auto", "enabled", "off", "low", "medium", "high", "max"}:
        current["reasoning_mode"] = None
    current["settings"] = settings
    legacy = deepcopy(current)
    for key in added:
        if key not in stored:
            legacy["settings"].pop(key, None)
    if any(key in stored for key in removed):
        for key in removed:
            legacy["settings"][key] = stored.get(key) if isinstance(stored.get(key), bool) else True
    return _digest(current) if original == _digest(legacy) else original
