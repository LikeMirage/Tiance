from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Iterable
import urllib.error
import urllib.request

import sqlite_vec

from config_loader import AutoParams, ProviderConfig, RetrievalDefaults


STOPWORDS = {
    "一个", "一种", "这些", "那些", "这个", "那个", "这种", "这样", "以及", "或者",
    "如果", "因为", "所以", "但是", "然而", "已经", "没有", "不是", "可以", "必须",
    "问题", "情况", "方面", "过程", "关系", "进行", "对于", "关于", "其中", "由于",
    "马克思", "恩格斯", "全集", "原文", "材料", "论述", "内容", "需要", "寻找", "分析",
    "研究", "说明", "讨论", "如何", "哪些", "什么", "希望", "能够", "经典", "理论",
    "请问", "请看", "查看", "请查看", "是否", "为何", "为什么", "怎么", "怎样",
}
REQUIRED_BASE_TABLES = {"volume", "page", "block"}
VECTOR_TABLE = "page_embedding"
FTS_TABLE = "fts_blocks"
BODY_BLOCK_TYPES = {
    "paragraph", "list", "table", "page_footnote",
    "equation_interline", "page_aside_text", "algorithm",
}
ANCHOR_LENGTHS = (14, 12, 10, 8, 6)
TEXT_MAP_CACHE_SCHEMA = 1


class RetrievalError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class PageMeta:
    page_id: int
    volume_id: int
    volume: str
    physical_page: int
    printed_number: str | None
    char_count: int
    body_char_count: int


@dataclass(frozen=True)
class SearchHit:
    page_id: int
    score: float
    detail: str
    distance: float | None = None
    semantic_weight: float | None = None
    method_ranks: dict[str, int] | None = None
    agreement_count: int | None = None
    match_type: str | None = None
    matched_terms: tuple[str, ...] | None = None
    lexical_coverage: float | None = None
    lexical_occurrences: int | None = None
    longest_anchor: str | None = None
    anchor_count: int | None = None
    literal_strength: int = 0
    semantic_quality_factor: float | None = None


class TextMapResolver:
    """Resolve FTS text rows back to formal block/page rows without trusting FTS rowid."""

    def __init__(
        self,
        *,
        cache_path: Path | None = None,
        memory_map: dict[bytes, list[tuple[int, str]]] | None = None,
        cache_reused: bool = False,
        prepare_seconds: float = 0.0,
        build_seconds: float = 0.0,
        warning: str | None = None,
    ) -> None:
        self.cache_path = cache_path
        self.memory_map = memory_map
        self.cache_reused = cache_reused
        self.prepare_seconds = prepare_seconds
        self.build_seconds = build_seconds
        self.warning = warning
        self.lookup_seconds = 0.0

    def resolve(self, texts: Iterable[str]) -> dict[bytes, list[tuple[int, str]]]:
        started = time.perf_counter()
        keys = list(dict.fromkeys(_text_key(str(text)) for text in texts if text))
        if not keys:
            return {}
        if self.memory_map is not None:
            result = {key: list(self.memory_map.get(key, ())) for key in keys}
            self.lookup_seconds += time.perf_counter() - started
            return result
        if self.cache_path is None:
            return {}
        result: dict[bytes, list[tuple[int, str]]] = defaultdict(list)
        with closing(sqlite3.connect(self.cache_path)) as connection:
            for start in range(0, len(keys), 400):
                batch = keys[start:start + 400]
                placeholders = ",".join("?" for _ in batch)
                for text_hash, page_id, block_type in connection.execute(
                    f"SELECT text_hash,page_id,block_type FROM text_map WHERE text_hash IN ({placeholders})",
                    batch,
                ):
                    result[bytes(text_hash)].append((int(page_id), str(block_type or "")))
        self.lookup_seconds += time.perf_counter() - started
        return dict(result)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "cache_path": str(self.cache_path) if self.cache_path else None,
            "cache_reused": self.cache_reused,
            "prepare_seconds": round(self.prepare_seconds, 4),
            "build_seconds": round(self.build_seconds, 4),
            "lookup_seconds": round(self.lookup_seconds, 4),
            "fallback_in_memory": self.memory_map is not None,
        }


def clean_text(value: str | None) -> str:
    text = re.sub(r"^text\s*", "", value or "", flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def chinese_char_count(value: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", value or ""))


def open_read_only_db(database_path: Path, *, vector: bool = False) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"file:{database_path.as_posix()}?mode=ro",
        uri=True,
        timeout=60,
    )
    if vector:
        try:
            connection.enable_load_extension(True)
            sqlite_vec.load(connection)
        except Exception as exc:
            connection.close()
            raise RetrievalError(
                "SQLITE_VEC_UNAVAILABLE",
                "无法加载 sqlite-vec，向量相关模式不可用。",
                {"error_type": type(exc).__name__},
            ) from exc
    return connection


def table_names(database_path: Path) -> set[str]:
    with closing(open_read_only_db(database_path)) as connection:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }


def validate_base_schema(database_path: Path) -> set[str]:
    names = table_names(database_path)
    missing = sorted(REQUIRED_BASE_TABLES - names)
    if missing:
        raise RetrievalError(
            "UNSUPPORTED_DATABASE",
            "数据库缺少 volume/page/block 基础结构。",
            {"missing_tables": missing, "tables": sorted(names)},
        )
    return names


def inspect_database(database_path: Path) -> tuple[dict[str, Any], list[str]]:
    names = validate_base_schema(database_path)
    warnings: list[str] = []
    with closing(open_read_only_db(database_path)) as connection:
        volumes = [
            {
                "volume_id": int(volume_id),
                "name": str(name),
                "total_pages": int(total_pages or 0),
            }
            for volume_id, name, total_pages in connection.execute(
                "SELECT volume_id,name,total_pages FROM volume ORDER BY volume_id"
            )
        ]
        page_count = int(connection.execute("SELECT COUNT(*) FROM page").fetchone()[0])
        block_count = int(connection.execute("SELECT COUNT(*) FROM block").fetchone()[0])
        block_types = [
            {"type": str(block_type), "count": int(count)}
            for block_type, count in connection.execute(
                "SELECT COALESCE(type,''),COUNT(*) FROM block GROUP BY type ORDER BY COUNT(*) DESC,type"
            )
        ]
        fts_count = None
        if FTS_TABLE in names:
            try:
                fts_count = int(connection.execute(f"SELECT COUNT(*) FROM {FTS_TABLE}").fetchone()[0])
            except sqlite3.Error as exc:
                warnings.append(f"FTS 行数读取失败：{type(exc).__name__}")

        vector_schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name=?",
            (VECTOR_TABLE,),
        ).fetchone()
        vector_sql = str(vector_schema[0] or "") if vector_schema else ""
        dimension_match = re.search(r"float\[(\d+)\]", vector_sql, flags=re.IGNORECASE)
        vector_dimensions = int(dimension_match.group(1)) if dimension_match else None

    vector_count = None
    vector_available = VECTOR_TABLE in names
    if vector_available:
        try:
            with closing(open_read_only_db(database_path, vector=True)) as vector_db:
                vector_count = int(vector_db.execute(f"SELECT COUNT(*) FROM {VECTOR_TABLE}").fetchone()[0])
        except RetrievalError as exc:
            vector_available = False
            warnings.append(exc.message)
        except sqlite3.Error as exc:
            vector_available = False
            warnings.append(f"向量表读取失败：{type(exc).__name__}")

    return {
        "file_size_bytes": database_path.stat().st_size,
        "tables": sorted(names),
        "volumes": volumes,
        "counts": {
            "volumes": len(volumes),
            "pages": page_count,
            "blocks": block_count,
            "fts_rows": fts_count,
            "page_embeddings": vector_count,
        },
        "block_types": block_types,
        "capabilities": {
            "exact": FTS_TABLE in names,
            "keyword": FTS_TABLE in names,
            "vector": vector_available,
            "hybrid": FTS_TABLE in names and vector_available,
            "auto": FTS_TABLE in names and vector_available,
            "consensus": FTS_TABLE in names and vector_available,
        },
        "vector_dimensions": vector_dimensions,
        "read_only": True,
    }, warnings


