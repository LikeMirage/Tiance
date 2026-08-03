from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from index_store import connect


def search_index(
    database_path: Path,
    query: str,
    *,
    mode: str,
    path_prefix: str,
    extensions: tuple[str, ...],
    limit: int,
    offset: int,
    context_chars: int,
) -> dict[str, Any]:
    connection = connect(database_path)
    try:
        terms = [term for term in query.split() if term]
        use_literal_scan = mode != "raw" and any(len(term) < 3 for term in (terms or [query]))
        if use_literal_scan:
            rows = _literal_search(
                connection,
                query,
                terms=terms,
                mode=mode,
                path_prefix=path_prefix,
                extensions=extensions,
                limit=limit,
                offset=offset,
            )
            results = [_literal_result(row, query, terms, context_chars) for row in rows]
            engine = "literal_fallback"
        else:
            expression = _fts_expression(query, terms, mode)
            rows = _fts_search(
                connection,
                expression,
                path_prefix=path_prefix,
                extensions=extensions,
                limit=limit,
                offset=offset,
            )
            results = [dict(row) for row in rows]
            engine = "fts5_trigram"
        return {"query": query, "mode": mode, "engine": engine, "results": results, "count": len(results)}
    except sqlite3.OperationalError as exc:
        raise ValueError(f"FTS5 查询语法无效：{exc}") from exc
    finally:
        connection.close()


def _fts_expression(query: str, terms: list[str], mode: str) -> str:
    if mode == "raw":
        return query
    if mode == "phrase" or not terms:
        return _quote_fts(query)
    quoted = [_quote_fts(term) for term in terms]
    if mode == "any":
        return " OR ".join(quoted)
    if mode == "all":
        return " AND ".join(quoted)
    return " AND ".join(quoted) if len(quoted) > 1 else quoted[0]


def _quote_fts(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


def _fts_search(
    connection: sqlite3.Connection,
    expression: str,
    *,
    path_prefix: str,
    extensions: tuple[str, ...],
    limit: int,
    offset: int,
) -> list[sqlite3.Row]:
    conditions = ["chunks_fts MATCH ?"]
    parameters: list[Any] = [expression]
    _append_filters(conditions, parameters, path_prefix, extensions)
    sql = (
        "SELECT c.path, c.start_line, c.end_line, "
        "snippet(chunks_fts, 0, '【', '】', ' … ', 32) AS snippet, "
        "bm25(chunks_fts) AS rank "
        "FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.rowid "
        "JOIN files f ON f.id=c.file_id WHERE "
        + " AND ".join(conditions)
        + " ORDER BY rank ASC, c.path ASC, c.start_line ASC LIMIT ? OFFSET ?"
    )
    parameters.extend((limit, offset))
    return list(connection.execute(sql, parameters))


def _literal_search(
    connection: sqlite3.Connection,
    query: str,
    *,
    terms: list[str],
    mode: str,
    path_prefix: str,
    extensions: tuple[str, ...],
    limit: int,
    offset: int,
) -> list[sqlite3.Row]:
    values = terms if terms and mode in {"all", "any"} else [query]
    operator = " OR " if mode == "any" else " AND "
    conditions = [operator.join("instr(lower(c.content), lower(?)) > 0" for _ in values)]
    parameters: list[Any] = list(values)
    _append_filters(conditions, parameters, path_prefix, extensions)
    sql = (
        "SELECT c.path, c.start_line, c.end_line, c.content, 0.0 AS rank "
        "FROM chunks c JOIN files f ON f.id=c.file_id WHERE "
        + " AND ".join(f"({condition})" for condition in conditions)
        + " ORDER BY c.path ASC, c.start_line ASC LIMIT ? OFFSET ?"
    )
    parameters.extend((limit, offset))
    return list(connection.execute(sql, parameters))


def _append_filters(
    conditions: list[str],
    parameters: list[Any],
    path_prefix: str,
    extensions: tuple[str, ...],
) -> None:
    if path_prefix:
        normalized = path_prefix.strip("/\\").replace("\\", "/")
        conditions.append("(c.path = ? OR c.path LIKE ?)")
        parameters.extend((normalized, f"{normalized}/%"))
    if extensions:
        normalized_extensions = tuple(item if item.startswith(".") else f".{item}" for item in extensions)
        placeholders = ",".join("?" for _ in normalized_extensions)
        conditions.append(f"f.extension IN ({placeholders})")
        parameters.extend(item.casefold() for item in normalized_extensions)


def _literal_result(row: sqlite3.Row, query: str, terms: list[str], context_chars: int) -> dict[str, Any]:
    content = str(row["content"])
    needles = terms or [query]
    positions = [content.casefold().find(needle.casefold()) for needle in needles if needle]
    positions = [position for position in positions if position >= 0]
    position = min(positions, default=0)
    start = max(0, position - context_chars)
    end = min(len(content), position + max(len(query), 1) + context_chars)
    snippet = content[start:end].replace("\r", "").strip()
    exact_line = int(row["start_line"]) + content[:position].count("\n")
    return {
        "path": row["path"],
        "start_line": exact_line,
        "end_line": int(row["end_line"]),
        "snippet": snippet,
        "rank": row["rank"],
    }
