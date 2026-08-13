from __future__ import annotations

from json import loads
import os
from pathlib import Path
import sqlite3
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
        database_path = _workspace_root() / ".Tiance" / "tiance.db"
        if not database_path.is_file():
            return _error(
                "DATABASE_NOT_FOUND",
                "当前项目还没有 .Tiance/tiance.db，请先在天策中打开一次该项目。",
            )

        with _read_only_connection(database_path) as connection:
            session_row = connection.execute(
                "SELECT payload_json FROM conversation_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if session_row is None:
                return _error("SESSION_NOT_FOUND", "没有找到指定会话。")
            session_payload = _object(session_row[0])
            where, parameters = _where(session_id, query, mode, roles)
            total_count = int(connection.execute(
                f"SELECT COUNT(*) FROM conversation_messages WHERE {where}",
                parameters,
            ).fetchone()[0])
            rows = connection.execute(
                f"""
                SELECT ordinal, message_id, payload_json
                FROM conversation_messages
                WHERE {where}
                ORDER BY ordinal
                LIMIT ? OFFSET ?
                """,
                (*parameters, limit, offset),
            ).fetchall()

        results = []
        for ordinal, message_id, raw_json in rows:
            record = _object(raw_json)
            item = {
                "ordinal": int(ordinal),
                "message_id": str(message_id),
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
            "database_path": str(database_path),
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
    except sqlite3.Error as exc:
        return _error("DATABASE_READ_FAILED", str(exc))
    except (TypeError, ValueError) as exc:
        return _error("INVALID_INPUT", str(exc))
    except Exception as exc:
        return _error("TOOL_FAILED", str(exc) or exc.__class__.__name__)


def _workspace_root() -> Path:
    raw = os.environ.get("TIANCE_WORKSPACE_ROOT") or os.environ.get("WORKSPACE_ROOT") or os.getcwd()
    return Path(raw).expanduser().resolve(strict=False)


def _read_only_connection(path: Path) -> sqlite3.Connection:
    uri = f"{path.as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10.0)
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


def _where(
    session_id: str,
    query: str,
    mode: str,
    roles: tuple[str, ...],
) -> tuple[str, tuple[Any, ...]]:
    clauses = ["session_id = ?"]
    parameters: list[Any] = [session_id]
    if mode == "exact_content":
        clauses.append("json_extract(payload_json, '$.content') = ?")
        parameters.append(query)
    else:
        terms = [query] if mode == "contains" else query.split()
        for term in terms:
            clauses.append("instr(lower(payload_json), lower(?)) > 0")
            parameters.append(term)
    if roles:
        placeholders = ",".join("?" for _ in roles)
        clauses.append(f"json_extract(payload_json, '$.role') IN ({placeholders})")
        parameters.extend(roles)
    return " AND ".join(clauses), tuple(parameters)


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


def _object(raw_json: str) -> dict[str, Any]:
    value = loads(raw_json)
    return value if isinstance(value, dict) else {}


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
