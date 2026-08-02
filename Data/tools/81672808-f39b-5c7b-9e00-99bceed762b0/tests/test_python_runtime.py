from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROGRAM_ROOT = Path(__file__).resolve().parents[1] / "program"
if str(PROGRAM_ROOT) not in sys.path:
    sys.path.insert(0, str(PROGRAM_ROOT))

import python_runtime  # noqa: E402


class PythonRuntimeTests(unittest.TestCase):
    def test_resolves_versioned_active_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir) / "runtime"
            executable = runtime_root / "python/py313/python.exe"
            executable.parent.mkdir(parents=True)
            executable.touch()
            user_root = runtime_root / "python-packages/user/py313"
            site_packages = user_root / "environments/env-test/site-packages"
            site_packages.mkdir(parents=True)
            (user_root / "active.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "site_packages": "environments/env-test/site-packages",
                    }
                ),
                encoding="utf-8",
            )
            resolved = python_runtime.resolve_user_site_packages_path(executable)
        self.assertEqual(resolved, site_packages)

    def test_explicitly_injects_user_and_caller_import_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workdir = root / "workspace"
            user_packages = root / "user-packages"
            caller_packages = root / "caller-packages"
            for path in (workdir, user_packages, caller_packages):
                path.mkdir()
            with patch.object(
                python_runtime,
                "resolve_user_site_packages_path",
                return_value=user_packages,
            ):
                runtime = python_runtime.build_runtime(
                    workdir,
                    {"PYTHONPATH": str(caller_packages)},
                )
        self.assertEqual(
            runtime.import_paths,
            (workdir, user_packages, caller_packages),
        )
        self.assertNotIn("PYTHONPATH", runtime.environment)

    def test_prepared_runtime_holds_and_releases_environment_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            site_packages = root / "environments/env-test/site-packages"
            site_packages.mkdir(parents=True)
            (root / "active.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "site_packages": "environments/env-test/site-packages",
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(
                python_runtime,
                "resolve_user_packages_root",
                return_value=root,
            ):
                with python_runtime.prepared_runtime(root, {}) as runtime:
                    self.assertEqual(runtime.user_site_packages, site_packages)
                    self.assertEqual(len(list((root / "leases").glob("lease-*.json"))), 1)
                self.assertEqual(list((root / "leases").glob("lease-*.json")), [])

    def test_run_script_can_import_from_injected_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workdir = root / "workspace"
            user_packages = root / "user-packages"
            workdir.mkdir()
            user_packages.mkdir()
            (user_packages / "example_dependency.py").write_text(
                'VALUE = "import-ok"\n',
                encoding="utf-8",
            )
            script = root / "script.py"
            script.write_text(
                "import example_dependency; print(example_dependency.VALUE)\n",
                encoding="utf-8",
            )
            runtime = python_runtime.PythonRuntime(
                environment={
                    key: value
                    for key in ("COMSPEC", "PATH", "PATHEXT", "SystemRoot", "TEMP", "TMP", "WINDIR")
                    if (value := os.environ.get(key))
                },
                import_paths=(workdir, user_packages),
                user_site_packages=user_packages,
            )
            completed = python_runtime.run_script(
                script,
                [],
                stdin_text=None,
                workdir=workdir,
                runtime=runtime,
                timeout=10,
            )
        self.assertEqual(completed.exit_code, 0, completed.stderr)
        self.assertFalse(completed.timed_out)
        self.assertEqual(completed.stdout.strip(), "import-ok")

    def test_exit_code_124_is_not_reported_as_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "exit_124.py"
            script.write_text("raise SystemExit(124)\n", encoding="utf-8")
            runtime = python_runtime.build_runtime(root, {})
            completed = python_runtime.run_script(
                script,
                [],
                stdin_text=None,
                workdir=root,
                runtime=runtime,
                timeout=10,
            )
        self.assertEqual(completed.exit_code, 124)
        self.assertFalse(completed.timed_out)

    def test_timeout_is_reported_separately_from_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "slow.py"
            script.write_text("import time; time.sleep(1)\n", encoding="utf-8")
            completed = python_runtime.run_script(
                script,
                [],
                stdin_text=None,
                workdir=root,
                runtime=python_runtime.build_runtime(root, {}),
                timeout=0.05,
            )
        self.assertIsNone(completed.exit_code)
        self.assertTrue(completed.timed_out)
        self.assertIn("已停止", completed.stderr)

if __name__ == "__main__":
    unittest.main()
