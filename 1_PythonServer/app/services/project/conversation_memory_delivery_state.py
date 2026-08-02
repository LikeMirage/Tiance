from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.project.conversation_memory_delivery_schema import (
    GLOBAL_MEMORY_SCOPE,
    MEMORY_DELIVERY_SCHEMA_VERSION,
    MEMORY_SCOPES,
    PROJECT_MEMORY_SCOPE,
    normalize_keywords,
    normalize_memory_delivery_state,
    normalize_memory_item,
    normalize_memory_items,
    text_value,
)


def prepare_memory_delivery_state(
    existing: dict[str, Any] | None,
    *,
    user_message_id: str,
    created_at: str,
    global_events: list[dict[str, Any]],
    project_events: list[dict[str, Any]],
    global_enabled: bool,
    project_enabled: bool,
    cache_provider_id: str = "",
    cache_model_id: str = "",
    cache_retention_seconds: int = 5 * 60,
) -> dict[str, Any]:
    events_by_scope = {
        GLOBAL_MEMORY_SCOPE: global_events,
        PROJECT_MEMORY_SCOPE: project_events,
    }
    enabled_by_scope = {
        GLOBAL_MEMORY_SCOPE: global_enabled,
        PROJECT_MEMORY_SCOPE: project_enabled,
    }
    if existing is None:
        return _initial_state(
            user_message_id=user_message_id,
            created_at=created_at,
            events_by_scope=events_by_scope,
            cache_provider_id=cache_provider_id,
            cache_model_id=cache_model_id,
        )

    state = normalize_memory_delivery_state(existing)
    if state["last_prepared_user_message_id"] == user_message_id:
        return state

    baseline = state["baseline"]
    cursors = state["cursors"]
    deliveries = state["deliveries"]
    cache_context = state["cache_context"]
    cache_expired = _cache_has_expired(
        cache_context,
        current_at=created_at,
        provider_id=cache_provider_id,
        model_id=cache_model_id,
        retention_seconds=cache_retention_seconds,
    )
    if cache_expired:
        _fold_all_deliveries_into_baseline(baseline, deliveries)
    delivery = {
        "user_message_id": user_message_id,
        "created_at": created_at,
        GLOBAL_MEMORY_SCOPE: [],
        PROJECT_MEMORY_SCOPE: [],
        "cursor_after": {},
    }

    for scope in MEMORY_SCOPES:
        events = events_by_scope[scope]
        if cursors[scope] > len(events):
            raise ValueError("Conversation memory event log is shorter than its delivery cursor.")
        current_items, changes = memory_snapshot_and_changes(
            events,
            start_index=cursors[scope],
        )
        if enabled_by_scope[scope]:
            delivery[scope] = changes
        else:
            baseline[scope] = {
                "event_count": len(events),
                "items": current_items,
            }
            _remove_scope_from_deliveries(deliveries, scope)
        cursors[scope] = len(events)
        delivery["cursor_after"][scope] = len(events)

    if delivery[GLOBAL_MEMORY_SCOPE] or delivery[PROJECT_MEMORY_SCOPE]:
        if cache_expired:
            _apply_delivery_to_baseline(baseline, delivery)
        deliveries.append(delivery)

    return {
        "schema_version": MEMORY_DELIVERY_SCHEMA_VERSION,
        "created_at": state["created_at"],
        "updated_at": created_at,
        "last_prepared_user_message_id": user_message_id,
        "cache_context": {
            "provider_id": cache_provider_id or cache_context["provider_id"],
            "model_id": cache_model_id or cache_context["model_id"],
            "last_request_at": created_at,
        },
        "baseline": baseline,
        "cursors": cursors,
        "deliveries": deliveries,
    }


