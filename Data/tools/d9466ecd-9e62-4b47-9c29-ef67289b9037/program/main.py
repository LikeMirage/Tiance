from __future__ import annotations

import os
from pathlib import Path
import re
import sys

from tiance_runtime import run_tool
from windows_shell import ShellError, WindowsShell


ACTIONS = {"reveal", "get_default_app", "list_apps", "open_default", "open_with"}
FIELDS = {"action", "path", "application_id", "application_path"}


def validate(payload):
    if not isinstance(payload, dict) or set(payload) - FIELDS:
        raise ShellError("INVALID_ARGUMENT", "只接受 action、path、application_id、application_path 参数。")
    for name in payload:
        value = payload[name]
        if not isinstance(value, str) or not value.strip() or "\0" in value:
            raise ShellError("INVALID_ARGUMENT", f"{name} 必须为非空字符串，不能含 NUL。")
    if payload.get("action") not in ACTIONS or "path" not in payload:
        raise ShellError("INVALID_ARGUMENT", "必须提供合法 action 和 path。")
    selected = [key for key in ("application_id", "application_path") if key in payload]
    if payload["action"] == "open_with":
        if len(selected) != 1:
            raise ShellError("INVALID_ARGUMENT", "open_with 必须且只能提供 application_id 或 application_path 其中一个。")
    elif selected:
        raise ShellError("INVALID_ARGUMENT", "只有 open_with 可以指定应用。")
    if "application_id" in payload and not re.fullmatch(r"windows:[0-9a-f]{64}", payload["application_id"]):
        raise ShellError("INVALID_ARGUMENT", "application_id 必须原样使用 list_apps 返回的标识。")


def resolve_path(raw, *, application=False):
    if "://" in raw or raw.lower().startswith("shell:"):
        raise ShellError("INVALID_PATH", "此工具只接受本机文件系统路径，不接受 URL 或 shell 命令。")
    path = Path(raw)
    if not path.is_absolute():
        if application or path.drive or path.root:
            raise ShellError("INVALID_PATH", "程序路径必须为绝对路径；文件路径不能省略盘符或使用盘符相对路径。")
        workspace = os.getenv("TIANCE_WORKSPACE_ROOT", "")
        if not workspace or not Path(workspace).is_absolute():
            raise ShellError("WORKSPACE_REQUIRED", "相对路径需要有效的调用工作区，请改用绝对路径。")
        path = Path(workspace) / path
    # Alternate data streams are not documents exposed by Explorer.
    if ":" in str(path)[len(path.drive):]:
        raise ShellError("INVALID_PATH", "不支持备用数据流路径。")
    try:
        path = path.resolve(strict=True)
    except FileNotFoundError:
        raise ShellError("PATH_NOT_FOUND", "路径不存在。", path=str(path)) from None
    if application and (not path.is_file() or path.suffix.lower() not in {".exe", ".com"}):
        raise ShellError("INVALID_APPLICATION", "application_path 必须指向实际存在的 EXE/COM 程序，不接受命令行或脚本。")
    if not path.is_file() and not path.is_dir():
        raise ShellError("INVALID_PATH", "路径不是普通文件或文件夹。")
    return path


def run(payload):
    try:
        validate(payload)
        if sys.platform != "win32":
            raise ShellError("UNSUPPORTED_PLATFORM", "此工具当前支持 Windows。")
        action = payload["action"]
        path = resolve_path(payload["path"])
        if path.is_dir() and action != "reveal":
            raise ShellError("IS_DIRECTORY", "此动作需要文件；打开文件夹请用 reveal。")
        executable = resolve_path(payload["application_path"], application=True) if "application_path" in payload else None
        data = {"action": action, "path": str(path), "extension": path.suffix.lower(),
                "kind": "directory" if path.is_dir() else "file", "execution_location": "tiance_computer"}
        warnings = []
        with WindowsShell() as shell:
            if action == "get_default_app":
                data["default_app"] = shell.default_app(path.suffix.lower())
                data["status"] = "queried"
                summary = "已查询系统默认应用。" if data["default_app"]["registered"] else "系统未返回此扩展名的默认应用。"
            elif action == "list_apps":
                associations, warnings = shell.list_apps(path.suffix.lower())
                data.update(associations, status="queried", application_count=len(associations["applications"]))
                summary = f"找到 {data['application_count']} 个系统登记的打开方式。"
            else:
                if action == "reveal":
                    shell.reveal(path)
                    data["selection_requested"] = path.is_file()
                elif action == "open_default":
                    shell.open_default(path)
                elif executable is not None:
                    data["application"] = shell.open_with_executable(path, executable)
                else:
                    data["application"] = shell.open_with_handler(path, payload["application_id"])
                data["status"] = "submitted"
                summary = "已向运行天策的电脑提交打开请求；不代表已验证应用显示或文档加载完成。"
        return {"ok": True, "summary": summary, "data": data, "warnings": warnings}
    except ShellError as exc:
        return failure(exc.code, str(exc), exc.details)
    except OSError as exc:
        code = "NO_ASSOCIATION" if getattr(exc, "winerror", None) == 1155 else "SYSTEM_OPERATION_FAILED"
        message = "未找到默认打开方式，请 list_apps 后选择应用或提供 application_path。" if code == "NO_ASSOCIATION" else str(exc)
        return failure(code, message, {"winerror": getattr(exc, "winerror", None)})


def failure(code, message, details):
    return {"ok": False, "error": f"{code}: {message}",
            "error_info": {"code": code, "message": message, "details": details}, "warnings": []}


if __name__ == "__main__":
    run_tool(run)
