from __future__ import annotations

import ctypes
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


PROGRAM_ROOT = Path(__file__).resolve().parents[1] / "program"
if str(PROGRAM_ROOT) not in sys.path:
    sys.path.insert(0, str(PROGRAM_ROOT))

import process_output  # noqa: E402


def _load_run_command_module():
    runtime_stub = types.ModuleType("tiance_runtime")
    runtime_stub.run_tool = lambda _function: None
    sys.modules.setdefault("tiance_runtime", runtime_stub)
    spec = importlib.util.spec_from_file_location("run_command_main", PROGRAM_ROOT / "main.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 run_command 主程序。")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_command = _load_run_command_module()


class ProcessOutputTests(unittest.TestCase):
    def test_utf8_wins_before_windows_code_page_fallback(self) -> None:
        raw = "中文测试".encode("utf-8")
        with patch.object(process_output, "_fallback_encodings", return_value=("cp936",)):
            decoded = process_output.decode_process_output(raw, encoding_hint="cmd")
        self.assertEqual(decoded, "中文测试")

    def test_legacy_code_page_is_used_when_utf8_is_invalid(self) -> None:
        raw = "中文测试".encode("cp936")
        with patch.object(process_output, "_fallback_encodings", return_value=("cp936",)):
            decoded = process_output.decode_process_output(raw, encoding_hint="cmd")
        self.assertEqual(decoded, "中文测试")

    def test_bom_and_probable_utf16_are_decoded(self) -> None:
        text = "中文 UTF-16"
        self.assertEqual(
            process_output.decode_process_output(text.encode("utf-8-sig"), encoding_hint="argv"),
            text,
        )
        self.assertEqual(
            process_output.decode_process_output(text.encode("utf-16"), encoding_hint="argv"),
            text,
        )
        self.assertEqual(
            process_output.decode_process_output(text.encode("utf-16-le"), encoding_hint="argv"),
            text,
        )

    def test_terminal_controls_are_removed_without_damaging_text(self) -> None:
        raw = (
            "\x1b[31m红色\x1b[0m"
            "|\x1b]8;;https://example.com\x1b\\链接\x1b]8;;\x1b\\"
            "|\x1b[2J清屏后"
            "|\x1bPignored\x1b\\保留"
            "|\x9dtitle\x9c正文"
            "\x00\x07"
        )
        self.assertEqual(
            process_output.strip_terminal_controls(raw),
            "红色|链接|清屏后|保留|正文",
        )

    def test_plain_unicode_and_whitespace_are_preserved(self) -> None:
        text = "普通[]\\中文🙂\n下一行\t制表\r\n"
        self.assertEqual(process_output.strip_terminal_controls(text), text)

    def test_controls_are_removed_before_visible_text_is_truncated(self) -> None:
        raw = b"\x1b[31m12345\x1b[0m"
        text, truncated = process_output.prepare_process_output(
            raw,
            encoding_hint="argv",
            max_chars=5,
        )
        self.assertEqual(text, "12345")
        self.assertFalse(truncated)

    def test_invalid_bytes_only_use_replacement_as_last_resort(self) -> None:
        with patch.object(process_output, "_fallback_encodings", return_value=()):
            decoded = process_output.decode_process_output(b"\xfftext", encoding_hint="argv")
        self.assertEqual(decoded, "�text")


