from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import os
from typing import Any

try:
    import psutil
except ImportError:  # pragma: no cover - runtime dependency guard
    psutil = None  # type: ignore[assignment]


@dataclass(frozen=True)
class _TrackedProcess:
    process: Any
    created_at: float


class SystemMetricsSampler:
    def __init__(self) -> None:
        self._current_pid = os.getpid()
        self._tracked_processes: dict[int, _TrackedProcess] = {}

    def snapshot(self) -> dict[str, Any]:
        if psutil is None:
            return {
                "available": False,
                "reason": "psutil_missing",
                "sampledAt": _utc_now(),
            }

        cpu_count = max(int(psutil.cpu_count() or 1), 1)
        system_memory = psutil.virtual_memory()
        self._refresh_current_process_tree()
        app_processes = self._sample_tracked_processes(cpu_count)
        app_cpu_percent = round(sum(item["cpuPercent"] for item in app_processes), 1)
        app_memory_bytes = sum(int(item["memoryBytes"]) for item in app_processes)

        return {
            "available": True,
            "sampledAt": _utc_now(),
            "app": {
                "cpuPercent": app_cpu_percent,
                "memoryBytes": app_memory_bytes,
                "processCount": len(app_processes),
            },
            "system": {
                "cpuPercent": round(float(psutil.cpu_percent(interval=None)), 1),
                "memoryAvailableBytes": int(system_memory.available),
                "memoryTotalBytes": int(system_memory.total),
                "memoryUsedBytes": int(system_memory.used),
                "memoryPercent": round(float(system_memory.percent), 1),
            },
            "processes": sorted(
                app_processes,
                key=lambda item: int(item["memoryBytes"]),
                reverse=True,
            )[:8],
        }

    def _refresh_current_process_tree(self) -> None:
        try:
            current_process = psutil.Process(self._current_pid)
            self._remember_process(current_process)
            children = current_process.children(recursive=True)
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            return

        for child in children:
            self._remember_process(child)

    def _remember_process(self, process: Any) -> None:
        try:
            pid = int(process.pid)
            process_created_at = float(process.create_time())
        except (
            psutil.AccessDenied,
            psutil.NoSuchProcess,
            psutil.ZombieProcess,
            TypeError,
            ValueError,
        ):
            return

        tracked_process = _TrackedProcess(process=process, created_at=process_created_at)
        existing = self._tracked_processes.get(pid)
        if existing is None or existing.created_at != process_created_at:
            self._tracked_processes[pid] = tracked_process

    def _sample_tracked_processes(self, cpu_count: int) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for pid, tracked in tuple(self._tracked_processes.items()):
            process = tracked.process
            try:
                if float(process.create_time()) != tracked.created_at:
                    self._forget_process(pid, tracked)
                    continue
                cpu_percent = round(max(float(process.cpu_percent(interval=None)), 0.0) / cpu_count, 1)
                memory_bytes = int(process.memory_info().rss)
                result.append({
                    "pid": pid,
                    "name": str(process.name() or "process"),
                    "cpuPercent": cpu_percent,
                    "memoryBytes": memory_bytes,
                })
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                self._forget_process(pid, tracked)

        return result

    def _forget_process(self, pid: int, tracked: _TrackedProcess) -> None:
        if self._tracked_processes.get(pid) is tracked:
            self._tracked_processes.pop(pid, None)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
