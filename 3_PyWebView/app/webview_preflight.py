"""Run the native prerequisite check before creating any desktop window or service."""
import ctypes
import os
from pathlib import Path
import subprocess

from app.config import ShellSettings

HELPER = Path(__file__).resolve().parent / "native" / "Tiance.WebViewCheck.exe"


def _run_check(*args: str) -> None:
    try:
        result = subprocess.run([str(HELPER), *args], creationflags=subprocess.CREATE_NO_WINDOW)
    except OSError as exc:
        message = f"无法启动运行环境检测程序。请重新解压完整的天策程序包。\n\n{exc}"
        ctypes.windll.user32.MessageBoxW(None, message, "天策", 0x10)
        raise SystemExit(1) from exc
    if result.returncode:
        raise SystemExit(result.returncode)


def report_runtime_configuration(detail: str) -> None:
    if os.name == "nt":
        _run_check("--configuration-error", detail)


def check_webview_runtime(settings: ShellSettings, webview) -> None:
    if os.name == "nt":
        sdk = Path(webview.__file__).resolve().parent / "lib"
        browser = os.environ.get("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER") or settings.webview2_runtime_path
        _run_check(str(sdk), browser or "", settings.webview_storage_path)
