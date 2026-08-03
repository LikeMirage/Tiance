from __future__ import annotations

from pathlib import Path
from typing import Any

from tiance_runtime import run_tool

from contracts import (
    DEFAULT_DATABASE_PATH,
    ToolError,
    read_bool,
    read_int,
    read_string_list,
    relative_path,
    resolve_inside_workspace,
    workspace_root,
)
from file_scanner import ScanConfig
from index_store import (
    check_changes,
    connect,
    database_status,
    load_config,
    synchronize,
)
from search_engine import search_index


OPERATIONS = {"index", "update", "search", "check_changes", "status", "rebuild", "delete_index"}
SEARCH_MODES = {"simple", "all", "any", "phrase", "raw"}


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        root = workspace_root()
        operation = str(payload.get("operation") or "search").strip().lower()
        if operation not in OPERATIONS:
            raise ToolError("INVALID_OPERATION", "不支持的操作。", {"operation": operation})
        database_path = resolve_inside_workspace(
            payload.get("database_path"),
            root,
            field="database_path",
            default=DEFAULT_DATABASE_PATH,
        )

        if operation == "delete_index":
            deleted = _delete_database(database_path)
            return _ok(operation, root, database_path, "全文索引已删除。" if deleted else "全文索引不存在。", {"deleted": deleted})

        if operation == "status":
            status = database_status(database_path)
            if status["exists"] and read_bool(payload.get("check_stale"), False):
                config, source_root = _existing_config(database_path, root, payload)
                status["changes"] = check_changes(
                    database_path,
                    root,
                    source_root,
                    config,
                    verification=_verification(payload),
                )
            return _ok(operation, root, database_path, "已读取全文索引状态。", status)

        if operation in {"index", "update", "rebuild"}:
            config, source_root = _write_config(database_path, root, payload, rebuild=operation == "rebuild")
            result = synchronize(
                database_path,
                root,
                source_root,
                config,
                rebuild=operation == "rebuild",
            )
            summary = (
                f"全文索引已更新：新增 {result['indexed']}，修改 {result['updated']}，"
                f"删除 {result['deleted']}，未变 {result['unchanged']}。"
            )
            warnings = [f"{item['path']}：{item['reason']}" for item in result.pop("warnings", [])]
            return _ok(operation, root, database_path, summary, result, warnings=warnings)

        _require_database(database_path)
        config, source_root = _existing_config(database_path, root, payload)
        if operation == "check_changes":
            result = check_changes(
                database_path,
                root,
                source_root,
                config,
                verification=_verification(payload),
            )
            change_type = str(payload.get("change_type") or "all").strip().lower()
            if change_type != "all":
                allowed = {"new", "modified", "deleted", "unreadable"}
                if change_type not in allowed:
                    raise ToolError("INVALID_CHANGE_TYPE", "不支持的变化类型。", {"change_type": change_type})
                result["changes"] = [item for item in result["changes"] if item["state"] == change_type]
            return _ok(operation, root, database_path, "索引已过期。" if result["stale"] else "索引仍然有效。", result)

        query = str(payload.get("query") or "").strip()
        if not query:
            raise ToolError("QUERY_REQUIRED", "search 操作必须提供非空 query。")
        mode = str(payload.get("mode") or "simple").strip().lower()
        if mode not in SEARCH_MODES:
            raise ToolError("INVALID_SEARCH_MODE", "不支持的检索模式。", {"mode": mode})
        result = search_index(
            database_path,
            query,
            mode=mode,
            path_prefix=str(payload.get("path_prefix") or "").strip(),
            extensions=read_string_list(payload.get("extensions"), maximum=50),
            limit=read_int(payload.get("limit"), 20, 1, 100),
            offset=read_int(payload.get("offset"), 0, 0, 100_000),
            context_chars=read_int(payload.get("context_chars"), 160, 40, 1000),
        )
        if read_bool(payload.get("check_stale"), False):
            result["changes"] = check_changes(
                database_path,
                root,
                source_root,
                config,
                verification=_verification(payload),
            )
        return _ok(operation, root, database_path, f"找到 {result['count']} 条全文检索结果。", result)
    except ToolError as exc:
        return _fail(exc.code, exc.message, exc.details)
    except ValueError as exc:
        return _fail("INVALID_INPUT", str(exc))
    except Exception as exc:
        return _fail("TOOL_FAILED", str(exc) or exc.__class__.__name__)


