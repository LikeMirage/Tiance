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
PROJECT_ROOT = Path(__file__).resolve().parents[4]
BACKEND_ROOT = PROJECT_ROOT / "1_PythonServer"
for path in (PROGRAM_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import main as tool_main  # noqa: E402
import package_operations  # noqa: E402
from candidate_environment import CandidateEnvironment  # noqa: E402
from package_environment import (  # noqa: E402
    EnvironmentError,
    RuntimePaths,
    resolve_active_site_packages,
)
from package_spec import InputError, parse_request  # noqa: E402
from package_target import resolve_package_target  # noqa: E402


def _tool_packages_root(temp_dir: str) -> Path:
    return Path(temp_dir) / "Data" / "tools" / "tool-id" / "dependencies" / "py313"


def _runtime_paths(temp_dir: str) -> RuntimePaths:
    root = Path(temp_dir)
    runtime_root = root / "Data" / "runtime"
    tools_root = root / "Data" / "tools"
    python_executable = runtime_root / "python" / "py313" / "python.exe"
    pip_runner = runtime_root / "python" / "run_pip.py"
    python_executable.parent.mkdir(parents=True)
    python_executable.touch()
    pip_runner.touch()
    return RuntimePaths(
        python_executable=python_executable,
        pip_runner=pip_runner,
        runtime_root=runtime_root,
        tools_root=tools_root,
    )


def _create_tool(
    tools_root: Path,
    *,
    folder_id: str,
    name: str,
    display_name: str,
    market_id: str | None = None,
) -> Path:
    tool_root = tools_root / folder_id
    (tool_root / ".tool").mkdir(parents=True)
    (tool_root / "program").mkdir()
    (tool_root / ".tool" / "tool.json").write_text(
        json.dumps({"name": name, "display_name": display_name}),
        encoding="utf-8",
    )
    (tool_root / "manifest.json").write_text(
        json.dumps({"id": market_id or name}),
        encoding="utf-8",
    )
    (tool_root / "program" / "requirements.txt").write_text("", encoding="utf-8")
    return tool_root


class PipPackageManagerTests(unittest.TestCase):
    def test_manifest_and_schema_match_program_contract(self) -> None:
        manifest = json.loads((TOOL_ROOT / ".tool/tool.json").read_text(encoding="utf-8"))
        schema = json.loads((TOOL_ROOT / ".tool/input.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "pip_package_manager")
        self.assertEqual(manifest["runtime"]["type"], "python")
        self.assertEqual(
            set(schema["properties"]),
            {"operation", "target_tool", "target_path", "packages", "index_url", "timeout_seconds"},
        )
        self.assertEqual(
            set(schema["properties"]["operation"]["enum"]),
            {"check", "install", "install_requirements", "list", "repair", "show", "uninstall"},
        )

    def test_health_operations_do_not_accept_package_arguments(self) -> None:
        self.assertEqual(parse_request({"operation": "check"}).packages, ())
        self.assertEqual(parse_request({"operation": "repair"}).packages, ())
        with self.assertRaises(InputError):
            parse_request({"operation": "repair", "packages": ["requests"]})

    def test_active_install_and_requirements_install_have_distinct_contracts(self) -> None:
        active = parse_request(
            {
                "operation": "install",
                "target_tool": "some-tool",
                "packages": ["requests"],
            }
        )
        declared = parse_request(
            {"operation": "install_requirements", "target_tool": "some-tool"}
        )
        self.assertEqual(active.packages, ("requests",))
        self.assertEqual(declared.packages, ())
        with self.assertRaises(InputError):
            parse_request(
                {
                    "operation": "install_requirements",
                    "target_path": "custom-packages",
                }
            )

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
            root = _tool_packages_root(temp_dir)
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

    def test_active_environment_cannot_escape_tool_package_root(self) -> None:
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
            root = _tool_packages_root(temp_dir)
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
            paths = _runtime_paths(temp_dir)
            tool_root = _create_tool(
                paths.tools_root,
                folder_id="tool-id",
                name="run_python_script",
                display_name="Python 脚本执行",
            )
            target = tool_root / "dependencies" / "py313" / "site-packages"
            target.mkdir(parents=True)
            marker = target / "active.txt"
            marker.write_text("unchanged", encoding="utf-8")
            failed = subprocess.CompletedProcess(
                ["pip"],
                returncode=1,
                stdout="",
                stderr="failed",
            )
            with patch.object(tool_main, "resolve_runtime_paths", return_value=paths), patch.object(
                package_operations,
                "install_packages",
                return_value=failed,
            ):
                result = tool_main.run({"operation": "install", "packages": ["requests"]})
            self.assertFalse(result["ok"])
            self.assertEqual(marker.read_text(encoding="utf-8"), "unchanged")

    def test_resolves_tool_by_display_name_and_folder_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = _runtime_paths(temp_dir)
            tool_root = _create_tool(
                paths.tools_root,
                folder_id="folder-id",
                name="example_tool",
                display_name="示例工具",
                market_id="market-example",
            )
            by_name = resolve_package_target(
                parse_request({"operation": "list", "target_tool": "示例工具"}),
                paths,
            )
            by_id = resolve_package_target(
                parse_request({"operation": "list", "target_tool": "folder-id"}),
                paths,
            )
            by_market_id = resolve_package_target(
                parse_request({"operation": "list", "target_tool": "market-example"}),
                paths,
            )
            expected = tool_root / "dependencies" / "py313" / "site-packages"
            self.assertEqual(by_name.target_directory, expected)
            self.assertEqual(by_id.target_directory, expected)
            self.assertEqual(by_market_id.target_directory, expected)

    def test_explicit_path_target_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = _runtime_paths(temp_dir)
            target_path = Path(temp_dir) / "custom-packages"
            target = resolve_package_target(
                parse_request(
                    {
                        "operation": "install",
                        "target_path": str(target_path),
                        "packages": ["requests"],
                    }
                ),
                paths,
            )
            self.assertEqual(target.kind, "path")
            self.assertEqual(target.target_directory, target_path.resolve())

    def test_active_install_does_not_require_declared_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = _runtime_paths(temp_dir)
            _create_tool(
                paths.tools_root,
                folder_id="tool-id",
                name="example_tool",
                display_name="示例工具",
            )
            succeeded = subprocess.CompletedProcess(
                ["pip"],
                returncode=0,
                stdout="installed",
                stderr="",
            )
            with patch.object(tool_main, "resolve_runtime_paths", return_value=paths), patch.object(
                package_operations,
                "install_packages",
                return_value=succeeded,
            ) as install:
                result = tool_main.run(
                    {
                        "operation": "install",
                        "target_tool": "example_tool",
                        "packages": ["not-declared>=1"],
                    }
                )
            self.assertTrue(result["ok"])
            self.assertEqual(install.call_args.args[2], ("not-declared>=1",))

    def test_install_requirements_reads_target_tool_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = _runtime_paths(temp_dir)
            tool_root = _create_tool(
                paths.tools_root,
                folder_id="tool-id",
                name="example_tool",
                display_name="示例工具",
            )
            (tool_root / "program" / "requirements.txt").write_text(
                "requests>=2.32,<3\n",
                encoding="utf-8",
            )
            succeeded = subprocess.CompletedProcess(
                ["pip"],
                returncode=0,
                stdout="installed",
                stderr="",
            )
            with patch.object(tool_main, "resolve_runtime_paths", return_value=paths), patch.object(
                package_operations,
                "install_packages",
                return_value=succeeded,
            ) as install:
                result = tool_main.run(
                    {"operation": "install_requirements", "target_tool": "example_tool"}
                )
            self.assertTrue(result["ok"])
            self.assertEqual(install.call_args.args[2], ("requests>=2.32,<3",))

if __name__ == "__main__":
    unittest.main()
