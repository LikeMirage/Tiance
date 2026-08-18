from __future__ import annotations

from gzip import decompress as gzip_decompress
from json import dumps, loads
import os
from pathlib import Path
import sqlite3
from typing import Any, Callable

from tiance_runtime import run_tool


MODES = {"contains", "all_terms", "exact_content"}
ROLES = {"user", "assistant", "tool", "system", "error"}
SOURCES = ("messages", "model_exchanges", "journal", "artifacts")


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        query = str(payload.get("query") or "").strip()
        if not query:
            return _error("QUERY_REQUIRED", "必须提供非空 query。")
        mode = str(payload.get("mode") or "contains").strip().lower()
        if mode not in MODES:
            return _error("INVALID_MODE", "不支持的匹配方式。")
        sources = _sources(payload.get("sources"))
        if mode == "exact_content" and sources != ("messages",):
            return _error(
                "MODE_SOURCE_CONFLICT",
                "exact_content 只适用于普通消息；检索其他来源请使用 contains 或 all_terms。",
            )
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
                "当前项目没有 .Tiance/tiance.db。",
            )

        with _read_only_connection(database_path) as connection:
            session_row = connection.execute(
                "SELECT payload_json FROM conversation_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if session_row is None:
                return _error("SESSION_NOT_FOUND", "没有找到指定会话。")
            session_payload = _object(session_row[0])
            total_count, source_counts, results, warnings = _search_sources(
                connection,
                session_id=session_id,
                query=query,
                mode=mode,
                roles=roles,
                sources=sources,
                offset=offset,
                limit=limit,
                context_chars=context_chars,
                include_raw=include_raw,
            )

        return {
            "ok": True,
            "summary": f"在会话中找到 {total_count} 条匹配记录，本次返回 {len(results)} 条。",
            "database_path": str(database_path),
            "session_id": session_id,
            "session_title": str(session_payload.get("title") or ""),
            "sources": list(sources),
            "source_counts": source_counts,
            "mode": mode,
            "query": query,
            "count": len(results),
            "total_count": total_count,
            "offset": offset,
            "has_more": offset + len(results) < total_count,
            "results": results,
            "warnings": warnings,
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
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=10.0)
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


def _search_sources(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    query: str,
    mode: str,
    roles: tuple[str, ...],
    sources: tuple[str, ...],
    offset: int,
    limit: int,
    context_chars: int,
    include_raw: bool,
) -> tuple[int, dict[str, int], list[dict[str, Any]], list[str]]:
    searchers: dict[str, Callable[..., tuple[int, list[dict[str, Any]], list[str]]]] = {
        "messages": _search_messages,
        "model_exchanges": _search_model_exchanges,
        "journal": _search_journal,
        "artifacts": _search_artifacts,
    }
    source_counts: dict[str, int] = {}
    results: list[dict[str, Any]] = []
    warnings: list[str] = []
    remaining_offset = offset
    remaining_limit = limit
    total_count = 0
    for source in sources:
        count, items, source_warnings = searchers[source](
            connection,
            session_id=session_id,
            query=query,
            mode=mode,
            roles=roles,
            offset=remaining_offset,
            limit=remaining_limit,
            context_chars=context_chars,
            include_raw=include_raw,
        )
        source_counts[source] = count
        total_count += count
        warnings.extend(source_warnings)
        if remaining_limit > 0:
            results.extend(items)
            remaining_limit -= len(items)
        remaining_offset = max(0, remaining_offset - count)
    return total_count, source_counts, results, warnings


def _search_messages(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    query: str,
    mode: str,
    roles: tuple[str, ...],
    offset: int,
    limit: int,
    context_chars: int,
    include_raw: bool,
) -> tuple[int, list[dict[str, Any]], list[str]]:
    where, parameters = _message_where(session_id, query, mode, roles)
    count = int(connection.execute(
        f"SELECT COUNT(*) FROM conversation_messages WHERE {where}",
        parameters,
    ).fetchone()[0])
    if limit <= 0 or offset >= count:
        return count, [], []
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
    items = []
    for ordinal, message_id, raw_json in rows:
        record = _object(raw_json)
        item = {
            "source": "messages",
            "record_id": str(message_id),
            "message_id": str(message_id),
            "ordinal": int(ordinal),
            "role": str(record.get("role") or ""),
            "created_at": str(record.get("created_at") or ""),
            "snippet": _snippet(record, query, mode, context_chars),
        }
        if include_raw:
            item["raw"] = record
        items.append(item)
    return count, items, []


def _search_model_exchanges(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    query: str,
    mode: str,
    roles: tuple[str, ...],
    offset: int,
    limit: int,
    context_chars: int,
    include_raw: bool,
) -> tuple[int, list[dict[str, Any]], list[str]]:
    del roles
    where, parameters = _json_where(
        ["session_id = ?", "kind = 'model_exchanges'"],
        [session_id],
        query,
        mode,
        ["payload_json"],
    )
    count = int(connection.execute(
        f"SELECT COUNT(*) FROM conversation_session_events WHERE {where}",
        parameters,
    ).fetchone()[0])
    if limit <= 0 or offset >= count:
        return count, [], []
    rows = connection.execute(
        f"""
        SELECT ordinal, payload_json
        FROM conversation_session_events
        WHERE {where}
        ORDER BY ordinal
        LIMIT ? OFFSET ?
        """,
        (*parameters, limit, offset),
    ).fetchall()
    items = []
    for ordinal, raw_json in rows:
        record = _object(raw_json)
        item = {
            "source": "model_exchanges",
            "record_id": f"model_exchange:{ordinal}",
            "ordinal": int(ordinal),
            "created_at": _created_at(record),
            "snippet": _snippet(record, query, mode, context_chars),
        }
        if include_raw:
            item["raw"] = record
        items.append(item)
    return count, items, []


def _search_journal(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    query: str,
    mode: str,
    roles: tuple[str, ...],
    offset: int,
    limit: int,
    context_chars: int,
    include_raw: bool,
) -> tuple[int, list[dict[str, Any]], list[str]]:
    del roles
    where, parameters = _json_where(
        ["session_id = ?"],
        [session_id],
        query,
        mode,
        [
            "event_type", "run_id", "turn_id", "tool_call_id",
            "occurred_at", "payload_json", "artifact_id",
        ],
    )
    count = int(connection.execute(
        f"SELECT COUNT(*) FROM conversation_journal WHERE {where}",
        parameters,
    ).fetchone()[0])
    if limit <= 0 or offset >= count:
        return count, [], []
    rows = connection.execute(
        f"""
        SELECT event_id, run_id, turn_id, tool_call_id, event_type,
               occurred_at, payload_json, artifact_id
        FROM conversation_journal
        WHERE {where}
        ORDER BY event_id
        LIMIT ? OFFSET ?
        """,
        (*parameters, limit, offset),
    ).fetchall()
    items = []
    for event_id, run_id, turn_id, tool_call_id, event_type, occurred_at, raw_json, artifact_id in rows:
        record = {
            "event_id": int(event_id),
            "run_id": run_id,
            "turn_id": turn_id,
            "tool_call_id": tool_call_id,
            "event_type": event_type,
            "occurred_at": occurred_at,
            "payload": _json_value(raw_json),
            "artifact_id": artifact_id,
        }
        item = {
            "source": "journal",
            "record_id": f"journal:{event_id}",
            "event_type": str(event_type),
            "created_at": str(occurred_at),
            "snippet": _snippet(record, query, mode, context_chars),
        }
        if include_raw:
            item["raw"] = record
        items.append(item)
    return count, items, []


def _search_artifacts(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    query: str,
    mode: str,
    roles: tuple[str, ...],
    offset: int,
    limit: int,
    context_chars: int,
    include_raw: bool,
) -> tuple[int, list[dict[str, Any]], list[str]]:
    del roles
    rows = connection.execute(
        """
        SELECT artifact.artifact_id, artifact.kind, artifact.relative_path,
               artifact.media_type, artifact.encoding, artifact.size_bytes,
               artifact.sha256, artifact.status, artifact.created_at,
               artifact.metadata_json, payload.compression, payload.payload_blob
        FROM conversation_artifacts AS artifact
        LEFT JOIN conversation_artifact_payloads AS payload
            ON payload.artifact_id = artifact.artifact_id
        WHERE artifact.session_id = ?
        ORDER BY artifact.created_at, artifact.artifact_id
        """,
        (session_id,),
    ).fetchall()
    matches: list[tuple[dict[str, Any], str]] = []
    warnings: list[str] = []
    for row in rows:
        (
            artifact_id, kind, relative_path, media_type, encoding,
            size_bytes, digest, status, created_at, metadata_json,
            compression, payload_blob,
        ) = row
        metadata = {
            "artifact_id": artifact_id,
            "kind": kind,
            "relative_path": relative_path,
            "media_type": media_type,
            "encoding": encoding,
            "size_bytes": int(size_bytes),
            "sha256": digest,
            "status": status,
            "created_at": created_at,
            "metadata": _json_value(metadata_json),
        }
        payload_text = ""
        if payload_blob is not None:
            try:
                payload_text = _decode_artifact_payload(payload_blob, compression, encoding)
            except (OSError, UnicodeError, ValueError) as exc:
                warnings.append(f"工件 {artifact_id} 的内容无法解码：{exc}")
        searchable = _json_text(metadata)
        if payload_text:
            searchable += "\n" + payload_text
        if _matches(searchable, query, mode):
            matches.append((metadata, payload_text))
    count = len(matches)
    if limit <= 0 or offset >= count:
        return count, [], warnings
    items = []
    for metadata, payload_text in matches[offset:offset + limit]:
        item = {
            "source": "artifacts",
            "record_id": str(metadata["artifact_id"]),
            "artifact_kind": str(metadata["kind"]),
            "created_at": str(metadata["created_at"]),
            "snippet": _snippet_text(
                payload_text or _json_text(metadata),
                query,
                mode,
                context_chars,
            ),
        }
        if include_raw:
            raw = dict(metadata)
            if payload_text:
                raw["payload"] = _json_or_text(payload_text)
            item["raw"] = raw
        items.append(item)
    return count, items, warnings


def _message_where(
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
        clauses, parameters = _append_search_terms(
            clauses, parameters, query, mode, ["payload_json"]
        )
    if roles:
        placeholders = ",".join("?" for _ in roles)
        clauses.append(f"json_extract(payload_json, '$.role') IN ({placeholders})")
        parameters.extend(roles)
    return " AND ".join(clauses), tuple(parameters)


def _json_where(
    clauses: list[str],
    parameters: list[Any],
    query: str,
    mode: str,
    columns: list[str],
) -> tuple[str, tuple[Any, ...]]:
    clauses, parameters = _append_search_terms(clauses, parameters, query, mode, columns)
    return " AND ".join(clauses), tuple(parameters)


def _append_search_terms(
    clauses: list[str],
    parameters: list[Any],
    query: str,
    mode: str,
    columns: list[str],
) -> tuple[list[str], list[Any]]:
    terms = [query] if mode == "contains" else query.split()
    searchable = " || ' ' || ".join(f"coalesce({column}, '')" for column in columns)
    for term in terms:
        clauses.append(f"instr(lower({searchable}), lower(?)) > 0")
        parameters.append(term)
    return clauses, parameters


def _sources(value: object) -> tuple[str, ...]:
    if value is None:
        return ("messages",)
    if not isinstance(value, list) or not value:
        raise ValueError("sources 必须是非空数组。")
    sources = tuple(dict.fromkeys(str(item).strip().lower() for item in value))
    invalid = [source for source in sources if source not in SOURCES]
    if invalid:
        raise ValueError(f"不支持的记录来源：{', '.join(invalid)}")
    return sources


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
    value = _json_value(raw_json)
    return value if isinstance(value, dict) else {}


def _json_value(raw_json: str) -> Any:
    return loads(raw_json)


def _json_or_text(value: str) -> Any:
    try:
        return loads(value)
    except (TypeError, ValueError):
        return value


def _json_text(value: Any) -> str:
    return dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _decode_artifact_payload(payload: bytes, compression: str | None, encoding: str | None) -> str:
    if compression == "gzip":
        payload = gzip_decompress(payload)
    elif compression not in (None, "", "none"):
        raise ValueError(f"不支持的压缩格式 {compression}")
    return payload.decode(encoding or "utf-8")


def _created_at(record: dict[str, Any]) -> str:
    for key in ("created_at", "completed_at", "started_at", "timestamp"):
        value = record.get(key)
        if value:
            return str(value)
    return ""


def _matches(text: str, query: str, mode: str) -> bool:
    haystack = text.casefold()
    if mode == "contains":
        return query.casefold() in haystack
    return all(term.casefold() in haystack for term in query.split())


def _snippet(record: dict[str, Any], query: str, mode: str, context_chars: int) -> str:
    candidates = [
        str(record.get("content") or ""),
        str(record.get("thinking_content") or ""),
        _json_text(record),
    ]
    haystack = next((value for value in candidates if _matches(value, query, mode)), candidates[-1])
    return _snippet_text(haystack, query, mode, context_chars)


def _snippet_text(text: str, query: str, mode: str, context_chars: int) -> str:
    needle = query if mode == "contains" else next(
        (term for term in query.split() if term.casefold() in text.casefold()),
        query,
    )
    index = text.casefold().find(needle.casefold())
    if index < 0:
        return text[: context_chars * 2]
    start = max(0, index - context_chars)
    end = min(len(text), index + len(needle) + context_chars)
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "summary": message, "error": {"code": code, "message": message}}


if __name__ == "__main__":
    run_tool(run)
