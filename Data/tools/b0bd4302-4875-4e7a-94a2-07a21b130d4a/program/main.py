from __future__ import annotations

import json
import os
from pathlib import Path

from tiance_runtime import call_host_capability, run_tool


BACKEND_REQUEST_TIMEOUT_SECONDS = 570
CONFIG_PATH = Path(__file__).with_name("config.json")


def run(payload):
    _install_optional_token()
    result = call_host_capability(
        "git_repository",
        payload,
        timeout_seconds=BACKEND_REQUEST_TIMEOUT_SECONDS,
    )
    if not isinstance(result, dict):
        return {"ok": False, "error": "Git 仓库服务返回了无效结果。"}
    return result


def _install_optional_token() -> None:
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("program/config.json 不是有效的 JSON 配置。") from exc
    if not isinstance(payload, dict):
        raise ValueError("program/config.json 必须是 JSON 对象。")
    token = payload.get("github_token")
    if token in {None, ""}:
        return
    if not isinstance(token, str) or not token.strip():
        raise ValueError("program/config.json 中的 github_token 无效。")
    os.environ["TIANCE_GITHUB_TOKEN"] = token.strip()


if __name__ == "__main__":
    run_tool(run)
