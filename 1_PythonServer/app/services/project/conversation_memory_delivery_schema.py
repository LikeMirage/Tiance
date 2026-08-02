from __future__ import annotations

from typing import Any


MEMORY_DELIVERY_SCHEMA_VERSION = 2
SUPPORTED_MEMORY_DELIVERY_SCHEMA_VERSIONS = {1, MEMORY_DELIVERY_SCHEMA_VERSION}
GLOBAL_MEMORY_SCOPE = "global_memory"
PROJECT_MEMORY_SCOPE = "project_memory"
MEMORY_SCOPES = (GLOBAL_MEMORY_SCOPE, PROJECT_MEMORY_SCOPE)


def normalize_memory_delivery_state(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") not in SUPPORTED_MEMORY_DELIVERY_SCHEMA_VERSIONS:
        raise ValueError("Unsupported conversation memory delivery schema version.")
    baseline_payload = payload.get("baseline")
    cursor_payload = payload.get("cursors")
    deliveries_payload = payload.get("deliveries")
    if not isinstance(baseline_payload, dict):
        raise ValueError("Conversation memory delivery baseline is invalid.")
    if not isinstance(cursor_payload, dict):
        raise ValueError("Conversation memory delivery cursors are invalid.")
    if not isinstance(deliveries_payload, list):
        raise ValueError("Conversation memory deliveries are invalid.")

    baseline: dict[str, dict[str, Any]] = {}
    cursors: dict[str, int] = {}
    for scope in MEMORY_SCOPES:
        scope_payload = baseline_payload.get(scope)
        if not isinstance(scope_payload, dict):
            raise ValueError(f"Conversation memory baseline '{scope}' is invalid.")
        baseline[scope] = {
            "event_count": non_negative_int(scope_payload.get("event_count")),
            "items": normalize_memory_items(scope_payload.get("items")),
        }
        cursors[scope] = non_negative_int(cursor_payload.get(scope))
        if cursors[scope] < baseline[scope]["event_count"]:
            raise ValueError("Conversation memory delivery cursor precedes its baseline.")

    deliveries: list[dict[str, Any]] = []
    for raw_delivery in deliveries_payload:
        if not isinstance(raw_delivery, dict):
            raise ValueError("Conversation memory delivery entry is invalid.")
        cursor_after_payload = raw_delivery.get("cursor_after")
        if not isinstance(cursor_after_payload, dict):
            raise ValueError("Conversation memory delivery cursor snapshot is invalid.")
        deliveries.append({
            "user_message_id": required_text(raw_delivery.get("user_message_id")),
            "created_at": text_value(raw_delivery.get("created_at")),
            GLOBAL_MEMORY_SCOPE: normalize_memory_changes(
                raw_delivery.get(GLOBAL_MEMORY_SCOPE)
            ),
            PROJECT_MEMORY_SCOPE: normalize_memory_changes(
                raw_delivery.get(PROJECT_MEMORY_SCOPE)
            ),
            "cursor_after": {
                scope: non_negative_int(cursor_after_payload.get(scope))
                for scope in MEMORY_SCOPES
            },
        })

    cache_context_payload = payload.get("cache_context")
    cache_context = cache_context_payload if isinstance(cache_context_payload, dict) else {}
    return {
        "schema_version": MEMORY_DELIVERY_SCHEMA_VERSION,
        "created_at": text_value(payload.get("created_at")),
        "updated_at": text_value(payload.get("updated_at")),
        "last_prepared_user_message_id": text_value(
            payload.get("last_prepared_user_message_id")
        ),
        "cache_context": {
            "provider_id": text_value(cache_context.get("provider_id")),
            "model_id": text_value(cache_context.get("model_id")),
            "last_request_at": (
                text_value(cache_context.get("last_request_at"))
                or text_value(payload.get("updated_at"))
            ),
        },
        "baseline": baseline,
        "cursors": cursors,
        "deliveries": deliveries,
    }


def normalize_memory_items(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("Conversation memory item list is invalid.")
    items: list[dict[str, Any]] = []
    for raw_item in value:
        item = normalize_memory_item(raw_item)
        if item is None:
            raise ValueError("Conversation memory item is invalid.")
        if not isinstance(raw_item, dict):
            raise ValueError("Conversation memory item is invalid.")
        items.append({"id": required_text(raw_item.get("id")), **item})
    return items


def normalize_memory_item(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    content = text_value(value.get("content"))
    if not content:
        return None
    return {
        "content": content,
        "keywords": normalize_keywords(value.get("keywords")),
    }


def normalize_memory_changes(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("Conversation memory change list is invalid.")
    changes: list[dict[str, Any]] = []
    for raw_change in value:
        if not isinstance(raw_change, dict):
            raise ValueError("Conversation memory change entry is invalid.")
        operation = required_text(raw_change.get("operation"))
        if operation not in {"add", "update", "delete"}:
            raise ValueError("Conversation memory change operation is invalid.")
        before = raw_change.get("before")
        after = raw_change.get("after")
        normalized_before = normalize_memory_item(before) if before is not None else None
        normalized_after = normalize_memory_item(after) if after is not None else None
        if operation == "add" and normalized_after is None:
            raise ValueError("Conversation memory add change is missing its new value.")
        if operation == "update" and (
            normalized_before is None or normalized_after is None
        ):
            raise ValueError("Conversation memory update change is incomplete.")
        if operation == "delete" and (
            normalized_before is None or normalized_after is not None
        ):
            raise ValueError("Conversation memory delete change is invalid.")
        changes.append({
            "event_index": non_negative_int(raw_change.get("event_index")),
            "operation": operation,
            "memory_id": required_text(raw_change.get("memory_id")),
            "before": normalized_before,
            "after": normalized_after,
            "reason": text_value(raw_change.get("reason")),
            "created_at": text_value(raw_change.get("created_at")),
        })
    return changes


def normalize_keywords(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    keywords: list[str] = []
    seen: set[str] = set()
    for item in value:
        keyword = text_value(item)
        if not keyword or keyword in seen:
            continue
        keywords.append(keyword)
        seen.add(keyword)
    return keywords


def text_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def required_text(value: object) -> str:
    text = text_value(value)
    if not text:
        raise ValueError("Conversation memory delivery text field is empty.")
    return text


def non_negative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Conversation memory delivery integer field is invalid.")
    return value
