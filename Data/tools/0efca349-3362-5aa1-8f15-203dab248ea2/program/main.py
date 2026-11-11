"""Independent external messaging tool; the host owns configured connections and credentials."""
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from tiance_runtime import call_host_capability, run_tool


def run(payload):
    action = payload.get("action")
    if action not in {"list_connections", "send_file"}:
        raise ValueError("action 必须是 list_connections 或 send_file。")
    platform = payload.get("platform")
    if platform not in {"telegram", "feishu", "wechat"}:
        raise ValueError("platform 必须是 telegram、feishu 或 wechat。")
    request = {"platform": platform, "action": action}
    if action == "send_file":
        for name in ("connection_id", "chat_id", "file_path"):
            if not isinstance(payload.get(name), str) or not payload[name].strip():
                raise ValueError(f"send_file 必须明确提供 {name}。")
        path = Path(payload["file_path"])
        if not path.is_absolute():
            workspace = os.environ.get("TIANCE_WORKSPACE_ROOT")
            if not workspace:
                raise ValueError("没有当前工作区，请使用文件绝对路径。")
            path = Path(workspace) / path
        request.update(connection_id=payload["connection_id"].strip(), chat_id=payload["chat_id"].strip(),
                       file_path=str(path.resolve()), caption=payload.get("caption", ""))
    config = json.loads((Path(__file__).resolve().parents[1] / ".tool/tool.json").read_text(encoding="utf-8"))
    try:
        return call_host_capability("external_messaging", request,
                                    timeout_seconds=config["runtime"]["timeout_seconds"])
    except RuntimeError as exc:
        # The HTTP response from the local bridge may have been lost after delivery.
        rejected = isinstance(exc.__cause__, HTTPError) and exc.__cause__.code in {400,401,403,404,409,422}
        return {"ok": False, "status": "not_sent" if rejected else "unknown", "error": str(exc),
                "instruction": "若已发起发送，请先检查目标聊天；不能据此认定文件未送达并自动重发。"}


if __name__ == "__main__":
    run_tool(run)
