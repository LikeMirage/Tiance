from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SHELL_ROOT = Path(__file__).resolve().parents[1]
if str(SHELL_ROOT) not in sys.path:
    sys.path.insert(0, str(SHELL_ROOT))

from app import system_metrics


class _ProcessError(Exception):
    pass


class _FakeProcess:
    def __init__(
        self,
        pid: int,
        *,
        created_at: float,
        cpu_percent: float,
        memory_bytes: int,
        name: str,
        cwd: Path,
    ) -> None:
        self.pid = pid
        self._created_at = created_at
        self._cpu_percent = cpu_percent
        self._memory_bytes = memory_bytes
        self._name = name
        self._children: list[_FakeProcess] = []
        self.info = {
            "pid": pid,
            "name": name,
            "exe": None,
            "cwd": str(cwd),
            "cmdline": [],
            "create_time": created_at,
        }

    def children(self, *, recursive: bool) -> list[_FakeProcess]:
        assert recursive is True
        return list(self._children)

    def cpu_percent(self, *, interval: None) -> float:
        assert interval is None
        return self._cpu_percent

    def create_time(self) -> float:
        return self._created_at

    def memory_info(self) -> SimpleNamespace:
        return SimpleNamespace(rss=self._memory_bytes)

    def name(self) -> str:
        return self._name


class _FakePsutil:
    AccessDenied = _ProcessError
    NoSuchProcess = _ProcessError
    ZombieProcess = _ProcessError

    def __init__(self, current_process: _FakeProcess) -> None:
        self.current_process = current_process

    def Process(self, pid: int) -> _FakeProcess:
        if pid != self.current_process.pid:
            raise self.NoSuchProcess()
        return self.current_process

    def cpu_count(self) -> int:
        return 4

    def cpu_percent(self, *, interval: None) -> float:
        assert interval is None
        return 42.5

    def virtual_memory(self) -> SimpleNamespace:
        return SimpleNamespace(
            available=6_000,
            total=10_000,
            used=4_000,
            percent=40.0,
        )

    def process_iter(self, _attrs: list[str]):
        raise AssertionError("System metrics must not scan all system processes.")


class SystemMetricsSamplerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project_root = Path("C:/Tiance-metrics-test").resolve()
        self.shell = _FakeProcess(
            100,
            created_at=1.0,
            cpu_percent=8.0,
            memory_bytes=100,
            name="shell",
            cwd=self.project_root / "3_PyWebView",
        )
        self.backend = _FakeProcess(
            101,
            created_at=2.0,
            cpu_percent=12.0,
            memory_bytes=300,
            name="backend",
            cwd=self.project_root / "1_PythonServer",
        )
        self.shell._children = [self.backend]
        self.fake_psutil = _FakePsutil(self.shell)

    def _sampler(self) -> system_metrics.SystemMetricsSampler:
        sampler = system_metrics.SystemMetricsSampler()
        sampler._current_pid = self.shell.pid
        return sampler

    def test_snapshot_only_uses_shell_process_tree(self) -> None:
        with patch.object(system_metrics, "psutil", self.fake_psutil):
            snapshot = self._sampler().snapshot()

        self.assertEqual(
            snapshot["app"],
            {"cpuPercent": 5.0, "memoryBytes": 400, "processCount": 2},
        )
        self.assertEqual(snapshot["system"]["cpuPercent"], 42.5)
        self.assertEqual([item["pid"] for item in snapshot["processes"]], [101, 100])

    def test_process_outside_shell_tree_is_not_included(self) -> None:
        external_process = _FakeProcess(
            200,
            created_at=3.0,
            cpu_percent=20.0,
            memory_bytes=500,
            name="node",
            cwd=self.project_root / "2_ReactWeb",
        )

        with patch.object(system_metrics, "psutil", self.fake_psutil):
            snapshot = self._sampler().snapshot()

        self.assertEqual(snapshot["app"]["processCount"], 2)
        self.assertNotIn(external_process.pid, [item["pid"] for item in snapshot["processes"]])

    def test_reused_pid_replaces_stale_cached_process(self) -> None:
        with patch.object(system_metrics, "psutil", self.fake_psutil):
            sampler = self._sampler()
            sampler.snapshot()
            replacement = _FakeProcess(
                101,
                created_at=9.0,
                cpu_percent=4.0,
                memory_bytes=700,
                name="replacement",
                cwd=self.project_root / "1_PythonServer",
            )
            self.shell._children = [replacement]
            snapshot = sampler.snapshot()

        process = next(item for item in snapshot["processes"] if item["pid"] == 101)
        self.assertEqual(process["name"], "replacement")
        self.assertEqual(process["memoryBytes"], 700)


if __name__ == "__main__":
    unittest.main()
