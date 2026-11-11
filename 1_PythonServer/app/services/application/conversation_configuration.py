"""Resolve a role base and explicit overrides before a single session mutation."""
from app.services.application.role_configuration import get_role_configuration_application_service


def resolve_configuration(patch: dict) -> dict:
    patch = dict(patch)
    role_id = patch.get("role_project_id")
    if not role_id:
        return patch
    seed = get_role_configuration_application_service().build_new_session_seed(role_id)
    resolved = {"provider_id": seed.provider_id, "model_id": seed.model_id,
                "reasoning_mode": seed.reasoning_mode, "settings": dict(seed.settings),
                "role_project_id": seed.role_project_id}
    resolved.update({key: value for key, value in patch.items() if key != "settings"})
    resolved["settings"].update(patch.get("settings") or {})
    if any(resolved[key] != getattr(seed, key)
           for key in ("provider_id", "model_id", "reasoning_mode", "settings")):
        # Match the ordinary UI: once overridden this is a custom session config,
        # not an unmodified copy of a role. Never mark overrides as the role hash.
        resolved["role_project_id"] = None
    return resolved