def load_page_metadata(database_path: Path) -> dict[int, PageMeta]:
    body_types_sql = ",".join("'" + value.replace("'", "''") + "'" for value in sorted(BODY_BLOCK_TYPES))
    with closing(open_read_only_db(database_path)) as connection:
        rows = connection.execute(
            f"""
            SELECT p.page_id,p.volume_id,v.name,p.physical_page,p.printed_number,
                   SUM(length(COALESCE(b.text,''))) AS char_count,
                   SUM(
                       CASE WHEN COALESCE(b.type,'') IN ({body_types_sql})
                            THEN length(COALESCE(b.text,'')) ELSE 0 END
                   ) AS body_char_count
            FROM page p
            JOIN volume v ON v.volume_id=p.volume_id
            LEFT JOIN block b ON b.page_id=p.page_id
            GROUP BY p.page_id
            """
        ).fetchall()
    return {
        int(page_id): PageMeta(
            page_id=int(page_id),
            volume_id=int(volume_id),
            volume=str(volume),
            physical_page=int(physical_page),
            printed_number=str(printed_number) if printed_number is not None else None,
            char_count=int(char_count or 0),
            body_char_count=int(body_char_count or 0),
        )
        for (
            page_id, volume_id, volume, physical_page, printed_number,
            char_count, body_char_count,
        ) in rows
    }


