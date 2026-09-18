from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path
from typing import Any

from tiance_runtime import run_tool

from config_loader import AutoParams, ConfigError, load_tool_config
from retrieval import (
    RetrievalError,
    inspect_database,
    read_context,
    read_page,
    search_database,
)


OPERATIONS = {"inspect", "search", "read_page", "read_context"}
SEARCH_MODES = {"exact", "keyword", "vector", "hybrid", "auto", "consensus"}
VECTOR_MODES = {"vector", "hybrid", "auto", "consensus"}


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def workspace_root() -> Path:
    raw = os.environ.get("TIANCE_WORKSPACE_ROOT") or os.environ.get("WORKSPACE_ROOT") or os.getcwd()
    return Path(raw).expanduser().resolve(strict=False)


def resolve_database_path(value: Any, root: Path) -> Path:
    raw = str(value or "马恩全集.db").strip() or "马恩全集.db"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ToolError(
            "DATABASE_OUTSIDE_WORKSPACE",
            "database_path 必须位于当前项目工作区内。",
            {"database_path": str(path), "workspace_root": str(root)},
        ) from exc
    if not path.is_file():
        raise ToolError(
            "DATABASE_NOT_FOUND",
            "数据库文件不存在。",
            {"database_path": str(path)},
        )
    return path


def relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def read_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, result))


def read_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, result))


def read_int_tuple(value: Any, maximum: int = 500) -> tuple[int, ...] | None:
    if not isinstance(value, list):
        return None
    result: list[int] = []
    for item in value[:maximum]:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in result:
            result.append(number)
    return tuple(result) or None


def read_string_tuple(value: Any, maximum: int = 50) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    result: list[str] = []
    for item in value[:maximum]:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return tuple(result) or None


def merged_auto_params(value: Any, defaults: AutoParams) -> AutoParams:
    payload = value if isinstance(value, dict) else {}
    return AutoParams(
        bias=read_float(payload.get("bias"), defaults.bias, -10.0, 10.0),
        length_ratio_coefficient=read_float(
            payload.get("length_ratio_coefficient"),
            defaults.length_ratio_coefficient,
            -10.0,
            10.0,
        ),
        lexical_confidence_coefficient=read_float(
            payload.get("lexical_confidence_coefficient"),
            defaults.lexical_confidence_coefficient,
            -10.0,
            10.0,
        ),
        semantic_margin_coefficient=read_float(
            payload.get("semantic_margin_coefficient"),
            defaults.semantic_margin_coefficient,
            -20.0,
            20.0,
        ),
    )


