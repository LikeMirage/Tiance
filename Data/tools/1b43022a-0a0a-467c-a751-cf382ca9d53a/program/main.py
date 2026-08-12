from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import posixpath
from typing import Any

from result_store import (
    atomic_write_json,
    atomic_write_text,
    create_batch_directory,
    numbered_directory,
    relative_path,
    save_page_result,
    workspace_root,
)
from search_provider import (
    ENGINE_LABELS,
    SUPPORTED_ENGINES,
    SearchProviderError,
    search_web,
)
from webpage_reader import PageReadResult, read_page
from tiance_runtime import run_tool


MAX_QUERIES = 20
MAX_URLS = 100
DEFAULT_RESULTS_PER_QUERY = 10
MAX_RESULTS_PER_QUERY = 50
CONTENT_FETCH_WORKERS = 4
MAX_CONTENT_PAGES_PER_BATCH = 100


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        request = normalize_request(payload)
        root = workspace_root()
        batch_dir = create_batch_directory(root)
        manifest = {
            "schema_version": 1,
            "engine": request["engine"],
            "engine_label": ENGINE_LABELS[request["engine"]],
            "mode": request["mode"],
            "created_at": datetime.now().astimezone().isoformat(),
            "queries": [],
            "direct_urls": [],
            "warnings": [],
        }

        for query_index, query in enumerate(request["queries"], start=1):
            manifest["queries"].append(
                process_query(
                    query,
                    engine=request["engine"],
                    query_index=query_index,
                    max_results=request["max_results_per_query"],
                    mode=request["mode"],
                    batch_dir=batch_dir,
                    root=root,
                )
            )

        if request["urls"]:
            manifest["direct_urls"] = process_direct_urls(
                request["urls"],
                batch_dir=batch_dir,
                root=root,
            )

        manifest["warnings"] = collect_warnings(manifest)
        manifest["summary"] = summarize_manifest(manifest)
        manifest_path = batch_dir / "manifest.json"
        index_path = batch_dir / "index.md"
        atomic_write_json(manifest_path, manifest)
        atomic_write_text(
            index_path,
            render_batch_index(manifest, index_file=relative_path(index_path, root)),
        )
        data = build_response_data(manifest, batch_dir=batch_dir, root=root)
        if not any_success(manifest):
            return {
                "ok": False,
                "error": "ALL_ITEMS_FAILED: 本批次没有成功保存任何搜索结果或具体网址。",
                "error_info": {
                    "code": "ALL_ITEMS_FAILED",
                    "message": "本批次没有成功保存任何搜索结果或具体网址。",
                    "details": data,
                },
                "data": data,
                "warnings": manifest["warnings"],
            }
        return {
            "ok": True,
            "summary": manifest["summary"],
            "data": data,
            "warnings": manifest["warnings"],
        }
    except ToolError as exc:
        return fail(exc.code, exc.message, exc.details)
    except Exception as exc:
        return fail("UNEXPECTED_ERROR", str(exc) or exc.__class__.__name__)


