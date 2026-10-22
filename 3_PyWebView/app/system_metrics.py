from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import os
from threading import Lock
from time import monotonic
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
        self._lock = Lock()
        self._last_snapshot: dict[str, Any] | None = None
        self._last_sample_time = float("-inf")
        self._system_cpu_times: dict[str, float] | None = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            # Bridge calls can arrive on different threads or in quick succession.
            if self._last_snapshot is not None and monotonic() - self._last_sample_time < 5.0:
                return self._last_snapshot
            snapshot = self._collect_snapshot()
            self._last_snapshot = snapshot
            self._last_sample_time = monotonic()
            return snapshot

    def _collect_snapshot(self) -> dict[str, Any]:
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
        app_cpu_percent = (round(sum(item["cpuPercent"] for item in app_processes), 1)
                           if self._last_snapshot is not None else None)
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
                "cpuPercent": self._sample_system_cpu(),
                "memoryAvailableBytes": int(system_memory.available),
                "memoryTotalBytes": int(system_memory.total),
                "memoryUsedBytes": int(system_memory.used),
                "memoryPercent": round(float(system_memory.percent), 1),
            },
        }

    def _sample_system_cpu(self) -> float | None:
        # psutil.cpu_percent keeps a baseline per calling thread. pywebview uses
        # separate bridge threads, so retain raw CPU time baselines on the sampler.
        current = dict(psutil.cpu_times()._asdict())
        previous, self._system_cpu_times = self._system_cpu_times, current
        if previous is None:
            return None
        delta = {key: max(0.0, value - previous.get(key, value)) for key, value in current.items()}
        # guest times are included in user/nice; Windows interrupt/dpc in system.
        total = sum(value for key, value in delta.items() if key not in {"guest", "guest_nice", "interrupt", "dpc"})
        idle = delta.get("idle", 0.0) + delta.get("iowait", 0.0)
        return round(max(0.0, min(100.0, (total - idle) / total * 100)), 1) if total > 0 else None

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