def ok(summary: str, data: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    return {
        "ok": True,
        "summary": summary,
        "data": data,
        "warnings": warnings or [],
    }


def fail(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    safe_details = details or {}
    error_text = f"{code}: {message}"
    config_path = safe_details.get("config_path")
    fields = safe_details.get("fields")
    parse_error = safe_details.get("parse_error")
    if config_path:
        error_text += f"\n配置文件：{config_path}"
    if fields:
        error_text += "\n需检查字段：" + ", ".join(str(item) for item in fields)
    if parse_error:
        error_text += f"\nJSON错误：{parse_error}"
    if safe_details.get("ai_instruction"):
        error_text += f"\nAI操作：{safe_details['ai_instruction']}"
    return {
        "ok": False,
        "summary": message,
        "error": error_text,
        "error_info": {
            "code": code,
            "message": message,
            "details": safe_details,
        },
        "warnings": [],
    }


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        if not isinstance(payload, dict):
            raise ToolError("INVALID_INPUT", "工具输入必须是 JSON 对象。")

        root = workspace_root()
        operation = str(payload.get("operation") or "search").strip().lower()
        if operation not in OPERATIONS:
            raise ToolError("INVALID_OPERATION", "不支持的 operation。", {"operation": operation})

        database_path = resolve_database_path(payload.get("database_path"), root)
        database_label = relative_path(database_path, root)

        if operation == "inspect":
            data, warnings = inspect_database(database_path)
            return ok(
                "已只读检查结构化数据库。",
                {
                    "operation": operation,
                    "database_path": database_label,
                    **data,
                },
                warnings,
            )

        if operation == "read_page":
            page = read_page(
                database_path,
                page_id=read_int(payload.get("page_id"), 0, 0, 2_000_000_000) or None,
                volume_id=read_int(payload.get("volume_id"), 0, 0, 2_000_000_000) or None,
                physical_page=read_int(payload.get("physical_page"), 0, 0, 2_000_000_000) or None,
                max_chars=read_int(payload.get("max_chars_per_page"), 20000, 500, 100000),
            )
            warnings = ["该页达到 max_chars_per_page，返回内容已显式截断。"] if page["truncated"] else []
            return ok(
                f"已读取 page_id={page['page_id']}。",
                {
                    "operation": operation,
                    "database_path": database_label,
                    "page": page,
                },
                warnings,
            )

        if operation == "read_context":
            data = read_context(
                database_path,
                page_id=read_int(payload.get("page_id"), 0, 0, 2_000_000_000) or None,
                volume_id=read_int(payload.get("volume_id"), 0, 0, 2_000_000_000) or None,
                physical_page=read_int(payload.get("physical_page"), 0, 0, 2_000_000_000) or None,
                before=read_int(payload.get("before"), 2, 0, 20),
                after=read_int(payload.get("after"), 2, 0, 20),
                max_chars_per_page=read_int(payload.get("max_chars_per_page"), 20000, 500, 100000),
            )
            warnings = ["至少一页达到 max_chars_per_page，返回内容已显式截断。"] if data["any_truncated"] else []
            return ok(
                f"已读取锚点页及前后 {data['before']} / {data['after']} 页上下文。",
                {
                    "operation": operation,
                    "database_path": database_label,
                    **data,
                },
                warnings,
            )

        query = str(payload.get("query") or "").strip()
        if not query:
            raise ToolError("QUERY_REQUIRED", "search 操作必须提供非空 query。")
        mode = str(payload.get("mode") or "auto").strip().lower()
        if mode not in SEARCH_MODES:
            raise ToolError("INVALID_SEARCH_MODE", "不支持的 search mode。", {"mode": mode})

        config = load_tool_config(require_provider=mode in VECTOR_MODES)
        defaults = config.retrieval
        auto_params = merged_auto_params(payload.get("auto_params"), defaults.auto_params)
        keyword_weight = read_float(
            payload.get("keyword_weight"),
            defaults.hybrid_keyword_weight,
            0.0,
            1.0,
        )

        search_data, warnings = search_database(
            database_path,
            mode=mode,
            query=query,
            explicit_keywords=read_string_tuple(payload.get("keywords"), maximum=12),
            exact_query=(str(payload.get("exact_query") or "").strip() or None),
            volume_ids=read_int_tuple(payload.get("volume_ids"), maximum=500),
            block_types=read_string_tuple(payload.get("block_types"), maximum=50),
            limit=read_int(payload.get("limit"), 20, 1, 100),
            semantic_k=read_int(payload.get("semantic_k"), defaults.semantic_k, 1, 2000),
            exact_candidate_cap=read_int(
                payload.get("exact_candidate_cap"),
                defaults.exact_candidate_cap,
                100,
                20000,
            ),
            keyword_block_cap=read_int(
                payload.get("keyword_block_cap"),
                defaults.keyword_block_cap,
                100,
                50000,
            ),
            keyword_page_cap=read_int(
                payload.get("keyword_page_cap"),
                defaults.keyword_page_cap,
                10,
                5000,
            ),
            keyword_weight=keyword_weight,
            auto_params=auto_params,
            provider=config.provider if mode in VECTOR_MODES else None,
            defaults=defaults,
            cache_root=root / ".Tiance" / "cache" / "structured-database-search",
        )
        return ok(
            f"{mode} 检索返回 {len(search_data['results'])} 条结果。",
            {
                "operation": operation,
                "database_path": database_label,
                **search_data,
            },
            warnings,
        )
    except ToolError as exc:
        return fail(exc.code, exc.message, exc.details)
    except ConfigError as exc:
        return fail(exc.code, exc.message, exc.details)
    except RetrievalError as exc:
        return fail(exc.code, exc.message, exc.details)
    except Exception as exc:
        return fail(
            "TOOL_FAILED",
            str(exc) or exc.__class__.__name__,
            {"error_type": type(exc).__name__},
        )


if __name__ == "__main__":
    run_tool(run)
