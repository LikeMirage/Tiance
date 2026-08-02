from __future__ import annotations

from typing import Any

from process_repository import (
    ProcessRepository,
    ProcessRepositoryError,
    default_execution_root,
)
from process_pruning import prune_process_records
from tiance_runtime import run_tool


OPERATIONS = frozenset({"list", "get", "read_logs", "stop", "cleanup", "prune"})
LOG_STREAMS = frozenset({"both", "stdout", "stderr"})


class ToolError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        operation = _read_choice(payload.get("operation"), OPERATIONS, "operation")
        repository = ProcessRepository(default_execution_root())
        if operation == "list":
            return _list_processes(repository, payload)
        if operation == "prune":
            older_than_seconds = _read_int(
                payload.get("older_than_seconds"),
                default=60,
                minimum=10,
                maximum=None,
                field_name="older_than_seconds",
            )
            dry_run = _read_bool(payload.get("dry_run"), default=False)
            data = prune_process_records(
                repository,
                older_than_seconds=older_than_seconds,
                dry_run=dry_run,
            )
            warnings = (
                [f"{data['failed_count']} 条记录清理失败，详情见 failed。"]
                if data["failed_count"]
                else []
            )
            summary = (
                f"找到 {data['candidate_count']} 条可安全清理的记录，未执行删除。"
                if dry_run
                else f"已安全清理 {data['removed_count']} 条后台进程记录。"
            )
            return _success(summary, data, warnings)

        execution_id = _read_execution_id(payload.get("execution_id"))
        if operation == "get":
            snapshot = repository.get_process(execution_id)
            return _success("已读取 Python 后台进程状态。", snapshot.data)
        if operation == "read_logs":
            stream = _read_choice(payload.get("stream", "both"), LOG_STREAMS, "stream")
            tail_chars = _read_int(
                payload.get("tail_chars"),
                default=20000,
                minimum=1000,
                maximum=200000,
                field_name="tail_chars",
            )
            data = repository.read_logs(
                execution_id,
                stream=stream,
                tail_chars=tail_chars,
            )
            return _success("已读取 Python 后台进程最新状态和日志。", data)
        if operation == "stop":
            timeout_seconds = _read_int(
                payload.get("timeout_seconds"),
                default=10,
                minimum=1,
                maximum=60,
                field_name="timeout_seconds",
            )
            before = repository.get_process(execution_id)
            snapshot = repository.request_stop(
                execution_id,
                timeout_seconds=timeout_seconds,
            )
            summary = (
                "Python 后台进程此前已经结束。"
                if before.state == snapshot.state and before.active is False
                else "Python 后台进程已结束。"
            )
            return _success(summary, snapshot.data)

        removed_directory = repository.cleanup(execution_id)
        return _success(
            "已清理 Python 后台进程记录。",
            {
                "execution_id": execution_id,
                "removed_execution_directory": str(removed_directory),
            },
        )
    except ToolError as exc:
        return _failure(exc.code, exc.message, exc.details)
    except ProcessRepositoryError as exc:
        return _failure(exc.code, exc.message, exc.details)


def _list_processes(
    repository: ProcessRepository,
    payload: dict[str, Any],
) -> dict[str, Any]:
    offset = _read_int(
        payload.get("offset"),
        default=0,
        minimum=0,
        maximum=2_147_483_647,
        field_name="offset",
    )
    limit = _read_int(
        payload.get("limit"),
        default=100,
        minimum=1,
        maximum=500,
        field_name="limit",
    )
    snapshots, total, skipped = repository.list_processes(limit=limit, offset=offset)
    warnings = [f"跳过 {skipped} 条损坏或无效的进程记录。"] if skipped else []
    return _success(
        f"找到 {total} 条 Python 后台进程记录，本次返回 {len(snapshots)} 条。",
        {
            "processes": [snapshot.data for snapshot in snapshots],
            "offset": offset,
            "limit": limit,
            "total": total,
            "returned": len(snapshots),
            "has_more": offset + len(snapshots) < total,
            "execution_root": str(repository.execution_root),
        },
        warnings,
    )


def _read_execution_id(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ToolError("INVALID_ARGUMENT", "当前操作必须提供 execution_id。")
    return value


def _read_choice(value: Any, choices: frozenset[str], field_name: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ToolError(
            "INVALID_ARGUMENT",
            f"{field_name} 必须是：{', '.join(sorted(choices))}。",
        )
    return value


def _read_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ToolError("INVALID_ARGUMENT", "dry_run 必须是布尔值。")
    return value


def _read_int(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int | None,
    field_name: str,
) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError("INVALID_ARGUMENT", f"{field_name} 必须是整数。")
    if value < minimum or (maximum is not None and value > maximum):
        range_text = (
            f"{minimum} 到 {maximum}"
            if maximum is not None
            else f"不小于 {minimum}"
        )
        raise ToolError(
            "INVALID_ARGUMENT",
            f"{field_name} 必须{range_text}。",
        )
    return value


def _success(
    summary: str,
    data: dict[str, object],
    warnings: list[str] | None = None,
) -> dict[str, object]:
    return {"ok": True, "summary": summary, "data": data, "warnings": warnings or []}


def _failure(
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "ok": False,
        "error": f"{code}: {message}",
        "error_info": {"code": code, "message": message, "details": details or {}},
        "warnings": [],
    }


if __name__ == "__main__":
    run_tool(run)