def _write_config(database_path: Path, root: Path, payload: dict[str, Any], *, rebuild: bool) -> tuple[ScanConfig, Path]:
    existing: ScanConfig | None = None
    if database_path.is_file() and not rebuild:
        connection = connect(database_path)
        try:
            existing = load_config(connection)
        finally:
            connection.close()
    source_value = payload.get("source_path")
    source_relative = str(source_value or (existing.source_path if existing else ".")).strip() or "."
    source_root = resolve_inside_workspace(source_relative, root, field="source_path", default=".")
    if not source_root.exists():
        raise ToolError("SOURCE_NOT_FOUND", "索引来源路径不存在。", {"source_path": str(source_root)})
    config = ScanConfig(
        source_path=relative_path(source_root, root) or ".",
        max_file_bytes=read_int(
            payload.get("max_file_bytes"),
            existing.max_file_bytes if existing else 5 * 1024 * 1024,
            1024,
            100 * 1024 * 1024,
        ),
        include_globs=(
            read_string_list(payload.get("include_globs"))
            if "include_globs" in payload
            else existing.include_globs if existing else ()
        ),
        exclude_globs=(
            read_string_list(payload.get("exclude_globs"))
            if "exclude_globs" in payload
            else existing.exclude_globs if existing else ()
        ),
    )
    if existing is not None and config.source_path != existing.source_path:
        raise ToolError(
            "SOURCE_CHANGED",
            "现有数据库属于另一个来源路径；请使用 rebuild 重建，或指定其他 database_path。",
            {"indexed_source": existing.source_path, "requested_source": config.source_path},
        )
    return config, source_root


def _existing_config(database_path: Path, root: Path, payload: dict[str, Any]) -> tuple[ScanConfig, Path]:
    connection = connect(database_path)
    try:
        config = load_config(connection)
    finally:
        connection.close()
    if config is None:
        raise ToolError("INDEX_CONFIG_MISSING", "索引缺少来源配置，请执行 rebuild。")
    requested_source = str(payload.get("source_path") or config.source_path).strip() or config.source_path
    source_root = resolve_inside_workspace(requested_source, root, field="source_path", default=config.source_path)
    if relative_path(source_root, root) != config.source_path:
        raise ToolError(
            "SOURCE_MISMATCH",
            "指定路径与这个索引数据库的来源不一致。",
            {"indexed_source": config.source_path, "requested_source": relative_path(source_root, root)},
        )
    return config, source_root


def _verification(payload: dict[str, Any]) -> str:
    value = str(payload.get("verification") or "quick").strip().lower()
    if value not in {"quick", "hash"}:
        raise ToolError("INVALID_VERIFICATION", "verification 只支持 quick 或 hash。")
    return value


def _require_database(database_path: Path) -> None:
    if not database_path.is_file():
        raise ToolError("INDEX_NOT_FOUND", "全文索引不存在，请先执行 index。", {"database_path": str(database_path)})


def _delete_database(database_path: Path) -> bool:
    deleted = False
    for path in (database_path, Path(f"{database_path}-wal"), Path(f"{database_path}-shm")):
        if path.is_file():
            path.unlink()
            deleted = True
    return deleted


def _ok(
    operation: str,
    root: Path,
    database_path: Path,
    summary: str,
    result: dict[str, Any],
    *,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "summary": summary,
        "data": {
            "operation": operation,
            "workspace_root": str(root),
            "database_path": relative_path(database_path, root),
            **result,
        },
        "warnings": warnings or [],
    }


def _fail(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "summary": message,
        "error": message,
        "error_info": {"code": code, "details": details or {}},
        "warnings": [],
    }


if __name__ == "__main__":
    run_tool(run)