def memory_snapshot_and_changes(
    events: list[dict[str, Any]],
    *,
    start_index: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    current: dict[str, dict[str, Any]] = {}
    changes: list[dict[str, Any]] = []
    safe_start = max(0, start_index)
    for index, event in enumerate(events):
        change = _apply_event(current, event, event_index=index + 1)
        if change is not None and index >= safe_start:
            changes.append(change)
    return _current_items(current), changes


def apply_memory_changes(
    items: list[dict[str, Any]],
    changes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current = {
        item["id"]: {
            "content": item["content"],
            "keywords": list(item["keywords"]),
        }
        for item in normalize_memory_items(items)
    }
    for change in changes:
        memory_id = text_value(change.get("memory_id"))
        after = change.get("after")
        if not memory_id:
            continue
        if after is None:
            current.pop(memory_id, None)
            continue
        item = normalize_memory_item(after)
        if item is not None:
            current[memory_id] = {
                "content": item["content"],
                "keywords": item["keywords"],
            }
    return _current_items(current)


def fold_missing_leading_memory_deliveries(
    existing: dict[str, Any],
    *,
    visible_message_ids: set[str],
    updated_at: str,
) -> dict[str, Any]:
    state = normalize_memory_delivery_state(existing)
    baseline = state["baseline"]
    deliveries = state["deliveries"]
    folded_count = 0

    for delivery in deliveries:
        if delivery["user_message_id"] in visible_message_ids:
            break
        for scope in MEMORY_SCOPES:
            baseline[scope] = {
                "event_count": max(
                    baseline[scope]["event_count"],
                    delivery["cursor_after"][scope],
                ),
                "items": apply_memory_changes(
                    baseline[scope]["items"],
                    delivery[scope],
                ),
            }
        folded_count += 1

    if folded_count == 0:
        return state
    return {
        **state,
        "updated_at": updated_at,
        "baseline": baseline,
        "deliveries": deliveries[folded_count:],
    }


def _initial_state(
    *,
    user_message_id: str,
    created_at: str,
    events_by_scope: dict[str, list[dict[str, Any]]],
    cache_provider_id: str,
    cache_model_id: str,
) -> dict[str, Any]:
    baseline: dict[str, dict[str, Any]] = {}
    cursors: dict[str, int] = {}
    for scope in MEMORY_SCOPES:
        events = events_by_scope[scope]
        items, _changes = memory_snapshot_and_changes(events, start_index=len(events))
        baseline[scope] = {
            "event_count": len(events),
            "items": items,
        }
        cursors[scope] = len(events)
    return {
        "schema_version": MEMORY_DELIVERY_SCHEMA_VERSION,
        "created_at": created_at,
        "updated_at": created_at,
        "last_prepared_user_message_id": user_message_id,
        "cache_context": {
            "provider_id": cache_provider_id,
            "model_id": cache_model_id,
            "last_request_at": created_at,
        },
        "baseline": baseline,
        "cursors": cursors,
        "deliveries": [],
    }


def _cache_has_expired(
    cache_context: dict[str, str],
    *,
    current_at: str,
    provider_id: str,
    model_id: str,
    retention_seconds: int,
) -> bool:
    previous_provider_id = cache_context["provider_id"]
    previous_model_id = cache_context["model_id"]
    if provider_id and previous_provider_id and provider_id != previous_provider_id:
        return True
    if model_id and previous_model_id and model_id != previous_model_id:
        return True
    try:
        previous_at = datetime.fromisoformat(
            cache_context["last_request_at"].replace("Z", "+00:00")
        )
        current = datetime.fromisoformat(current_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return (current - previous_at).total_seconds() >= max(1, retention_seconds)


def _fold_all_deliveries_into_baseline(
    baseline: dict[str, dict[str, Any]],
    deliveries: list[dict[str, Any]],
) -> None:
    for delivery in deliveries:
        _apply_delivery_to_baseline(baseline, delivery)
    deliveries.clear()


def _apply_delivery_to_baseline(
    baseline: dict[str, dict[str, Any]],
    delivery: dict[str, Any],
) -> None:
    for scope in MEMORY_SCOPES:
        baseline[scope] = {
            "event_count": max(
                baseline[scope]["event_count"],
                delivery["cursor_after"][scope],
            ),
            "items": apply_memory_changes(
                baseline[scope]["items"],
                delivery[scope],
            ),
        }


def _apply_event(
    current: dict[str, dict[str, Any]],
    event: dict[str, Any],
    *,
    event_index: int,
) -> dict[str, Any] | None:
    operation = text_value(event.get("operation"))
    memory_id = (
        text_value(event.get("memory_id"))
        if operation == "add"
        else text_value(event.get("target_memory_id"))
    )
    if not memory_id:
        return None
    before = _copy_memory_payload(current.get(memory_id))
    if operation == "add":
        content = text_value(event.get("content"))
        if not content:
            return None
        current[memory_id] = {
            "content": content,
            "keywords": normalize_keywords(event.get("keywords")),
        }
    elif operation == "update":
        content = text_value(event.get("content"))
        if before is None or not content:
            return None
        current[memory_id] = {
            "content": content,
            "keywords": normalize_keywords(event.get("keywords")),
        }
    elif operation == "delete":
        if before is None:
            return None
        current.pop(memory_id, None)
    else:
        return None
    return {
        "event_index": event_index,
        "operation": operation,
        "memory_id": memory_id,
        "before": before,
        "after": _copy_memory_payload(current.get(memory_id)),
        "reason": text_value(event.get("reason")),
        "created_at": text_value(event.get("created_at")),
    }


def _remove_scope_from_deliveries(
    deliveries: list[dict[str, Any]],
    scope: str,
) -> None:
    for delivery in deliveries:
        delivery[scope] = []
    deliveries[:] = [
        delivery
        for delivery in deliveries
        if delivery[GLOBAL_MEMORY_SCOPE] or delivery[PROJECT_MEMORY_SCOPE]
    ]


def _current_items(current: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": memory_id,
            "content": payload["content"],
            "keywords": list(payload["keywords"]),
        }
        for memory_id, payload in current.items()
    ]


def _copy_memory_payload(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "content": value["content"],
        "keywords": list(value["keywords"]),
    }
