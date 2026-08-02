from __future__ import annotations

import json
from typing import Any


def parse_compaction_result(content: str) -> dict[str, Any]:
    payload = _parse_json_object(content)
    _require_exact_fields(
        payload,
        {"items", "handoff"},
        label="Memory compaction result",
    )

    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("Memory compaction items must be an array.")
    items: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise ValueError("Memory compaction items must be JSON objects.")
        _require_exact_fields(
            item,
            {"content", "keywords"},
            label="Memory compaction item",
        )
        item_content = _string_value(item.get("content"))
        if not item_content:
            raise ValueError("Memory compaction item content must not be empty.")
        items.append(
            {
                "content": item_content,
                "keywords": _parse_keywords(
                    item.get("keywords"),
                    label="Memory compaction item keywords",
                ),
            }
        )
    if not items:
        raise ValueError("Memory compaction result must contain at least one item.")
    handoff = _required_text(payload.get("handoff"), "handoff")
    return {
        "items": items,
        "handoff": handoff,
    }


def compression_record_items(record: dict[str, Any]) -> list[dict[str, Any]]:
    result = record.get("result")
    if not isinstance(result, dict):
        return []
    raw_items = result.get("items")
    if not isinstance(raw_items, list):
        return []
    items: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        content = _string_value(item.get("content"))
        if not content:
            continue
        items.append(
            {
                "content": content,
                "keywords": _string_list(item.get("keywords")),
            }
        )
    return items


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = _strip_json_fence(text)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Memory compaction result must be a JSON object.")
    return payload


def _strip_json_fence(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _require_exact_fields(
    payload: dict[str, Any],
    expected: set[str],
    *,
    label: str,
) -> None:
    actual = set(payload)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    details: list[str] = []
    if missing:
        details.append(f"missing: {', '.join(missing)}")
    if extra:
        details.append(f"extra: {', '.join(extra)}")
    raise ValueError(f"{label} fields do not match the contract ({'; '.join(details)}).")


def _parse_keywords(value: object, *, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array.")
    keywords = _string_list(value)
    if len(keywords) != len(value):
        raise ValueError(f"{label} must contain non-empty strings.")
    return keywords


def _required_text(value: object, label: str) -> str:
    text = _string_value(value)
    if not text:
        raise ValueError(f"Memory compaction {label} must not be empty.")
    return text


def _string_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    values: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _string_value(item)
        if not text or text in seen:
            continue
        values.append(text)
        seen.add(text)
    return values
