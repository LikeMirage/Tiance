"""Keep source-log positions separate from a conversation's delivery history."""
from __future__ import annotations

from hashlib import sha256
from json import dumps
from typing import Any


def memory_source_checkpoints(
    events: list[dict[str, Any]], prefix_count: int,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    # Hash canonical records, not paths/mtimes: a copied log is still the same
    # source, while a replacement of equal or greater length is not a continuation.
    digest = sha256()
    prefix = {"event_count": 0, "sha256": digest.hexdigest()} if prefix_count == 0 else None
    for count, event in enumerate(events, start=1):
        record = dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest.update(record.encode("utf-8"))
        digest.update(b"\n")
        if count == prefix_count:
            prefix = {"event_count": count, "sha256": digest.hexdigest()}
    return prefix, {"event_count": len(events), "sha256": digest.hexdigest()}


def memory_items_equal(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
    return _item_map(left) == _item_map(right)


def reconcile_memory_changes(
    existing_items: list[dict[str, Any]], changes: list[dict[str, Any]],
    *, skip_unchanged: bool = False,
) -> list[dict[str, Any]]:
    """Describe changes against what this conversation actually already knows."""
    current = _item_map(existing_items)
    reconciled = []
    for change in changes:
        memory_id = change["memory_id"]
        before = current.get(memory_id)
        after = change["after"]
        if (before is None and after is None) or (skip_unchanged and before == after):
            continue
        reconciled.append({
            **change,
            "operation": "delete" if after is None else "add" if before is None else "update",
            "before": before,
            "after": after,
        })
        if after is None:
            current.pop(memory_id, None)
        else:
            current[memory_id] = after
    return reconciled


def reconnect_memory_source(
    existing_items: list[dict[str, Any]], current_items: list[dict[str, Any]],
    *, events: list[dict[str, Any]], cursor: int, created_at: str,
) -> list[dict[str, Any]]:
    # Absence from a different/truncated log is not a deletion. Import its current
    # facts, retaining old conversation facts and all already-delivered notices.
    changes = [
        {
            "event_index": cursor + index,
            "operation": "add",
            "memory_id": item["id"],
            "before": None,
            "after": {"content": item["content"], "keywords": list(item["keywords"])},
            "reason": "记忆来源发生变化，接入当前来源中已有的记忆；缺失的旧记忆不视为删除。",
            "created_at": created_at,
        }
        for index, item in enumerate(current_items, start=1)
    ]
    # A real tombstone in the new log is different from a missing old fact.
    # IDs are stable: honor an explicit final deletion of an already-known ID.
    final_events = {}
    for event in events:
        operation = event.get("operation")
        memory_id = event.get("memory_id") if operation == "add" else event.get("target_memory_id")
        if isinstance(memory_id, str) and operation in {"add", "update", "delete"}:
            final_events[memory_id] = event
    for memory_id in _item_map(existing_items):
        event = final_events.get(memory_id, {})
        if event.get("operation") == "delete":
            changes.append({
                "event_index": cursor + len(changes) + 1,
                "operation": "delete", "memory_id": memory_id,
                "before": None, "after": None,
                "reason": event.get("reason") or "当前记忆来源明确记录了删除。",
                "created_at": event.get("created_at") or created_at,
            })
    return reconcile_memory_changes(existing_items, changes, skip_unchanged=True)


def _item_map(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: {"content": item["content"], "keywords": list(item["keywords"])}
        for item in items
    }
