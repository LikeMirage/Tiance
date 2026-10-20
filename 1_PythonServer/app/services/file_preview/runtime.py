"""Bounded process lifetime, disconnect cancellation and shutdown participation."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from fastapi import Request

from app.core.errors import AppError
from app.core.shutdown_tasks import shutdown_tasks
from . import policy

_slots = asyncio.Semaphore(policy.MAX_PROCESSES)


def validate_asset_version(path: str | Path, expected: str | None) -> None:
    if expected is None:
        return
    try:
        policy.require_version(Path(path), expected)
    except ValueError as error:
        raise AppError(str(error), code="preview_file_changed", status_code=409) from error


async def _watch_disconnect(request: Request) -> None:
    while True:
        if await request.is_disconnected():
            return
        await asyncio.sleep(0.1)


async def _compute(path: Path, operation: str, arguments: dict) -> dict:
    try:
        await asyncio.wait_for(_slots.acquire(), timeout=policy.QUEUE_SECONDS)
    except TimeoutError:
        raise AppError("预览任务排队超过 30 秒，请稍后重试。", code="preview_queue_timeout", status_code=503) from None
    try:
        with tempfile.TemporaryDirectory(prefix="tiance-preview-") as directory:
            root = Path(directory)
            request_path, result_path = root / "request.json", root / "result.json"
            request_path.write_text(json.dumps({
                **arguments, "operation": operation, "path": str(path),
                "module_paths": [str(Path(p).resolve()) for p in sys.path if p and Path(p).is_dir()],
            }), encoding="utf-8")
            process = subprocess.Popen(
                [sys.executable, str(Path(__file__).with_name("worker.py")), str(request_path), str(result_path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                deadline = time.monotonic() + policy.PROCESS_SECONDS
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        raise AppError("预览处理超过 30 秒，已终止。可用默认应用打开。", code="preview_timeout", status_code=422)
                    await asyncio.sleep(0.05)
                if process.returncode != 0 or not result_path.is_file():
                    raise AppError("文件预览进程异常退出。", code="preview_worker_failed", status_code=422)
                if result_path.stat().st_size > policy.MAX_RESULT_BYTES:
                    raise AppError("预览输出超过资源预算。", code="preview_result_limit", status_code=422)
                result = json.loads(await asyncio.to_thread(result_path.read_text, encoding="utf-8"))
                if "error" in result:
                    raise AppError(result["error"], code=result.get("code", "preview_failed"),
                                   status_code=result.get("status_code", 422))
                return result
            finally:
                if process.poll() is None:
                    process.kill()
                # kill is immediate; reap before deleting its temporary directory.
                await asyncio.to_thread(process.wait)
    finally:
        _slots.release()


@shutdown_tasks.request
async def preview_file(request: Request, path: str | Path, operation: str = "inspect", **arguments) -> dict:
    worker = asyncio.create_task(_compute(Path(path), operation, arguments))
    disconnected = asyncio.create_task(_watch_disconnect(request))
    try:
        done, _ = await asyncio.wait((worker, disconnected), return_when=asyncio.FIRST_COMPLETED)
        if worker in done:
            return worker.result()
        raise AppError("预览请求已取消。", code="preview_cancelled", status_code=499)
    finally:
        disconnected.cancel()
        worker.cancel()
        await asyncio.gather(worker, disconnected, return_exceptions=True)