def normalize_request(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ToolError("INVALID_ARGUMENT", "工具输入必须是 JSON 对象。")
    queries = normalize_string_list(payload.get("queries"), "queries", MAX_QUERIES)
    urls = normalize_string_list(payload.get("urls"), "urls", MAX_URLS)
    if not queries and not urls:
        raise ToolError("INVALID_ARGUMENT", "至少需要提供一个搜索内容 queries 或具体网址 urls。")
    mode = str(payload.get("mode") or "search").strip().casefold()
    if mode not in {"search", "content"}:
        raise ToolError("INVALID_ARGUMENT", "mode 只能是 search 或 content。")
    engine = str(payload.get("engine") or "baidu").strip().casefold()
    if engine not in SUPPORTED_ENGINES:
        raise ToolError(
            "INVALID_ENGINE",
            f"engine 只能是：{', '.join(SUPPORTED_ENGINES)}。",
        )
    max_results = read_int(
        payload.get("max_results_per_query"),
        DEFAULT_RESULTS_PER_QUERY,
        1,
        MAX_RESULTS_PER_QUERY,
        "max_results_per_query",
    )
    content_page_count = len(urls) + (len(queries) * max_results if mode == "content" else 0)
    if content_page_count > MAX_CONTENT_PAGES_PER_BATCH:
        raise ToolError(
            "BATCH_TOO_LARGE",
            f"单批最多读取 {MAX_CONTENT_PAGES_PER_BATCH} 个网页正文；当前请求需要读取 {content_page_count} 个。",
            {
                "maximum_content_pages": MAX_CONTENT_PAGES_PER_BATCH,
                "requested_content_pages": content_page_count,
            },
        )
    return {
        "queries": queries,
        "urls": urls,
        "mode": mode,
        "engine": engine,
        "max_results_per_query": max_results,
    }


def process_query(
    query: str,
    *,
    engine: str,
    query_index: int,
    max_results: int,
    mode: str,
    batch_dir: Path,
    root: Path,
) -> dict[str, Any]:
    queries_dir = batch_dir / "queries"
    query_dir = numbered_directory(queries_dir, query_index, query)
    query_record: dict[str, Any] = {
        "index": query_index,
        "query": query,
        "engine": engine,
        "engine_label": ENGINE_LABELS[engine],
        "mode": mode,
        "status": "completed",
        "result_count": 0,
        "saved_count": 0,
        "failed_count": 0,
        "snippet_character_count": 0,
        "content_character_count": 0,
        "results": [],
        "error_code": None,
        "error": None,
        "index_file": relative_path(query_dir / "index.md", root),
        "results_file": relative_path(query_dir / "results.json", root),
    }
    try:
        results = search_web(engine, query, max_results=max_results)
    except SearchProviderError as exc:
        query_record.update({"status": "failed", "error_code": exc.code, "error": exc.message})
        atomic_write_json(query_dir / "results.json", query_record)
        atomic_write_text(query_dir / "index.md", render_query_index(query_record))
        return query_record

    query_record["result_count"] = len(results)
    query_record["snippet_character_count"] = sum(len(item.get("snippet", "")) for item in results)
    if mode == "content":
        query_record["results"] = fetch_query_results(results, query_dir=query_dir, root=root)
    else:
        query_record["results"] = [
            {
                **item,
                "status": "search-result",
                "character_count": 0,
                "content_file": None,
                "metadata_file": None,
                "error_code": None,
                "error": None,
                "warnings": [],
            }
            for item in results
        ]
    query_record["saved_count"] = sum(
        1 for item in query_record["results"] if item["status"] in {"saved", "search-result"}
    )
    query_record["failed_count"] = sum(1 for item in query_record["results"] if item["status"] == "failed")
    query_record["content_character_count"] = sum(
        int(item.get("character_count") or 0) for item in query_record["results"]
    )
    atomic_write_json(query_dir / "results.json", query_record)
    atomic_write_text(query_dir / "index.md", render_query_index(query_record))
    return query_record


def fetch_query_results(results: list[dict[str, Any]], *, query_dir: Path, root: Path) -> list[dict[str, Any]]:
    fetched: dict[int, PageReadResult] = {}
    with ThreadPoolExecutor(max_workers=min(CONTENT_FETCH_WORKERS, len(results) or 1)) as executor:
        future_map = {executor.submit(read_page, item["url"]): index for index, item in enumerate(results)}
        for future in as_completed(future_map):
            index = future_map[future]
            try:
                fetched[index] = future.result()
            except Exception as exc:
                fetched[index] = unexpected_page_failure(results[index]["url"], exc)

    output: list[dict[str, Any]] = []
    result_root = query_dir / "results"
    for index, source in enumerate(results, start=1):
        folder = numbered_directory(result_root, index, source.get("title") or source.get("source") or "result")
        page = fetched[index - 1]
        metadata = save_page_result(folder, page, source=source)
        output.append(
            {
                **source,
                "status": metadata["status"],
                "character_count": metadata["character_count"],
                "byte_count": metadata["byte_count"],
                "final_url": metadata["final_url"],
                "content_file": relative_path(folder / metadata["content_file"], root) if metadata["content_file"] else None,
                "binary_file": relative_path(folder / metadata["binary_file"], root) if metadata["binary_file"] else None,
                "metadata_file": relative_path(folder / "metadata.json", root),
                "error_code": metadata["error_code"],
                "error": metadata["error"],
                "warnings": metadata["warnings"],
            }
        )
    return output


def process_direct_urls(urls: list[str], *, batch_dir: Path, root: Path) -> list[dict[str, Any]]:
    pages: dict[int, PageReadResult] = {}
    with ThreadPoolExecutor(max_workers=min(CONTENT_FETCH_WORKERS, len(urls) or 1)) as executor:
        future_map = {executor.submit(read_page, url): index for index, url in enumerate(urls)}
        for future in as_completed(future_map):
            index = future_map[future]
            try:
                pages[index] = future.result()
            except Exception as exc:
                pages[index] = unexpected_page_failure(urls[index], exc)

    output: list[dict[str, Any]] = []
    direct_root = batch_dir / "urls"
    for index, url in enumerate(urls, start=1):
        page = pages[index - 1]
        folder = numbered_directory(direct_root, index, page.title or page.final_url or url)
        metadata = save_page_result(folder, page, source={"kind": "direct-url"})
        output.append(
            {
                "index": index,
                "url": url,
                "final_url": metadata["final_url"],
                "title": metadata["title"],
                "status": metadata["status"],
                "character_count": metadata["character_count"],
                "byte_count": metadata["byte_count"],
                "content_file": relative_path(folder / metadata["content_file"], root) if metadata["content_file"] else None,
                "binary_file": relative_path(folder / metadata["binary_file"], root) if metadata["binary_file"] else None,
                "metadata_file": relative_path(folder / "metadata.json", root),
                "error_code": metadata["error_code"],
                "error": metadata["error"],
                "warnings": metadata["warnings"],
            }
        )
    return output


def build_response_data(manifest: dict[str, Any], *, batch_dir: Path, root: Path) -> dict[str, Any]:
    query_summaries = [
        {
            "query": item["query"],
            "engine": item["engine"],
            "engine_label": item["engine_label"],
            "status": item["status"],
            "result_count": item["result_count"],
            "saved_count": item["saved_count"],
            "failed_count": item["failed_count"],
            "snippet_character_count": item["snippet_character_count"],
            "content_character_count": item["content_character_count"],
            "content_character_counts": [result.get("character_count", 0) for result in item["results"]],
            "index_file": item["index_file"],
            "results_file": item["results_file"],
            "error_code": item["error_code"],
            "error": item["error"],
        }
        for item in manifest["queries"]
    ]
    direct_summaries = [
        {
            "url": item["url"],
            "status": item["status"],
            "character_count": item["character_count"],
            "content_file": item["content_file"],
            "binary_file": item["binary_file"],
            "metadata_file": item["metadata_file"],
            "error_code": item["error_code"],
            "error": item["error"],
        }
        for item in manifest["direct_urls"]
    ]
    return {
        "engine": manifest["engine"],
        "engine_label": manifest["engine_label"],
        "mode": manifest["mode"],
        "output_directory": relative_path(batch_dir, root),
        "index_file": relative_path(batch_dir / "index.md", root),
        "manifest_file": relative_path(batch_dir / "manifest.json", root),
        "query_count": len(manifest["queries"]),
        "direct_url_count": len(manifest["direct_urls"]),
        "result_count": sum(item["result_count"] for item in manifest["queries"]),
        "saved_count": total_saved(manifest),
        "failed_count": total_failed(manifest),
        "content_character_count": total_characters(manifest),
        "query_summaries": query_summaries,
        "direct_url_summaries": direct_summaries,
    }


def render_batch_index(manifest: dict[str, Any], *, index_file: str) -> str:
    lines = [
        "# 免费网络搜索批次",
        "",
        f"- 搜索引擎：{manifest['engine_label']}",
        f"- 模式：{manifest['mode']}",
        f"- 创建时间：{manifest['created_at']}",
        f"- 查询数：{len(manifest['queries'])}",
        f"- 具体网址数：{len(manifest['direct_urls'])}",
        f"- 搜索结果数：{sum(item['result_count'] for item in manifest['queries'])}",
        f"- 成功保存数：{total_saved(manifest)}",
        f"- 失败数：{total_failed(manifest)}",
        f"- 正文字符总数：{total_characters(manifest)}",
        "",
        "## 搜索查询",
        "",
        "| # | 查询 | 实际引擎 | 状态 | 结果 | 成功 | 失败 | 正文字符 | 索引 |",
        "|---:|---|---|---|---:|---:|---:|---:|---|",
    ]
    for item in manifest["queries"]:
        query_link = markdown_relative_link(item["index_file"], index_file)
        lines.append(
            f"| {item['index']} | {escape_table(item['query'])} | {item['engine_label']} | {item['status']} | {item['result_count']} | "
            f"{item['saved_count']} | {item['failed_count']} | {item['content_character_count']} | "
            f"[{query_link}]({query_link}) |"
        )
    if not manifest["queries"]:
        lines.append("| - | 未提交搜索查询 | - | - | 0 | 0 | 0 | 0 | - |")
    lines.extend(
        [
            "",
            "## 具体网址",
            "",
            "| # | 标题或网址 | 状态 | 字节 | 正文字符 | 内容文件 |",
            "|---:|---|---|---:|---:|---|",
        ]
    )
    for item in manifest["direct_urls"]:
        target = item["content_file"] or item["binary_file"] or item["metadata_file"]
        target_link = markdown_relative_link(target, index_file)
        label = item["title"] or item["url"]
        lines.append(
            f"| {item['index']} | {escape_table(label)} | {item['status']} | {item['byte_count']} | "
            f"{item['character_count']} | [{target_link}]({target_link}) |"
        )
    if not manifest["direct_urls"]:
        lines.append("| - | 未提交具体网址 | - | 0 | 0 | - |")
    if manifest["warnings"]:
        lines.extend(["", "## 警告", ""])
        lines.extend(f"- {warning}" for warning in manifest["warnings"])
    return "\n".join(lines).rstrip() + "\n"


def render_query_index(query: dict[str, Any]) -> str:
    lines = [
        f"# {query['query']}",
        "",
        f"- 搜索引擎：{query['engine_label']}",
        f"- 模式：{query['mode']}",
        f"- 状态：{query['status']}",
        f"- 结果数：{query['result_count']}",
        f"- 正文字符数：{query['content_character_count']}",
    ]
    if query["error"]:
        lines.extend(["", f"错误：{query['error_code']} - {query['error']}"])
    lines.extend(
        [
            "",
            "| # | 标题 | 来源 | 类型 | 摘要字符 | 正文字符 | 状态 | 文件 |",
            "|---:|---|---|---|---:|---:|---|---|",
        ]
    )
    for result in query["results"]:
        saved_target = result.get("content_file") or result.get("binary_file") or result.get("metadata_file")
        if saved_target:
            target = markdown_relative_link(saved_target, query["index_file"])
            link = f"[{target}]({target})"
        else:
            link = f"[原网页]({result['url']})"
        lines.append(
            f"| {result['rank']} | [{escape_table(result['title'])}]({result['url']}) | "
            f"{escape_table(result['source'])} | {result['result_type']} | {len(result.get('snippet', ''))} | "
            f"{result.get('character_count', 0)} | {result['status']} | {link} |"
        )
    if not query["results"]:
        lines.append("| - | 没有可用结果 | - | - | 0 | 0 | failed | - |")
    return "\n".join(lines).rstrip() + "\n"


def collect_warnings(manifest: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for query in manifest["queries"]:
        if query["error"]:
            warnings.append(f"查询“{query['query']}”失败：{query['error_code']} - {query['error']}")
        for result in query["results"]:
            prefix = f"查询“{query['query']}”第 {result['rank']} 条"
            if result.get("error"):
                warnings.append(f"{prefix}失败：{result['error_code']} - {result['error']}")
            warnings.extend(f"{prefix}：{item}" for item in result.get("warnings", []))
    for item in manifest["direct_urls"]:
        prefix = f"网址 {item['url']}"
        if item.get("error"):
            warnings.append(f"{prefix}失败：{item['error_code']} - {item['error']}")
        warnings.extend(f"{prefix}：{warning}" for warning in item.get("warnings", []))
    return warnings


def summarize_manifest(manifest: dict[str, Any]) -> str:
    return (
        f"免费网络搜索完成：{len(manifest['queries'])} 个查询、{len(manifest['direct_urls'])} 个具体网址，"
        f"发现 {sum(item['result_count'] for item in manifest['queries'])} 条搜索结果，"
        f"成功保存 {total_saved(manifest)} 项，失败 {total_failed(manifest)} 项，"
        f"正文共 {total_characters(manifest)} 个字符。"
    )


def total_saved(manifest: dict[str, Any]) -> int:
    return sum(item["saved_count"] for item in manifest["queries"]) + sum(
        1 for item in manifest["direct_urls"] if item["status"] == "saved"
    )


def total_failed(manifest: dict[str, Any]) -> int:
    query_failures = sum(1 for item in manifest["queries"] if item["status"] == "failed")
    result_failures = sum(item["failed_count"] for item in manifest["queries"])
    direct_failures = sum(1 for item in manifest["direct_urls"] if item["status"] == "failed")
    return query_failures + result_failures + direct_failures


def total_characters(manifest: dict[str, Any]) -> int:
    return sum(item["content_character_count"] for item in manifest["queries"]) + sum(
        int(item["character_count"] or 0) for item in manifest["direct_urls"]
    )


def any_success(manifest: dict[str, Any]) -> bool:
    return total_saved(manifest) > 0


def unexpected_page_failure(url: str, exc: Exception) -> PageReadResult:
    return PageReadResult(
        ok=False,
        requested_url=url,
        final_url="",
        title="",
        content_type="",
        status_code=None,
        content="",
        binary_content=None,
        binary_extension=None,
        byte_count=0,
        character_count=0,
        truncated=False,
        extraction_method=None,
        error_code="UNEXPECTED_PAGE_ERROR",
        error=str(exc) or exc.__class__.__name__,
        warnings=(),
    )


def normalize_string_list(value: Any, field: str, limit: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ToolError("INVALID_ARGUMENT", f"{field} 必须是字符串数组。")
    if not value:
        raise ToolError("INVALID_ARGUMENT", f"{field} 不能为空数组。")
    if len(value) > limit:
        raise ToolError("BATCH_TOO_LARGE", f"{field} 一次最多提交 {limit} 项，不会静默截断。")
    normalized: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value, start=1):
        if not isinstance(item, str) or not item.strip():
            raise ToolError("INVALID_ARGUMENT", f"{field} 第 {index} 项必须是非空字符串。")
        text = item.strip()
        key = text if field == "urls" else text.casefold()
        if key in seen:
            raise ToolError(
                "DUPLICATE_ARGUMENT",
                f"{field} 第 {index} 项与前面的输入重复：{text}",
            )
        seen.add(key)
        normalized.append(text)
    return normalized


def read_int(value: Any, default: int, minimum: int, maximum: int, field: str) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ToolError("INVALID_ARGUMENT", f"{field} 必须是整数。")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ToolError("INVALID_ARGUMENT", f"{field} 必须是整数。") from exc
    if parsed < minimum or parsed > maximum:
        raise ToolError("INVALID_ARGUMENT", f"{field} 必须在 {minimum} 到 {maximum} 之间。")
    return parsed


def escape_table(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def markdown_relative_link(target_file: str, source_file: str) -> str:
    source_directory = posixpath.dirname(source_file)
    return posixpath.relpath(target_file, start=source_directory or ".")


def fail(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "error": f"{code}: {message}",
        "error_info": {"code": code, "message": message, "details": details or {}},
        "warnings": [],
    }


if __name__ == "__main__":
    run_tool(run)