class RunCommandIntegrationTests(unittest.TestCase):
    def _run(self, payload: dict[str, object]) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"TIANCE_WORKSPACE_ROOT": temp_dir}, clear=False):
                return run_command.run(payload)

    def test_argv_preserves_utf8_stdin_and_output(self) -> None:
        script = (
            "import sys; "
            "text=sys.stdin.buffer.read().decode('utf-8'); "
            "sys.stdout.buffer.write(('收到:'+text).encode('utf-8'))"
        )
        result = self._run(
            {
                "argv": [sys.executable, "-c", script],
                "stdin": "中文输入",
            }
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["stdout"], "收到:中文输入")

    def test_argv_output_removes_ansi_sequences(self) -> None:
        script = "import sys;sys.stdout.write('\\x1b[32m成功\\x1b[0m')"
        result = self._run({"argv": [sys.executable, "-c", script]})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["stdout"], "成功")

    def test_timeout_output_uses_the_same_decode_and_cleanup_pipeline(self) -> None:
        script = (
            "import sys,time;"
            "sys.stdout.buffer.write('超时输出\\x1b[31m'.encode('utf-8'));"
            "sys.stdout.flush();time.sleep(3)"
        )
        result = self._run(
            {
                "argv": [sys.executable, "-c", script],
                "timeout_seconds": 1,
            }
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_info"]["code"], "COMMAND_TIMEOUT")
        self.assertEqual(result["data"]["status"], "timeout")
        self.assertEqual(result["data"]["stdout"], "超时输出")

    @unittest.skipUnless(os.name == "nt", "CMD 测试仅适用于 Windows。")
    def test_cmd_keeps_utf8_chinese_output(self) -> None:
        result = self._run({"command": "echo 中文测试", "shell": "cmd"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["stdout"].strip(), "中文测试")

    @unittest.skipUnless(os.name == "nt", "CMD 测试仅适用于 Windows。")
    def test_cmd_preserves_quoted_file_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "quoted source.txt"
            source_path.write_text("quoted-ok", encoding="ascii")
            command = f'type "{source_path}"'
            with patch.dict(os.environ, {"TIANCE_WORKSPACE_ROOT": temp_dir}, clear=False):
                result = run_command.run({"command": command, "shell": "cmd"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["stdout"], "quoted-ok")

    @unittest.skipUnless(os.name == "nt", "Windows 代码页测试仅适用于 Windows。")
    def test_cmd_decodes_native_code_page_stdout_and_stderr(self) -> None:
        code_page = int(ctypes.windll.kernel32.GetOEMCP())
        encoding = f"cp{code_page}"
        expected = self._representable_non_ascii_text(encoding)
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "native-output.txt"
            output_path.write_bytes(expected.encode(encoding))
            command = (
                f'type "{output_path}" '
                f'& type "{output_path}" 1>&2 '
                "& exit /b 7"
            )
            with patch.dict(os.environ, {"TIANCE_WORKSPACE_ROOT": temp_dir}, clear=False):
                result = run_command.run({"command": command, "shell": "cmd"})
        data = result["data"]
        self.assertEqual(data["stdout"], expected, result)
        self.assertEqual(data["stderr"], expected, result)

    @unittest.skipUnless(os.name == "nt", "PowerShell 测试仅适用于 Windows。")
    def test_powershell_keeps_chinese_output(self) -> None:
        if not (shutil.which("pwsh") or shutil.which("powershell")):
            self.skipTest("未安装 PowerShell。")
        result = self._run({"command": "Write-Output '中文测试'", "shell": "powershell"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["stdout"].strip(), "中文测试")

    @unittest.skipUnless(os.name == "nt", "PowerShell 测试仅适用于 Windows。")
    def test_powershell_preserves_native_exit_code(self) -> None:
        if not (shutil.which("pwsh") or shutil.which("powershell")):
            self.skipTest("未安装 PowerShell。")
        executable = str(Path(sys.executable)).replace("'", "''")
        command = f"& '{executable}' -c 'raise SystemExit(2)'"
        result = self._run(
            {
                "command": command,
                "shell": "powershell",
                "expected_exit_codes": [2],
            }
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["exit_code"], 2)

    @unittest.skipUnless(os.name == "nt", "PowerShell 测试仅适用于 Windows。")
    def test_powershell_cmdlet_failure_still_returns_one(self) -> None:
        if not (shutil.which("pwsh") or shutil.which("powershell")):
            self.skipTest("未安装 PowerShell。")
        result = self._run(
            {
                "command": "Write-Error 'expected failure'",
                "shell": "powershell",
            }
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_info"]["code"], "COMMAND_FAILED")
        self.assertEqual(result["data"]["exit_code"], 1)

    @unittest.skipUnless(os.name == "nt", "PowerShell 测试仅适用于 Windows。")
    def test_powershell_uses_the_last_command_status(self) -> None:
        if not (shutil.which("pwsh") or shutil.which("powershell")):
            self.skipTest("未安装 PowerShell。")
        executable = str(Path(sys.executable)).replace("'", "''")
        command = f"& '{executable}' -c 'raise SystemExit(2)'; Write-Output 'recovered'"
        result = self._run({"command": command, "shell": "powershell"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["exit_code"], 0)
        self.assertEqual(result["data"]["stdout"].strip(), "recovered")

    @staticmethod
    def _representable_non_ascii_text(encoding: str) -> str:
        for candidate in ("中文测试", "Grüße", "café", "£"):
            try:
                encoded = candidate.encode(encoding)
            except UnicodeEncodeError:
                continue
            if any(byte >= 0x80 for byte in encoded):
                return candidate
        raise AssertionError(f"未找到可用于 {encoding} 的非 ASCII 测试文本。")


if __name__ == "__main__":
    unittest.main()
