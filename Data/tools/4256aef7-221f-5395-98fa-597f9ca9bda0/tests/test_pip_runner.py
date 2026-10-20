from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


PROGRAM_ROOT = Path(__file__).resolve().parents[1] / "program"
if str(PROGRAM_ROOT) not in sys.path:
    sys.path.insert(0, str(PROGRAM_ROOT))

import pip_runner  # noqa: E402
from package_environment import RuntimePaths  # noqa: E402


class PipRunnerTests(unittest.TestCase):
    def test_inherits_platform_directories_without_ambient_configuration(self) -> None:
        directory_env = {
            "ALLUSERSPROFILE": "C:\\ProgramData",
            "APPDATA": "C:\\Users\\Tester\\AppData\\Roaming",
            "HOME": "C:\\Users\\Tester",
            "HOMEDRIVE": "C:",
            "HOMEPATH": "\\Users\\Tester",
            "LOCALAPPDATA": "C:\\Users\\Tester\\AppData\\Local",
            "ProgramData": "C:\\ProgramData",
            "PUBLIC": "C:\\Users\\Public",
            "SystemDrive": "C:",
            "SystemRoot": "C:\\Windows",
            "USERPROFILE": "C:\\Users\\Tester",
            "WINDIR": "C:\\Windows",
        }
        excluded_env = {
            "TIANCE_PRIVATE_TOKEN": "must-not-inherit",
            "PYTHONPATH": "C:\\ambient-python",
            "PIP_INDEX_URL": "https://ambient.invalid/simple",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = RuntimePaths(
                python_executable=Path(sys.executable),
                pip_runner=root / "run_pip.py",
                runtime_root=root / "runtime",
                tools_root=root / "tools",
            )
            with patch.dict(
                os.environ, {**directory_env, **excluded_env}, clear=False,
            ), patch.object(pip_runner.subprocess, "run") as run:
                run.return_value = subprocess.CompletedProcess([], 0, "", "")
                pip_runner.install_packages(
                    paths,
                    root / "site-packages",
                    ("example-package",),
                    index_url="https://explicit.invalid/simple",
                    timeout_seconds=30,
                )

        child_env = run.call_args.kwargs["env"]
        for key, value in directory_env.items():
            self.assertEqual(child_env[key], value)
        for key in excluded_env:
            self.assertNotIn(key, child_env)
        self.assertEqual(child_env["PYTHONNOUSERSITE"], "1")
        self.assertIn("--isolated", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
