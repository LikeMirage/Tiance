from __future__ import annotations

from json import dumps, loads
import os
from pathlib import Path
from re import fullmatch
from typing import Any

from tiance_runtime import run_tool


MODES = {"contains", "all_terms", "exact_content"}
ROLES = {"user", "assistant", "tool", "system"}


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        query = str(payload.get("query") or "").strip()
        if not query:
            return _error("QUERY_REQUIRED", "必须提供非空 query。")
        mode = str(payload.get("mode") or "contains").strip().lower()
        if mode not in MODES:
            return _error("INVALID_MODE", "不支持的匹配方式。")
        session_id = str(
            payload.get("session_id")
            or os.environ.get("TIANCE_SESSION_ID")
            or ""
        ).strip()
        if not session_id:
            return _error(
                "SESSION_REQUIRED",
                "当前调用没有会话上下文，请填写 session_id。",
            )
        roles = _roles(payload.get("roles"))
        limit = _integer(payload.get("limit"), 20, 1, 100)
        offset = _integer(payload.get("offset"), 0, 0, 1_000_000)
        context_chars = _integer(payload.get("context_chars"), 180, 40, 1000)
        include_raw = payload.get("include_raw", True) is not False
        if not fullmatch(r"[A-Za-z0-9_-]+", session_id):
            return _error("INVALID_SESSION_ID", "session_id 格式无效。")
        session_dir = (
            _workspace_root()
            / ".Tiance"
            / "conversations"
            / "sessions"
            / session_id
        )
        session_path = session_dir / "session.json"
        messages_path = session_dir / "messages.jsonl"
        if not session_path.is_file():
            return _error(
                "SESSION_NOT_FOUND",
                "没有找到指定会话，请确认项目与会话上下文。",
            )
        session_payload = _read_object(session_path)
        results: list[dict[str, Any]] = []
        total_count = 0
        for ordinal, record in _iter_messages(messages_path):
            if not _matches(record, query=query, mode=mode, roles=roles):
                continue
            match_index = total_count
            total_count += 1
            if match_index < offset or len(results) >= limit:
                continue
            item = {
                "ordinal": int(ordinal),
                "message_id": str(record.get("message_id") or ""),
                "role": str(record.get("role") or ""),
                "created_at": str(record.get("created_at") or ""),
                "snippet": _snippet(record, query, context_chars),
            }
            if include_raw:
                item["raw"] = record
            results.append(item)
        return {
            "ok": True,
            "summary": f"在会话中找到 {total_count} 条匹配记录，本次返回 {len(results)} 条。",
            "source_path": str(messages_path),
            "session_id": session_id,
            "session_title": str(session_payload.get("title") or ""),
            "mode": mode,
            "query": query,
            "count": len(results),
            "total_count": total_count,
            "offset": offset,
            "has_more": offset + len(results) < total_count,
            "results": results,
        }
    except OSError as exc:
        return _error("STORAGE_READ_FAILED", str(exc))
    except (TypeError, ValueError) as exc:
        return _error("INVALID_INPUT", str(exc))
    except Exception as exc:
        return _error("TOOL_FAILED", str(exc) or exc.__class__.__name__)


def _workspace_root() -> Path:
    raw = os.environ.get("TIANCE_WORKSPACE_ROOT") or os.environ.get("WORKSPACE_ROOT") or os.getcwd()
    return Path(raw).expanduser().resolve(strict=False)


def _matches(
    record: dict[str, Any],
    *,
    query: str,
    mode: str,
    roles: tuple[str, ...],
) -> bool:
    if roles and str(record.get("role") or "") not in roles:
        return False
    if mode == "exact_content":
        return str(record.get("content") or "") == query
    haystack = dumps(record, ensure_ascii=False, separators=(",", ":")).casefold()
    terms = [query] if mode == "contains" else query.split()
    return all(term.casefold() in haystack for term in terms)


def _read_object(path: Path) -> dict[str, Any]:
    value = loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"数据文件根节点不是对象：{path}")
    return value


def _iter_messages(path: Path):
    if not path.is_file():
        return
    ordinal = 0
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            value = loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"messages.jsonl 第 {line_number} 行不是对象。")
            yield ordinal, value
            ordinal += 1


def _roles(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("roles 必须是数组。")
    roles = tuple(dict.fromkeys(str(item).strip().lower() for item in value))
    invalid = [role for role in roles if role not in ROLES]
    if invalid:
        raise ValueError(f"不支持的消息角色：{', '.join(invalid)}")
    return roles


def _integer(value: object, default: int, minimum: int, maximum: int) -> int:
    result = default if value is None else int(value)
    if result < minimum or result > maximum:
        raise ValueError(f"整数必须在 {minimum} 到 {maximum} 之间。")
    return result


def _snippet(record: dict[str, Any], query: str, context_chars: int) -> str:
    candidates = [
        str(record.get("content") or ""),
        str(record.get("thinking_content") or ""),
    ]
    haystack = next((value for value in candidates if query.casefold() in value.casefold()), "")
    if not haystack:
        haystack = str(record)
    index = haystack.casefold().find(query.casefold())
    if index < 0:
        return haystack[: context_chars * 2]
    start = max(0, index - context_chars)
    end = min(len(haystack), index + len(query) + context_chars)
    return ("…" if start else "") + haystack[start:end] + ("…" if end < len(haystack) else "")


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "summary": message, "error": {"code": code, "message": message}}


if __name__ == "__main__":
    run_tool(run)
