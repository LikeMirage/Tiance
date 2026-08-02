from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


TOOL_ROOT = Path(__file__).resolve().parents[1]
PROGRAM_ROOT = TOOL_ROOT / "program"
PROJECT_ROOT = Path(__file__).resolve().parents[6]
BACKEND_ROOT = PROJECT_ROOT / "1_PythonServer"
for path in (PROGRAM_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import main as tool_main  # noqa: E402
from candidate_environment import CandidateEnvironment  # noqa: E402
from package_environment import (  # noqa: E402
    EnvironmentError,
    RuntimePaths,
    resolve_active_site_packages,
)
from package_spec import InputError, parse_request  # noqa: E402


def _user_packages_root(temp_dir: str) -> Path:
    return Path(temp_dir) / "runtime" / "python-packages" / "user" / "py313"


class PipPackageManagerTests(unittest.TestCase):
    def test_manifest_and_schema_match_program_contract(self) -> None:
        manifest = json.loads((TOOL_ROOT / ".tool/tool.json").read_text(encoding="utf-8"))
        schema = json.loads((TOOL_ROOT / ".tool/input.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "pip_package_manager")
        self.assertEqual(manifest["runtime"]["type"], "python")
        self.assertEqual(set(schema["properties"]), {"operation", "packages", "index_url", "timeout_seconds"})
        self.assertEqual(
            set(schema["properties"]["operation"]["enum"]),
            {"check", "install", "list", "repair", "show", "uninstall"},
        )

    def test_health_operations_do_not_accept_package_arguments(self) -> None:
        self.assertEqual(parse_request({"operation": "check"}).packages, ())
        self.assertEqual(parse_request({"operation": "repair"}).packages, ())
        with self.assertRaises(InputError):
            parse_request({"operation": "repair", "packages": ["requests"]})

    def test_rejects_raw_pip_flags_and_credentialed_index(self) -> None:
        request = parse_request({"operation": "install", "packages": ["requests"]})
        self.assertEqual(request.index_url, "https://mirrors.aliyun.com/pypi/simple/")
        with self.assertRaises(InputError):
            parse_request({"operation": "install", "packages": ["--user"]})
        with self.assertRaises(InputError):
            parse_request(
                {
                    "operation": "install",
                    "packages": ["requests"],
                    "index_url": "https://user:secret@example.test/simple",
                }
            )

    def test_candidate_environment_commits_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = _user_packages_root(temp_dir)
            legacy = root / "site-packages"
            legacy.mkdir(parents=True)
            (legacy / "old.txt").write_text("old", encoding="utf-8")
            with CandidateEnvironment(root) as candidate:
                assert candidate.path is not None
                (candidate.path / "new.txt").write_text("new", encoding="utf-8")
                candidate.commit()
            active = resolve_active_site_packages(root)
            self.assertNotEqual(active, legacy)
            self.assertEqual((legacy / "old.txt").read_text(encoding="utf-8"), "old")
            self.assertFalse((legacy / "new.txt").exists())
            self.assertEqual((active / "old.txt").read_text(encoding="utf-8"), "old")
            self.assertEqual((active / "new.txt").read_text(encoding="utf-8"), "new")

    def test_active_environment_cannot_escape_user_package_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "active.json").write_text(
                json.dumps({"schema_version": 1, "site_packages": "../outside"}),
                encoding="utf-8",
            )
            with self.assertRaises(EnvironmentError) as raised:
                resolve_active_site_packages(root)
            self.assertEqual(raised.exception.code, "ACTIVE_ENVIRONMENT_INVALID")

    def test_active_runtime_lease_keeps_previous_generation_until_later_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = _user_packages_root(temp_dir)
            with CandidateEnvironment(root) as candidate:
                candidate.commit()
            first_active = resolve_active_site_packages(root).parent
            leases = root / "leases"
            leases.mkdir()
            lease = leases / "lease-test.json"
            lease.write_text("{}", encoding="utf-8")
            with CandidateEnvironment(root) as candidate:
                candidate.commit()
            self.assertTrue(first_active.is_dir())
            lease.unlink()
            with CandidateEnvironment(root) as candidate:
                candidate.commit()
            self.assertFalse(first_active.exists())

    def test_install_failure_does_not_change_active_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "site-packages"
            target.mkdir()
            marker = target / "active.txt"
            marker.write_text("unchanged", encoding="utf-8")
            paths = RuntimePaths(
                python_executable=Path(sys.executable),
                pip_runner=root / "run_pip.py",
                user_packages_root=root,
            )
            failed = subprocess.CompletedProcess(
                ["pip"],
                returncode=1,
                stdout="",
                stderr="failed",
            )
            with patch.object(tool_main, "resolve_runtime_paths", return_value=paths), patch.object(
                tool_main,
                "install_packages",
                return_value=failed,
            ):
                result = tool_main.run({"operation": "install", "packages": ["requests"]})
            self.assertFalse(result["ok"])
            self.assertEqual(marker.read_text(encoding="utf-8"), "unchanged")

if __name__ == "__main__":
    unittest.main()
