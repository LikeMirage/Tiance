from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


PROGRAM_ROOT = Path(__file__).resolve().parents[1] / "program"
if str(PROGRAM_ROOT) not in sys.path:
    sys.path.insert(0, str(PROGRAM_ROOT))


def _load_run_command_module():
    runtime_stub = types.ModuleType("tiance_runtime")
    runtime_stub.run_tool = lambda _function: None
    sys.modules.setdefault("tiance_runtime", runtime_stub)
    spec = importlib.util.spec_from_file_location("run_command_contract_main", PROGRAM_ROOT / "main.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 run_command 主程序。")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_command = _load_run_command_module()


class CommandContractTests(unittest.TestCase):
    def _run(self, payload: dict[str, object]) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as workspace:
            with patch.dict(os.environ, {"TIANCE_WORKSPACE_ROOT": workspace}, clear=False):
                return run_command.run(payload)

    def test_command_and_argv_are_mutually_exclusive(self) -> None:
        missing = self._run({})
        both = self._run(
            {
                "command": "echo ignored",
                "argv": [sys.executable, "-c", "print('ignored')"],
            }
        )

        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error_info"]["code"], "INVALID_ARGUMENT")
        self.assertFalse(both["ok"])
        self.assertEqual(both["error_info"]["code"], "INVALID_ARGUMENT")

    def test_expected_exit_codes_control_success(self) -> None:
        payload = {
            "argv": [sys.executable, "-c", "raise SystemExit(3)"],
            "expected_exit_codes": [0, 3],
        }
        result = self._run(payload)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["exit_code"], 3)
        self.assertEqual(result["data"]["expected_exit_codes"], [0, 3])

    def test_unexpected_exit_code_keeps_execution_data(self) -> None:
        result = self._run(
            {
                "argv": [sys.executable, "-c", "import sys;sys.stderr.write('bad');raise SystemExit(4)"],
            }
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_info"]["code"], "COMMAND_FAILED")
        self.assertEqual(result["data"]["status"], "completed")
        self.assertEqual(result["data"]["exit_code"], 4)
        self.assertEqual(result["data"]["stderr"], "bad")

    def test_missing_executable_returns_structured_start_error(self) -> None:
        missing_name = "tiance-command-that-does-not-exist-7f0e8c"
        result = self._run({"argv": [missing_name]})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_info"]["code"], "COMMAND_NOT_FOUND")
        self.assertEqual(result["data"]["status"], "start_failed")
        self.assertIsNone(result["data"]["exit_code"])
        self.assertEqual(result["error_info"]["details"]["filename"], missing_name)

    def test_specific_shell_is_rejected_in_argv_mode(self) -> None:
        result = self._run(
            {
                "argv": [sys.executable, "-c", "print('ignored')"],
                "shell": "powershell",
            }
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_info"]["code"], "INVALID_ARGUMENT")

    def test_large_output_is_bounded_during_capture(self) -> None:
        result = self._run(
            {
                "argv": [sys.executable, "-c", "import sys;sys.stdout.write('x'*100000)"],
                "max_output_chars": 1000,
            }
        )

        self.assertTrue(result["ok"], result)
        self.assertTrue(result["data"]["stdout_truncated"])
        self.assertGreater(result["data"]["stdout_omitted_bytes"], 0)
        self.assertIn("stdout 已截断。", result["warnings"])
        self.assertLess(len(result["data"]["stdout"]), 1100)

    def test_outside_workdir_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as outside:
            payload = {
                "argv": [sys.executable, "-c", "import os;print(os.getcwd())"],
                "workdir": outside,
            }
            with patch.dict(os.environ, {"TIANCE_WORKSPACE_ROOT": workspace}, clear=False):
                result = run_command.run(payload)

        self.assertTrue(result["ok"], result)
        self.assertEqual(Path(result["data"]["stdout"].strip()), Path(outside))


if __name__ == "__main__":
    unittest.main()