def _text_key(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def load_text_block_map(database_path: Path) -> dict[bytes, list[tuple[int, str]]]:
    """Compatibility/fallback path used by tests and when a sidecar cache cannot be created."""
    mapping: dict[bytes, list[tuple[int, str]]] = defaultdict(list)
    with closing(open_read_only_db(database_path)) as connection:
        cursor = connection.execute(
            "SELECT page_id,COALESCE(type,''),text FROM block WHERE text IS NOT NULL AND text<>''"
        )
        for page_id, block_type, text in cursor:
            mapping[_text_key(str(text))].append((int(page_id), str(block_type or "")))
    return dict(mapping)


def _cache_identity(database_path: Path) -> dict[str, str]:
    stat = database_path.stat()
    with closing(open_read_only_db(database_path)) as connection:
        text_rows = int(
            connection.execute(
                "SELECT COUNT(*) FROM block WHERE text IS NOT NULL AND text<>''"
            ).fetchone()[0]
        )
    return {
        "schema": str(TEXT_MAP_CACHE_SCHEMA),
        "source_path": str(database_path.resolve(strict=False)),
        "source_size": str(stat.st_size),
        "source_mtime_ns": str(stat.st_mtime_ns),
        "text_rows": str(text_rows),
    }


def _cache_is_valid(cache_path: Path, identity: dict[str, str]) -> bool:
    if not cache_path.is_file():
        return False
    try:
        with closing(sqlite3.connect(cache_path)) as connection:
            rows = dict(connection.execute("SELECT key,value FROM metadata").fetchall())
            if any(str(rows.get(key, "")) != value for key, value in identity.items()):
                return False
            row = connection.execute("SELECT COUNT(*) FROM text_map").fetchone()
            return bool(row and int(row[0]) == int(identity["text_rows"]))
    except sqlite3.Error:
        return False


def _build_text_map_cache(database_path: Path, cache_path: Path, identity: dict[str, str]) -> float:
    started = time.perf_counter()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = cache_path.with_name(
        f".{cache_path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    try:
        with closing(sqlite3.connect(temp_path)) as output:
            output.execute("PRAGMA journal_mode=OFF")
            output.execute("PRAGMA synchronous=OFF")
            output.execute(
                "CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)"
            )
            output.execute(
                """
                CREATE TABLE text_map(
                    text_hash BLOB NOT NULL,
                    page_id INTEGER NOT NULL,
                    block_type TEXT NOT NULL
                )
                """
            )
            output.executemany(
                "INSERT INTO metadata(key,value) VALUES(?,?)",
                sorted(identity.items()),
            )
            batch: list[tuple[bytes, int, str]] = []
            with closing(open_read_only_db(database_path)) as source:
                for page_id, block_type, text in source.execute(
                    "SELECT page_id,COALESCE(type,''),text "
                    "FROM block WHERE text IS NOT NULL AND text<>''"
                ):
                    batch.append((_text_key(str(text)), int(page_id), str(block_type or "")))
                    if len(batch) >= 5000:
                        output.executemany(
                            "INSERT INTO text_map(text_hash,page_id,block_type) VALUES(?,?,?)",
                            batch,
                        )
                        batch.clear()
                if batch:
                    output.executemany(
                        "INSERT INTO text_map(text_hash,page_id,block_type) VALUES(?,?,?)",
                        batch,
                    )
            output.execute("CREATE INDEX idx_text_map_hash ON text_map(text_hash)")
            output.commit()
        os.replace(temp_path, cache_path)
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
    return time.perf_counter() - started


def prepare_text_map_resolver(
    database_path: Path,
    cache_root: Path | None,
) -> TextMapResolver:
    started = time.perf_counter()
    if cache_root is not None:
        try:
            identity = _cache_identity(database_path)
            path_key = hashlib.sha256(
                str(database_path.resolve(strict=False)).encode("utf-8")
            ).hexdigest()[:16]
            cache_path = cache_root / f"{database_path.stem}.{path_key}.textmap.sqlite3"
            if _cache_is_valid(cache_path, identity):
                return TextMapResolver(
                    cache_path=cache_path,
                    cache_reused=True,
                    prepare_seconds=time.perf_counter() - started,
                )
            build_seconds = _build_text_map_cache(database_path, cache_path, identity)
            return TextMapResolver(
                cache_path=cache_path,
                cache_reused=False,
                prepare_seconds=time.perf_counter() - started,
                build_seconds=build_seconds,
            )
        except Exception as exc:
            memory = load_text_block_map(database_path)
            return TextMapResolver(
                memory_map=memory,
                prepare_seconds=time.perf_counter() - started,
                warning=f"text-map 持久缓存不可用，已退回内存映射：{type(exc).__name__}",
            )
    memory = load_text_block_map(database_path)
    return TextMapResolver(
        memory_map=memory,
        prepare_seconds=time.perf_counter() - started,
    )


def _resolve_text_refs(
    resolver: TextMapResolver | dict[bytes, list[tuple[int, str]]],
    texts: Iterable[str],
) -> dict[bytes, list[tuple[int, str]]]:
    if isinstance(resolver, TextMapResolver):
        return resolver.resolve(texts)
    keys = list(dict.fromkeys(_text_key(str(text)) for text in texts if text))
    return {key: list(resolver.get(key, ())) for key in keys}


def _eligible_pages(
    database_path: Path,
    page_meta: dict[int, PageMeta],
    volume_ids: tuple[int, ...] | None,
    block_types: tuple[str, ...] | None,
) -> set[int]:
    eligible = set(page_meta)
    if volume_ids:
        selected = set(volume_ids)
        eligible = {page_id for page_id in eligible if page_meta[page_id].volume_id in selected}
    if block_types:
        placeholders = ",".join("?" for _ in block_types)
        with closing(open_read_only_db(database_path)) as connection:
            typed = {
                int(row[0])
                for row in connection.execute(
                    f"SELECT DISTINCT page_id FROM block WHERE type IN ({placeholders})",
                    block_types,
                )
            }
        eligible &= typed
    return eligible


def _fts_quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _exact_anchor(query: str) -> str | None:
    chinese = re.findall(r"[\u4e00-\u9fff]{3,}", query)
    if chinese:
        longest = max(chinese, key=len)
        return longest[: min(16, len(longest))]
    compact = re.sub(r"\s+", " ", query).strip()
    return compact[:16] if len(compact) >= 3 else None


def _strip_outer_quotes(value: str) -> str:
    return value.strip().strip('\"\'“”‘’')


def extract_keywords(query: str, explicit: Iterable[str] | None = None, top_k: int = 6) -> tuple[str, ...]:
    """Dependency-free deterministic fallback extractor.

    Explicit keywords are always preferred. Without them, quoted/title phrases and
    representative 3-8 character fragments from Chinese runs are used. Callers that
    already understand the user's intent should pass keywords explicitly.
    """
    result: list[str] = []

    def add(raw: str) -> None:
        word = re.sub(r"\s+", "", str(raw or "")).strip('\"\'“”‘’《》()（）[]【】')
        count = chinese_char_count(word)
        if not (2 <= count <= 16):
            return
        if word in STOPWORDS or word in result:
            return
        result.append(word)

    if explicit:
        for raw in explicit:
            add(str(raw))
            if len(result) >= top_k:
                break
        return tuple(result[:top_k])

    cleaned = clean_text(query)

    for pattern in (r"《([^》]{2,40})》", r"“([^”]{2,40})”", r'"([^"]{2,40})"'):
        for value in re.findall(pattern, cleaned):
            add(value)
            if len(result) >= top_k:
                return tuple(result)

    for value in re.split(r"[，,、;；|/\s]+", cleaned):
        if 2 <= chinese_char_count(value) <= 10:
            add(value)
            if len(result) >= top_k:
                return tuple(result)

    sequences = re.findall(r"[\u4e00-\u9fff]{3,}", cleaned)
    for sequence in sequences:
        if len(sequence) <= 10:
            add(sequence)
        else:
            for width in (8, 6, 5, 4, 3):
                if len(sequence) < width:
                    continue
                starts = (0, max(0, (len(sequence) - width) // 2), max(0, len(sequence) - width))
                for start in starts:
                    add(sequence[start:start + width])
                    if len(result) >= top_k:
                        return tuple(result)
                break
        if len(result) >= top_k:
            break

    return tuple(result[:top_k])


def _map_fts_texts(
    rows: list[tuple[Any, ...]],
    text_block_map: TextMapResolver | dict[bytes, list[tuple[int, str]]],
    eligible_pages: set[int],
    block_types: tuple[str, ...] | None,
) -> dict[int, list[str]]:
    allowed_types = set(block_types or ())
    texts = [str(row[0] or "") for row in rows if row]
    refs_by_key = _resolve_text_refs(text_block_map, texts)
    page_texts: dict[int, list[str]] = defaultdict(list)
    seen: set[tuple[int, bytes]] = set()
    for row in rows:
        block_text = str(row[0] or "")
        key = _text_key(block_text)
        refs = refs_by_key.get(key, ())
        for page_id, block_type in refs:
            if page_id not in eligible_pages:
                continue
            if allowed_types and block_type not in allowed_types:
                continue
            marker = (page_id, key)
            if marker in seen:
                continue
            seen.add(marker)
            page_texts[page_id].append(block_text)
    return dict(page_texts)


def exact_search(
    database_path: Path,
    page_meta: dict[int, PageMeta],
    text_block_map: TextMapResolver | dict[bytes, list[tuple[int, str]]],
    phrase: str,
    *,
    eligible_pages: set[int],
    block_types: tuple[str, ...] | None,
    candidate_cap: int,
) -> tuple[list[SearchHit], bool, list[str]]:
    phrase = _strip_outer_quotes(phrase)
    if not phrase:
        return [], False, []
    warnings: list[str] = []
    anchor = _exact_anchor(phrase)
    page_counts: dict[int, int] = defaultdict(int)
    truncated = False

    if anchor:
        with closing(open_read_only_db(database_path)) as connection:
            rows = connection.execute(
                f"""
                SELECT text
                FROM {FTS_TABLE}
                WHERE {FTS_TABLE} MATCH ?
                ORDER BY bm25({FTS_TABLE})
                LIMIT ?
                """,
                (_fts_quote(anchor), candidate_cap + 1),
            ).fetchall()
        truncated = len(rows) > candidate_cap
        rows = rows[:candidate_cap]
        refs_by_key = _resolve_text_refs(
            text_block_map,
            [str(raw_text or "") for (raw_text,) in rows],
        )
        allowed_types = set(block_types or ())
        for (raw_text,) in rows:
            block_text = str(raw_text or "")
            if phrase not in block_text:
                continue
            refs = refs_by_key.get(_text_key(block_text), ())
            occurrences = max(1, block_text.count(phrase))
            for page_id, block_type in refs:
                if page_id not in eligible_pages:
                    continue
                if allowed_types and block_type not in allowed_types:
                    continue
                page_counts[page_id] += occurrences
    else:
        warnings.append("精确文本不足 3 个可索引字符，本次使用只读块表扫描兜底。")
        conditions = ["instr(b.text, ?) > 0"]
        params: list[Any] = [phrase]
        if block_types:
            placeholders = ",".join("?" for _ in block_types)
            conditions.append(f"b.type IN ({placeholders})")
            params.extend(block_types)
        sql = (
            "SELECT b.page_id,b.text FROM block b "
            "WHERE b.text IS NOT NULL AND " + " AND ".join(conditions) + " LIMIT ?"
        )
        params.append(candidate_cap + 1)
        with closing(open_read_only_db(database_path)) as connection:
            rows = connection.execute(sql, params).fetchall()
        truncated = len(rows) > candidate_cap
        for page_id, raw_text in rows[:candidate_cap]:
            page_id = int(page_id)
            if page_id not in eligible_pages:
                continue
            block_text = str(raw_text or "")
            page_counts[page_id] += max(1, block_text.count(phrase))

    hits = [
        SearchHit(
            page_id=page_id,
            score=float(count),
            detail=f"精确命中块/次数={count}" + (f"; FTS锚点={anchor}" if anchor else "; 短文本扫描"),
            match_type="exact",
            literal_strength=4,
        )
        for page_id, count in page_counts.items()
        if page_id in page_meta
    ]
    hits.sort(key=lambda item: (-item.score, item.page_id))
    return hits, truncated, warnings


def _literal_anchor_windows(query: str, *, max_windows: int = 48) -> tuple[str, ...]:
    """Generate punctuation-safe literal windows, longest first.

    This is an internal recall layer used only after strict exact matching misses.
    It deliberately does not create a new public search mode.
    """
    text = re.sub(r"^\s*\d+\s*[.、]\s*", "", query or "")
    segments = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{6,}", clean_text(text))
    anchors: list[str] = []
    seen: set[str] = set()
    for length in ANCHOR_LENGTHS:
        for segment in segments:
            if len(segment) < length:
                continue
            stride = max(2, length // 2)
            starts = list(range(0, len(segment) - length + 1, stride))
            last = len(segment) - length
            if last not in starts:
                starts.append(last)
            for start in starts:
                anchor = segment[start:start + length]
                if anchor in seen:
                    continue
                seen.add(anchor)
                anchors.append(anchor)
                if len(anchors) >= max_windows:
                    return tuple(anchors)
    return tuple(anchors)


def anchored_literal_search(
    database_path: Path,
    page_meta: dict[int, PageMeta],
    text_block_map: TextMapResolver | dict[bytes, list[tuple[int, str]]],
    query: str,
    *,
    eligible_pages: set[int],
    block_types: tuple[str, ...] | None,
    per_anchor_cap: int = 120,
) -> tuple[list[SearchHit], bool, tuple[str, ...]]:
    anchors = _literal_anchor_windows(query)
    if not anchors:
        return [], False, ()

    allowed_types = set(block_types or ())
    pairs: list[tuple[str, str]] = []
    truncated = False
    with closing(open_read_only_db(database_path)) as connection:
        for anchor in anchors:
            rows = connection.execute(
                f"""
                SELECT text
                FROM {FTS_TABLE}
                WHERE {FTS_TABLE} MATCH ?
                ORDER BY bm25({FTS_TABLE})
                LIMIT ?
                """,
                (_fts_quote(anchor), per_anchor_cap + 1),
            ).fetchall()
            if len(rows) > per_anchor_cap:
                truncated = True
            for (raw_text,) in rows[:per_anchor_cap]:
                block_text = str(raw_text or "")
                # FTS is only candidate generation. Verify literal evidence ourselves.
                if anchor in block_text:
                    pairs.append((anchor, block_text))

    refs_by_key = _resolve_text_refs(text_block_map, [text for _, text in pairs])
    page_anchors: dict[int, set[str]] = defaultdict(set)
    for anchor, block_text in pairs:
        refs = refs_by_key.get(_text_key(block_text), ())
        for page_id, block_type in refs:
            if page_id not in eligible_pages:
                continue
            if allowed_types and block_type not in allowed_types:
                continue
            page_anchors[page_id].add(anchor)

    hits: list[SearchHit] = []
    for page_id, matched in page_anchors.items():
        ordered = sorted(matched, key=lambda value: (-len(value), value))
        longest = ordered[0]
        count = len(ordered)
        strength = 3 if len(longest) >= 12 else 2 if len(longest) >= 8 else 1
        if strength == 1 and count >= 2:
            strength = 2
        score = (
            0.72 * min(1.0, len(longest) / 14.0)
            + 0.28 * min(1.0, count / 3.0)
        )
        hits.append(
            SearchHit(
                page_id=page_id,
                score=score,
                detail=(
                    f"字面锚点: 最长={len(longest)}字; "
                    f"不同锚点={count}; 示例={longest}"
                ),
                match_type="anchored",
                longest_anchor=longest,
                anchor_count=count,
                literal_strength=strength,
            )
        )
    hits.sort(
        key=lambda hit: (
            -hit.literal_strength,
            -len(hit.longest_anchor or ""),
            -(hit.anchor_count or 0),
            -hit.score,
            hit.page_id,
        )
    )
    return hits, truncated, anchors


def _candidate_pages_from_short_terms(
    database_path: Path,
    short_terms: tuple[str, ...],
    eligible_pages: set[int],
    block_types: tuple[str, ...] | None,
    block_cap: int,
) -> tuple[set[int], bool]:
    if not short_terms:
        return set(), False
    pages: set[int] = set()
    truncated = False
    per_term_cap = max(100, block_cap // max(1, len(short_terms)))
    with closing(open_read_only_db(database_path)) as connection:
        for term in short_terms:
            conditions = ["instr(b.text, ?) > 0", "b.text IS NOT NULL"]
            params: list[Any] = [term]
            if block_types:
                placeholders = ",".join("?" for _ in block_types)
                conditions.append(f"b.type IN ({placeholders})")
                params.extend(block_types)
            params.append(per_term_cap + 1)
            rows = connection.execute(
                "SELECT DISTINCT b.page_id FROM block b WHERE "
                + " AND ".join(conditions)
                + " LIMIT ?",
                params,
            ).fetchall()
            if len(rows) > per_term_cap:
                truncated = True
            pages.update(
                int(page_id)
                for (page_id,) in rows[:per_term_cap]
                if int(page_id) in eligible_pages
            )
    return pages, truncated


def _full_text_for_pages(
    database_path: Path,
    page_ids: Iterable[int],
    block_types: tuple[str, ...] | None,
) -> dict[int, str]:
    ids = sorted(set(int(value) for value in page_ids))
    if not ids:
        return {}
    result: dict[int, list[str]] = defaultdict(list)
    with closing(open_read_only_db(database_path)) as connection:
        for start in range(0, len(ids), 700):
            batch = ids[start:start + 700]
            placeholders = ",".join("?" for _ in batch)
            params: list[Any] = list(batch)
            type_sql = ""
            if block_types:
                type_placeholders = ",".join("?" for _ in block_types)
                type_sql = f" AND type IN ({type_placeholders})"
                params.extend(block_types)
            rows = connection.execute(
                f"""
                SELECT page_id,text
                FROM block
                WHERE page_id IN ({placeholders})
                  AND text IS NOT NULL AND text<>''
                  {type_sql}
                ORDER BY page_id,seq,block_id
                """,
                params,
            ).fetchall()
            for page_id, text in rows:
                result[int(page_id)].append(clean_text(str(text or "")))
    return {page_id: "\n".join(parts) for page_id, parts in result.items()}


def keyword_search(
    database_path: Path,
    page_meta: dict[int, PageMeta],
    text_block_map: TextMapResolver | dict[bytes, list[tuple[int, str]]],
    query: str,
    explicit_keywords: Iterable[str] | None,
    *,
    eligible_pages: set[int],
    block_types: tuple[str, ...] | None,
    block_candidate_cap: int,
    page_candidate_cap: int,
) -> tuple[list[SearchHit], bool, tuple[str, ...], list[str]]:
    terms = extract_keywords(query, explicit_keywords)
    if not terms:
        return [], False, (), ["没有提取到可用关键词。"]

    warnings: list[str] = []
    long_terms = tuple(term for term in terms if chinese_char_count(term) >= 3 or len(term) >= 3)
    short_terms = tuple(term for term in terms if term not in long_terms)
    candidate_pages: set[int] = set()
    truncated = False

    # Give each term its own quota. A very common term can no longer consume
    # the entire FTS candidate pool before the other terms are examined.
    if long_terms:
        per_term_cap = max(100, block_candidate_cap // max(1, len(long_terms)))
        with closing(open_read_only_db(database_path)) as connection:
            for term in long_terms:
                rows = connection.execute(
                    f"""
                    SELECT text,bm25({FTS_TABLE}) AS rank
                    FROM {FTS_TABLE}
                    WHERE {FTS_TABLE} MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (_fts_quote(term), per_term_cap + 1),
                ).fetchall()
                if len(rows) > per_term_cap:
                    truncated = True
                mapped = _map_fts_texts(
                    rows[:per_term_cap],
                    text_block_map,
                    eligible_pages,
                    block_types,
                )
                candidate_pages.update(mapped)

    if short_terms:
        short_pages, short_truncated = _candidate_pages_from_short_terms(
            database_path,
            short_terms,
            eligible_pages,
            block_types,
            block_candidate_cap,
        )
        candidate_pages.update(short_pages)
        truncated = truncated or short_truncated
        warnings.append(
            "包含不足 3 个可索引字符的关键词；已按每词独立配额使用只读块表扫描补充短词候选。"
        )

    if not candidate_pages:
        return [], truncated, terms, warnings

    page_texts = _full_text_for_pages(database_path, candidate_pages, block_types)
    hits: list[SearchHit] = []
    for page_id, combined in page_texts.items():
        if page_id not in page_meta:
            continue
        matched_terms = tuple(term for term in terms if term in combined)
        covered = len(matched_terms)
        if covered <= 0:
            continue
        occurrences = sum(combined.count(term) for term in terms)
        coverage = covered / max(1, len(terms))
        density = min(1.0, occurrences / max(1.0, page_meta[page_id].char_count / 180.0))
        score = 0.85 * coverage + 0.15 * density
        hits.append(
            SearchHit(
                page_id=page_id,
                score=float(score),
                detail=f"关键词覆盖={covered}/{len(terms)}; 出现次数={occurrences}",
                match_type="lexical",
                matched_terms=matched_terms,
                lexical_coverage=coverage,
                lexical_occurrences=occurrences,
                literal_strength=2 if coverage >= 0.67 else 1,
            )
        )
    hits.sort(key=lambda item: (-item.score, item.page_id))
    return hits[:page_candidate_cap], truncated, terms, warnings


def embed_query(query: str, config: ProviderConfig) -> tuple[list[float], float]:
    body = json.dumps(
        {
            "model": config.model,
            "input": [query],
            "encoding_format": "float",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    last_error: Exception | None = None
    started = time.perf_counter()
    for attempt in range(config.attempts):
        try:
            request = urllib.request.Request(
                config.base_url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {config.api_key}",
                    "User-Agent": "TianceStructuredDatabaseSearch/0.1",
                },
            )
            with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            vector = payload["data"][0]["embedding"]
            if len(vector) != config.dimensions:
                raise RuntimeError(f"Embedding 维度不符：{len(vector)}/{config.dimensions}")
            return [float(value) for value in vector], time.perf_counter() - started
        except Exception as exc:
            last_error = exc
            if attempt + 1 < config.attempts:
                time.sleep(config.retry_base_delay_seconds * (2 ** attempt))
    raise RetrievalError(
        "EMBEDDING_FAILED",
        "SiliconFlow 查询向量生成失败。",
        {"error_type": type(last_error).__name__ if last_error else "Unknown"},
    ) from last_error


def semantic_search(
    database_path: Path,
    page_meta: dict[int, PageMeta],
    query: str,
    provider: ProviderConfig,
    *,
    eligible_pages: set[int],
    semantic_k: int,
) -> tuple[list[SearchHit], dict[str, Any]]:
    vector, embedding_seconds = embed_query(query, provider)
    total_vectors = 0
    with closing(open_read_only_db(database_path, vector=True)) as connection:
        total_vectors = int(connection.execute(f"SELECT COUNT(*) FROM {VECTOR_TABLE}").fetchone()[0])

    raw_k = min(total_vectors, max(semantic_k, semantic_k * (8 if len(eligible_pages) < len(page_meta) else 1)))

    def run(k: int) -> list[tuple[int, float]]:
        with closing(open_read_only_db(database_path, vector=True)) as connection:
            return [
                (int(page_id), float(distance))
                for page_id, distance in connection.execute(
                    f"""
                    SELECT page_id,distance
                    FROM {VECTOR_TABLE}
                    WHERE embedding MATCH ? AND k=?
                    ORDER BY distance
                    """,
                    (json.dumps(vector, ensure_ascii=False), int(k)),
                ).fetchall()
            ]

    knn_started = time.perf_counter()
    rows = run(raw_k)
    filtered = [row for row in rows if row[0] in eligible_pages]
    reran = False
    if len(filtered) < semantic_k and raw_k < total_vectors:
        second_k = min(total_vectors, max(raw_k, min(10000, semantic_k * 40)))
        if second_k > raw_k:
            rows = run(second_k)
            filtered = [row for row in rows if row[0] in eligible_pages]
            raw_k = second_k
            reran = True
    knn_seconds = time.perf_counter() - knn_started

    hits = [
        SearchHit(
            page_id=page_id,
            score=1.0 / (1.0 + distance),
            detail=f"向量距离={distance:.6f}",
            distance=distance,
        )
        for page_id, distance in filtered[:semantic_k]
        if page_id in page_meta
    ]
    return hits, {
        "embedding_seconds": round(embedding_seconds, 4),
        "knn_seconds": round(knn_seconds, 4),
        "raw_k": raw_k,
        "filtered_hits": len(filtered),
        "reran_for_scope": reran,
    }


def _minmax(hits: list[SearchHit]) -> dict[int, float]:
    if not hits:
        return {}
    values = [hit.score for hit in hits]
    lo = min(values)
    hi = max(values)
    if math.isclose(lo, hi):
        return {hit.page_id: 1.0 for hit in hits}
    return {hit.page_id: (hit.score - lo) / (hi - lo) for hit in hits}


def _semantic_page_quality_factor(meta: PageMeta) -> float:
    """Penalize nearly-empty pages only when semantic evidence is used for fusion."""
    body = meta.body_char_count
    if body >= 80:
        return 1.0
    if body <= 0:
        return 0.15
    if body <= 20:
        return 0.25
    return 0.25 + 0.75 * ((body - 20.0) / 60.0)


def quality_adjusted_vector_hits(
    vector_hits: list[SearchHit],
    page_meta: dict[int, PageMeta],
) -> list[SearchHit]:
    adjusted: list[SearchHit] = []
    for hit in vector_hits:
        meta = page_meta.get(hit.page_id)
        factor = _semantic_page_quality_factor(meta) if meta is not None else 1.0
        adjusted.append(
            SearchHit(
                page_id=hit.page_id,
                score=hit.score * factor,
                detail=hit.detail + f"; 语义页质量系数={factor:.3f}",
                distance=hit.distance,
                match_type=hit.match_type or "semantic_only",
                semantic_quality_factor=factor,
            )
        )
    adjusted.sort(key=lambda item: (-item.score, item.page_id))
    return adjusted


def hybrid_rank(
    keyword_hits: list[SearchHit],
    vector_hits: list[SearchHit],
    keyword_weight: float,
) -> list[SearchHit]:
    keyword = _minmax(keyword_hits)
    vector = _minmax(vector_hits)
    pages = set(keyword) | set(vector)
    scored = [
        SearchHit(
            page_id=page_id,
            score=keyword_weight * keyword.get(page_id, 0.0)
            + (1.0 - keyword_weight) * vector.get(page_id, 0.0),
            detail=(
                f"固定混合: 词={keyword_weight:.2f}, 向={1.0-keyword_weight:.2f}; "
                f"词归一={keyword.get(page_id,0.0):.4f}; 向归一={vector.get(page_id,0.0):.4f}"
            ),
        )
        for page_id in pages
    ]
    scored.sort(key=lambda item: (-item.score, item.page_id))
    return scored


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, value))))


def auto_rank(
    query: str,
    page_meta: dict[int, PageMeta],
    exact_hits: list[SearchHit],
    anchor_hits: list[SearchHit],
    keyword_hits: list[SearchHit],
    vector_hits: list[SearchHit],
    params: AutoParams,
) -> list[SearchHit]:
    keyword = _minmax(keyword_hits)
    vector = _minmax(vector_hits)
    pages = sorted(set(keyword) | set(vector))
    lexical_confidence = max((hit.score for hit in keyword_hits), default=0.0)
    vector_scores = [hit.score for hit in vector_hits]
    if vector_scores:
        comparison_index = min(4, len(vector_scores) - 1)
        denominator = max(abs(vector_scores[0]), 1e-9)
        semantic_margin = max(
            0.0,
            (vector_scores[0] - vector_scores[comparison_index]) / denominator,
        )
    else:
        semantic_margin = 0.0

    query_chars = chinese_char_count(query) or len(query)
    ranked: list[SearchHit] = []
    for page_id in pages:
        meta = page_meta.get(page_id)
        if meta is None:
            continue
        length_signal = math.tanh(
            math.log((query_chars + 1.0) / (meta.char_count + 1.0)) / 3.0
        )
        semantic_weight = _sigmoid(
            params.bias
            + params.length_ratio_coefficient * length_signal
            - params.lexical_confidence_coefficient * (lexical_confidence - 0.5) * 2.0
            + params.semantic_margin_coefficient * semantic_margin
        )
        score = (
            (1.0 - semantic_weight) * keyword.get(page_id, 0.0)
            + semantic_weight * vector.get(page_id, 0.0)
        )
        ranked.append(
            SearchHit(
                page_id=page_id,
                score=score,
                semantic_weight=semantic_weight,
                detail=(
                    f"动态权重: 向量权重={semantic_weight:.4f}; "
                    f"词归一={keyword.get(page_id,0.0):.4f}; "
                    f"向归一={vector.get(page_id,0.0):.4f}"
                ),
            )
        )
    ranked.sort(key=lambda item: (-item.score, item.page_id))

    # Tier 1: strict exact evidence always wins.
    if exact_hits:
        exact_ids = {hit.page_id for hit in exact_hits}
        output = [
            SearchHit(
                page_id=hit.page_id,
                score=hit.score,
                detail="精确门控 · " + hit.detail,
                semantic_weight=None,
                match_type="exact",
                literal_strength=4,
            )
            for hit in exact_hits
        ]
        output.extend(hit for hit in ranked if hit.page_id not in exact_ids)
        return output

    # Tier 2: after strict exact misses, verified 8+ character anchors (or
    # multiple 6-char anchors) are stronger source evidence than semantic-only
    # similarity. Weak single 6-char anchors remain diagnostic evidence only.
    strong_anchors = [hit for hit in anchor_hits if hit.literal_strength >= 2]
    if strong_anchors:
        strong_ids = {hit.page_id for hit in strong_anchors}
        output = [
            SearchHit(
                page_id=hit.page_id,
                score=hit.score,
                detail="字面证据优先 · " + hit.detail,
                match_type="anchored",
                longest_anchor=hit.longest_anchor,
                anchor_count=hit.anchor_count,
                literal_strength=hit.literal_strength,
            )
            for hit in strong_anchors
        ]
        output.extend(hit for hit in ranked if hit.page_id not in strong_ids)
        return output

    return ranked


def consensus_rank(
    exact_hits: list[SearchHit],
    anchor_hits: list[SearchHit],
    keyword_hits: list[SearchHit],
    vector_hits: list[SearchHit],
    hybrid_hits: list[SearchHit],
    auto_hits: list[SearchHit],
    *,
    rrf_k: float,
    weights: dict[str, float],
) -> list[SearchHit]:
    methods = {
        "exact": exact_hits,
        "anchor": anchor_hits,
        "keyword": keyword_hits,
        "vector": vector_hits,
        "hybrid": hybrid_hits,
        "auto": auto_hits,
    }
    ranks: dict[str, dict[int, int]] = {
        name: {hit.page_id: rank for rank, hit in enumerate(hits, start=1)}
        for name, hits in methods.items()
    }
    pages: set[int] = set()
    for page_ranks in ranks.values():
        pages.update(page_ranks)

    exact_pages = set(ranks["exact"])
    anchor_by_page = {hit.page_id: hit for hit in anchor_hits}
    base_methods = ("exact", "keyword", "vector")
    output: list[SearchHit] = []
    for page_id in pages:
        agreement = sum(page_id in ranks[name] for name in base_methods)
        score = 0.0
        method_ranks: dict[str, int] = {}
        for name, page_ranks in ranks.items():
            rank = page_ranks.get(page_id)
            if rank is None:
                continue
            method_ranks[name] = rank
            default_weight = 1.25 if name == "anchor" else 1.0
            score += float(weights.get(name, default_weight)) / (rrf_k + rank)
        anchor = anchor_by_page.get(page_id)
        literal_strength = anchor.literal_strength if anchor is not None else 0
        output.append(
            SearchHit(
                page_id=page_id,
                score=score,
                agreement_count=agreement,
                method_ranks=method_ranks,
                literal_strength=literal_strength,
                longest_anchor=anchor.longest_anchor if anchor else None,
                anchor_count=anchor.anchor_count if anchor else None,
                detail=(
                    f"共识: 基础通道共同命中={agreement}/3; "
                    f"字面证据等级={literal_strength}; "
                    + "; ".join(
                        f"{name}#{rank}"
                        for name, rank in sorted(method_ranks.items())
                    )
                ),
            )
        )
    output.sort(
        key=lambda hit: (
            -(1 if hit.page_id in exact_pages else 0),
            -(hit.literal_strength if hit.literal_strength >= 2 else 0),
            -(hit.agreement_count or 0),
            -hit.score,
            hit.page_id,
        )
    )
    return output


def _snippet(text: str, terms: tuple[str, ...], phrase: str, width: int = 240) -> str:
    compact = clean_text(text)
    if not compact:
        return ""
    needles = [value for value in (phrase, *terms) if value]
    positions = [compact.find(value) for value in needles if compact.find(value) >= 0]
    if positions:
        center = min(positions)
        start = max(0, center - width // 3)
    else:
        start = 0
    end = min(len(compact), start + width)
    return ("…" if start else "") + compact[start:end] + ("…" if end < len(compact) else "")


def _ranked_hit_map(hits: list[SearchHit]) -> dict[int, tuple[int, SearchHit]]:
    return {
        hit.page_id: (rank, hit)
        for rank, hit in enumerate(hits, start=1)
    }


def _score_type_for_mode(mode: str) -> str:
    return {
        "exact": "exact_occurrence_count",
        "keyword": "lexical_rank_score",
        "vector": "vector_similarity_transform",
        "hybrid": "hybrid_fusion",
        "auto": "auto_fusion_with_literal_tiers",
        "consensus": "rrf_consensus_with_literal_tiers",
    }.get(mode, "rank_score")


def hydrate_results(
    database_path: Path,
    page_meta: dict[int, PageMeta],
    hits: list[SearchHit],
    *,
    limit: int,
    terms: tuple[str, ...],
    phrase: str,
    mode: str,
    exact_hits: list[SearchHit],
    anchor_hits: list[SearchHit],
    keyword_hits: list[SearchHit],
    vector_hits: list[SearchHit],
) -> list[dict[str, Any]]:
    selected = hits[:limit]
    texts = _full_text_for_pages(database_path, [hit.page_id for hit in selected], None)
    exact_map = _ranked_hit_map(exact_hits)
    anchor_map = _ranked_hit_map(anchor_hits)
    keyword_map = _ranked_hit_map(keyword_hits)
    vector_map = _ranked_hit_map(vector_hits)

    results: list[dict[str, Any]] = []
    for rank, hit in enumerate(selected, start=1):
        meta = page_meta.get(hit.page_id)
        if meta is None:
            continue

        exact_evidence = exact_map.get(hit.page_id)
        anchor_evidence = anchor_map.get(hit.page_id)
        keyword_evidence = keyword_map.get(hit.page_id)
        vector_evidence = vector_map.get(hit.page_id)

        has_literal = bool(exact_evidence or anchor_evidence or keyword_evidence)
        if exact_evidence:
            match_type = "exact"
        elif anchor_evidence or keyword_evidence:
            match_type = "lexical_semantic" if vector_evidence else "lexical_only"
        else:
            match_type = "semantic_only"

        evidence: dict[str, Any] = {
            "exact": {
                "hit": bool(exact_evidence),
                "rank": exact_evidence[0] if exact_evidence else None,
            },
            "anchor": {
                "hit": bool(anchor_evidence),
                "rank": anchor_evidence[0] if anchor_evidence else None,
                "longest": (
                    anchor_evidence[1].longest_anchor
                    if anchor_evidence else None
                ),
                "count": (
                    anchor_evidence[1].anchor_count
                    if anchor_evidence else None
                ),
                "strength": (
                    anchor_evidence[1].literal_strength
                    if anchor_evidence else 0
                ),
            },
            "keyword": {
                "hit": bool(keyword_evidence),
                "rank": keyword_evidence[0] if keyword_evidence else None,
                "score": (
                    round(float(keyword_evidence[1].score), 8)
                    if keyword_evidence else None
                ),
                "coverage": (
                    round(float(keyword_evidence[1].lexical_coverage), 6)
                    if keyword_evidence
                    and keyword_evidence[1].lexical_coverage is not None
                    else None
                ),
                "matched_terms": (
                    list(keyword_evidence[1].matched_terms or ())
                    if keyword_evidence else []
                ),
                "occurrences": (
                    keyword_evidence[1].lexical_occurrences
                    if keyword_evidence else None
                ),
            },
            "vector": {
                "hit": bool(vector_evidence),
                "rank": vector_evidence[0] if vector_evidence else None,
                "distance": (
                    round(float(vector_evidence[1].distance), 8)
                    if vector_evidence and vector_evidence[1].distance is not None
                    else None
                ),
                "similarity_transform": (
                    round(float(vector_evidence[1].score), 8)
                    if vector_evidence else None
                ),
                "page_quality_factor": (
                    round(_semantic_page_quality_factor(meta), 6)
                    if vector_evidence else None
                ),
            },
        }

        result: dict[str, Any] = {
            "rank": rank,
            "page_id": meta.page_id,
            "volume_id": meta.volume_id,
            "volume": meta.volume,
            "physical_page": meta.physical_page,
            "printed_number": meta.printed_number,
            "page_char_count": meta.char_count,
            "body_char_count": meta.body_char_count,
            "rank_score": round(float(hit.score), 8),
            "score_type": _score_type_for_mode(mode),
            "score_note": (
                "rank_score 仅用于当前查询内部排序，不是命中概率；不同 mode 的 rank_score 不可直接横向比较。"
            ),
            "match_type": match_type,
            "has_literal_evidence": has_literal,
            "evidence": evidence,
            "detail": hit.detail,
            "snippet": _snippet(texts.get(hit.page_id, ""), terms, phrase),
        }
        if match_type == "semantic_only":
            result["evidence_note"] = (
                "仅有语义近邻证据；若任务是引文/原句溯源，不能据此直接认定出处。"
            )
        elif match_type == "exact":
            result["evidence_note"] = "存在完整连续原文证据。"
        else:
            result["evidence_note"] = "存在词面证据；请结合 matched_terms/anchor 与上下文判断。"

        if hit.distance is not None:
            result["vector_distance"] = round(hit.distance, 8)
        if hit.semantic_weight is not None:
            result["semantic_weight"] = round(hit.semantic_weight, 8)
        if hit.method_ranks is not None:
            result["method_ranks"] = hit.method_ranks
        if hit.agreement_count is not None:
            result["agreement_count"] = hit.agreement_count
        results.append(result)
    return results


def search_database(
    database_path: Path,
    *,
    mode: str,
    query: str,
    explicit_keywords: tuple[str, ...] | None,
    exact_query: str | None,
    volume_ids: tuple[int, ...] | None,
    block_types: tuple[str, ...] | None,
    limit: int,
    semantic_k: int,
    exact_candidate_cap: int,
    keyword_block_cap: int,
    keyword_page_cap: int,
    keyword_weight: float,
    auto_params: AutoParams,
    provider: ProviderConfig | None,
    defaults: RetrievalDefaults,
    cache_root: Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    names = validate_base_schema(database_path)
    if FTS_TABLE not in names and mode in {"exact", "keyword", "hybrid", "auto", "consensus"}:
        raise RetrievalError("FTS_UNAVAILABLE", "数据库没有 fts_blocks，当前模式不可用。")
    if mode in {"vector", "hybrid", "auto", "consensus"} and VECTOR_TABLE not in names:
        raise RetrievalError("VECTOR_UNAVAILABLE", "数据库没有 page_embedding，当前模式不可用。")
    if mode in {"vector", "hybrid", "auto", "consensus"} and provider is None:
        raise RetrievalError("PROVIDER_REQUIRED", "当前模式需要 SiliconFlow Embedding 配置。")

    started = time.perf_counter()
    warnings: list[str] = []
    page_meta = load_page_metadata(database_path)
    eligible = _eligible_pages(database_path, page_meta, volume_ids, block_types)
    if not eligible:
        return {
            "mode": mode,
            "query": query,
            "results": [],
            "source_status": "no_candidates",
            "literal_evidence_found": False,
            "strong_literal_evidence_found": False,
            "diagnostics": {
                "eligible_pages": 0,
                "elapsed_seconds": round(time.perf_counter() - started, 4),
            },
        }, ["筛选条件下没有可检索页面。"]

    phrase = _strip_outer_quotes(exact_query or query)
    terms: tuple[str, ...] = ()
    exact_hits: list[SearchHit] = []
    anchor_hits: list[SearchHit] = []
    keyword_hits: list[SearchHit] = []
    vector_hits: list[SearchHit] = []
    fusion_vector_hits: list[SearchHit] = []
    exact_truncated = False
    anchor_truncated = False
    keyword_truncated = False
    vector_diag: dict[str, Any] = {}
    anchor_windows: tuple[str, ...] = ()

    need_text_map = mode in {"exact", "keyword", "hybrid", "auto", "consensus"}
    text_resolver: TextMapResolver | dict[bytes, list[tuple[int, str]]] = {}
    if need_text_map:
        text_resolver = prepare_text_map_resolver(database_path, cache_root)
        if isinstance(text_resolver, TextMapResolver) and text_resolver.warning:
            warnings.append(text_resolver.warning)

    vector_future = None
    executor = None
    if mode in {"vector", "hybrid", "auto", "consensus"}:
        executor = ThreadPoolExecutor(max_workers=2)
        vector_future = executor.submit(
            semantic_search,
            database_path,
            page_meta,
            query,
            provider,
            eligible_pages=eligible,
            semantic_k=semantic_k,
        )

    if mode == "exact":
        exact_hits, exact_truncated, exact_warnings = exact_search(
            database_path,
            page_meta,
            text_resolver,
            phrase,
            eligible_pages=eligible,
            block_types=block_types,
            candidate_cap=exact_candidate_cap,
        )
        warnings.extend(exact_warnings)
        final_hits = exact_hits

    elif mode == "keyword":
        keyword_hits, keyword_truncated, terms, keyword_warnings = keyword_search(
            database_path,
            page_meta,
            text_resolver,
            query,
            explicit_keywords,
            eligible_pages=eligible,
            block_types=block_types,
            block_candidate_cap=keyword_block_cap,
            page_candidate_cap=keyword_page_cap,
        )
        warnings.extend(keyword_warnings)
        final_hits = keyword_hits

    elif mode == "vector":
        assert vector_future is not None
        vector_hits, vector_diag = vector_future.result()
        terms = extract_keywords(query, explicit_keywords)
        final_hits = vector_hits

    else:
        with ThreadPoolExecutor(max_workers=2) as lexical_executor:
            keyword_future = lexical_executor.submit(
                keyword_search,
                database_path,
                page_meta,
                text_resolver,
                query,
                explicit_keywords,
                eligible_pages=eligible,
                block_types=block_types,
                block_candidate_cap=keyword_block_cap,
                page_candidate_cap=keyword_page_cap,
            )
            exact_future = None
            if mode in {"auto", "consensus"}:
                exact_future = lexical_executor.submit(
                    exact_search,
                    database_path,
                    page_meta,
                    text_resolver,
                    phrase,
                    eligible_pages=eligible,
                    block_types=block_types,
                    candidate_cap=exact_candidate_cap,
                )
            keyword_hits, keyword_truncated, terms, keyword_warnings = keyword_future.result()
            warnings.extend(keyword_warnings)
            if exact_future is not None:
                exact_hits, exact_truncated, exact_warnings = exact_future.result()
                warnings.extend(exact_warnings)

        # Strict exact is intentionally attempted first. Only after it misses do
        # auto/consensus add the internal multi-level literal-anchor layer.
        if mode in {"auto", "consensus"} and not exact_hits:
            anchor_hits, anchor_truncated, anchor_windows = anchored_literal_search(
                database_path,
                page_meta,
                text_resolver,
                phrase,
                eligible_pages=eligible,
                block_types=block_types,
            )

        assert vector_future is not None
        vector_hits, vector_diag = vector_future.result()
        fusion_vector_hits = quality_adjusted_vector_hits(vector_hits, page_meta)

        if mode == "hybrid":
            final_hits = hybrid_rank(keyword_hits, fusion_vector_hits, keyword_weight)
        elif mode == "auto":
            final_hits = auto_rank(
                query,
                page_meta,
                exact_hits,
                anchor_hits,
                keyword_hits,
                fusion_vector_hits,
                auto_params,
            )
        else:
            hybrid_hits = hybrid_rank(keyword_hits, fusion_vector_hits, keyword_weight)
            auto_hits = auto_rank(
                query,
                page_meta,
                exact_hits,
                anchor_hits,
                keyword_hits,
                fusion_vector_hits,
                auto_params,
            )
            final_hits = consensus_rank(
                exact_hits,
                anchor_hits,
                keyword_hits,
                fusion_vector_hits,
                hybrid_hits,
                auto_hits,
                rrf_k=defaults.consensus_rrf_k,
                weights=defaults.consensus_weights,
            )

    if executor is not None:
        executor.shutdown(wait=True)

    results = hydrate_results(
        database_path,
        page_meta,
        final_hits,
        limit=limit,
        terms=terms,
        phrase=phrase,
        mode=mode,
        exact_hits=exact_hits,
        anchor_hits=anchor_hits,
        keyword_hits=keyword_hits,
        vector_hits=vector_hits,
    )

    literal_evidence_found = bool(exact_hits or anchor_hits or keyword_hits)
    strong_literal_evidence_found = bool(
        exact_hits
        or any(hit.literal_strength >= 2 for hit in anchor_hits)
        or any(
            hit.lexical_coverage is not None and hit.lexical_coverage >= 0.67
            for hit in keyword_hits
        )
    )
    if exact_hits:
        source_status = "exact_evidence"
    elif strong_literal_evidence_found:
        source_status = "literal_evidence"
    elif literal_evidence_found:
        source_status = "weak_literal_evidence"
    elif final_hits:
        source_status = "semantic_only_candidates"
    else:
        source_status = "no_candidates"

    if mode in {"hybrid", "auto", "consensus"} and final_hits and not strong_literal_evidence_found:
        warnings.append(
            "未发现强字面证据；当前结果主要依赖语义或弱词面信号。"
            "若任务是引文/原句溯源，不能直接把这些候选视为出处。"
        )

    resolver_diag = (
        text_resolver.diagnostics()
        if isinstance(text_resolver, TextMapResolver)
        else {
            "cache_path": None,
            "cache_reused": False,
            "prepare_seconds": 0.0,
            "build_seconds": 0.0,
            "lookup_seconds": 0.0,
            "fallback_in_memory": bool(text_resolver),
        }
    )
    diagnostics = {
        "eligible_pages": len(eligible),
        "base_candidate_counts": {
            "exact": len(exact_hits),
            "anchor": len(anchor_hits),
            "keyword": len(keyword_hits),
            "vector": len(vector_hits),
        },
        "exact_candidates_truncated": exact_truncated,
        "anchor_candidates_truncated": anchor_truncated,
        "keyword_candidates_truncated": keyword_truncated,
        "terms": list(terms),
        "exact_query": phrase if mode in {"exact", "auto", "consensus"} else None,
        "literal_anchor_query": (
            phrase if mode in {"auto", "consensus"} and not exact_hits else None
        ),
        "literal_anchor_windows": list(anchor_windows),
        # Backward-compatible field plus explicit cache diagnostics.
        "text_map_build_seconds": resolver_diag.get("prepare_seconds", 0.0),
        "text_map_cache": resolver_diag,
        "vector": vector_diag,
        "semantic_k": semantic_k,
        "semantic_page_quality_penalty_in_fusion": mode in {"hybrid", "auto", "consensus"},
        "keyword_page_cap": keyword_page_cap,
        "keyword_block_cap": keyword_block_cap,
        "exact_candidate_cap": exact_candidate_cap,
        "hybrid_keyword_weight": keyword_weight if mode in {"hybrid", "consensus"} else None,
        "auto_params": asdict(auto_params) if mode in {"auto", "consensus"} else None,
        "consensus": {
            "rrf_k": defaults.consensus_rrf_k,
            "weights": {**defaults.consensus_weights, "anchor": 1.25},
            "agreement_definition": (
                "agreement_count 仍只统计 exact/keyword/vector 三条基础通道；"
                "anchor 是 strict exact 落空后的内部字面证据层，"
                "会作为独立排序证据参与 RRF。"
            ),
        } if mode == "consensus" else None,
        "elapsed_seconds": round(time.perf_counter() - started, 4),
    }
    if exact_truncated or anchor_truncated or keyword_truncated:
        warnings.append(
            "至少一个候选阶段达到显式上限；未进入候选范围不能解释为数据库中不存在。"
        )

    return {
        "mode": mode,
        "query": query,
        "source_status": source_status,
        "literal_evidence_found": literal_evidence_found,
        "strong_literal_evidence_found": strong_literal_evidence_found,
        "results": results,
        "diagnostics": diagnostics,
    }, warnings


def _locate_page(
    connection: sqlite3.Connection,
    *,
    page_id: int | None,
    volume_id: int | None,
    physical_page: int | None,
) -> tuple[int, int, int, str | None, str]:
    if page_id is not None:
        row = connection.execute(
            """
            SELECT p.page_id,p.volume_id,p.physical_page,p.printed_number,v.name
            FROM page p JOIN volume v ON v.volume_id=p.volume_id
            WHERE p.page_id=?
            """,
            (page_id,),
        ).fetchone()
    elif volume_id is not None and physical_page is not None:
        row = connection.execute(
            """
            SELECT p.page_id,p.volume_id,p.physical_page,p.printed_number,v.name
            FROM page p JOIN volume v ON v.volume_id=p.volume_id
            WHERE p.volume_id=? AND p.physical_page=?
            """,
            (volume_id, physical_page),
        ).fetchone()
    else:
        raise RetrievalError(
            "PAGE_LOCATOR_REQUIRED",
            "必须提供 page_id，或同时提供 volume_id 与 physical_page。",
        )
    if row is None:
        raise RetrievalError("PAGE_NOT_FOUND", "没有找到指定页面。")
    return int(row[0]), int(row[1]), int(row[2]), (str(row[3]) if row[3] is not None else None), str(row[4])


def _read_page_from_connection(
    connection: sqlite3.Connection,
    page_id: int,
    *,
    max_chars: int,
) -> dict[str, Any]:
    meta = connection.execute(
        """
        SELECT p.page_id,p.volume_id,p.physical_page,p.printed_number,v.name
        FROM page p JOIN volume v ON v.volume_id=p.volume_id
        WHERE p.page_id=?
        """,
        (page_id,),
    ).fetchone()
    if meta is None:
        raise RetrievalError("PAGE_NOT_FOUND", "没有找到指定页面。", {"page_id": page_id})
    blocks = []
    total_chars = 0
    truncated = False
    for block_id, seq, block_type, raw_text in connection.execute(
        """
        SELECT block_id,seq,COALESCE(type,''),text
        FROM block
        WHERE page_id=? AND text IS NOT NULL AND text<>''
        ORDER BY seq,block_id
        """,
        (page_id,),
    ):
        text = clean_text(str(raw_text or ""))
        if not text:
            continue
        remaining = max_chars - total_chars
        if remaining <= 0:
            truncated = True
            break
        if len(text) > remaining:
            text = text[:remaining]
            truncated = True
        blocks.append({
            "block_id": int(block_id),
            "seq": int(seq or 0),
            "type": str(block_type or ""),
            "text": text,
        })
        total_chars += len(text)
        if truncated:
            break
    return {
        "page_id": int(meta[0]),
        "volume_id": int(meta[1]),
        "physical_page": int(meta[2]),
        "printed_number": str(meta[3]) if meta[3] is not None else None,
        "volume": str(meta[4]),
        "blocks": blocks,
        "returned_chars": total_chars,
        "truncated": truncated,
    }


def read_page(
    database_path: Path,
    *,
    page_id: int | None,
    volume_id: int | None,
    physical_page: int | None,
    max_chars: int,
) -> dict[str, Any]:
    validate_base_schema(database_path)
    with closing(open_read_only_db(database_path)) as connection:
        located = _locate_page(
            connection,
            page_id=page_id,
            volume_id=volume_id,
            physical_page=physical_page,
        )
        return _read_page_from_connection(connection, located[0], max_chars=max_chars)


def read_context(
    database_path: Path,
    *,
    page_id: int | None,
    volume_id: int | None,
    physical_page: int | None,
    before: int,
    after: int,
    max_chars_per_page: int,
) -> dict[str, Any]:
    validate_base_schema(database_path)
    with closing(open_read_only_db(database_path)) as connection:
        anchor = _locate_page(
            connection,
            page_id=page_id,
            volume_id=volume_id,
            physical_page=physical_page,
        )
        anchor_page_id, anchor_volume_id, anchor_physical, _, _ = anchor
        rows = connection.execute(
            """
            SELECT page_id
            FROM page
            WHERE volume_id=? AND physical_page BETWEEN ? AND ?
            ORDER BY physical_page
            """,
            (
                anchor_volume_id,
                max(1, anchor_physical - before),
                anchor_physical + after,
            ),
        ).fetchall()
        pages = [
            _read_page_from_connection(connection, int(row[0]), max_chars=max_chars_per_page)
            for row in rows
        ]
    return {
        "anchor_page_id": anchor_page_id,
        "anchor_volume_id": anchor_volume_id,
        "anchor_physical_page": anchor_physical,
        "before": before,
        "after": after,
        "pages": pages,
        "any_truncated": any(bool(page["truncated"]) for page in pages),
    }
