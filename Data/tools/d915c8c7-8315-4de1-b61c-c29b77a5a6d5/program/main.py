from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from tiance_runtime import call_host_capability, run_tool

from deepseek_config import ToolError, config_info, configure_key, load_config
from deepseek_results import format_results
from deepseek_transport import post_direct


CONFIG_PATH = Path(__file__).with_name("config.json")
_FIELDS = {
    "search": {"query", "count", "need_content", "ori_question", "localization"},
    "fetch": {"url"}, "configure": {"api_key"}, "config_info": set(),
}


def normalize_request(payload: dict) -> tuple[str, dict]:
    if not isinstance(payload, dict):
        raise ToolError("INVALID_ARGUMENT", "输入必须是 JSON 对象。")
    action = payload.get("action", "search")
    if not isinstance(action, str) or action not in _FIELDS:
        raise ToolError("INVALID_ARGUMENT", "action 只支持 search、fetch、configure、config_info。")
    if set(payload) - _FIELDS[action] - {"action"}:
        raise ToolError("INVALID_ARGUMENT", "当前 action 含不支持的参数。")
    body = {k: v for k, v in payload.items() if k != "action"}
    if action == "search":
        for field in ("query", "ori_question"):
            value = body.get(field)
            if field == "ori_question" and value is None:
                continue
            if not isinstance(value, str) or not value.strip() or len(value) > 128:
                raise ToolError("INVALID_ARGUMENT", f"{field} 必须为 1～128 字符的非空文本。")
        count = body.setdefault("count", 10)
        if type(count) is not int or not 1 <= count <= 50:
            raise ToolError("INVALID_ARGUMENT", "count 必须是 1～50 的整数。")
        if type(body.setdefault("need_content", False)) is not bool:
            raise ToolError("INVALID_ARGUMENT", "need_content 必须是布尔值。")
        if "localization" in body and not isinstance(body["localization"], str):
            raise ToolError("INVALID_ARGUMENT", "localization 必须是 IP 地址字符串。")
    elif action == "fetch":
        url = body.get("url")
        if not isinstance(url, str) or not url or len(url) > 8192 or any(c.isspace() for c in url):
            raise ToolError("INVALID_ARGUMENT", "url 必须是最多 8192 字符的 HTTP/HTTPS 网址。")
        try:
            parsed = urlsplit(url)
            valid = (parsed.scheme in {"http", "https"} and parsed.hostname
                     and parsed.username is None and parsed.password is None)
        except ValueError:
            valid = False
        if not valid:
            raise ToolError("INVALID_ARGUMENT", "url 必须是没有账号密码的 HTTP/HTTPS 网址。")
    elif action == "configure" and not isinstance(body.get("api_key"), str):
        raise ToolError("INVALID_ARGUMENT", "configure 必须传入 api_key 字符串；空字符串表示清除 JSON Key。")
    return action, body


def run(payload: dict) -> dict:
    key = ""
    source = None
    try:
        action, body = normalize_request(payload)
        if action == "configure":
            key = body["api_key"].strip()
            configure_key(CONFIG_PATH, key)
            return {"ok": True, "summary": "已保存工具 Key。" if key else "已清除工具 Key，搜索时将使用模型集凭据。",
                    "data": {"config_path": str(CONFIG_PATH.resolve()), "config_key_configured": bool(key)}}
        config = load_config(CONFIG_PATH)
        if action == "config_info":
            return {"ok": True, "data": config_info(CONFIG_PATH, config)}
        key = config["deepseek"]["api_key"]
        source = "config" if key else "provider"
        if key:
            response = post_direct(action, body, key)
        else:
            try:
                reply = call_host_capability("deepseek_web", {"action": action, **body}, timeout_seconds=165)
            except RuntimeError as exc:
                raise ToolError("DEEPSEEK_BRIDGE_UNAVAILABLE",
                                f"无法通过能力桥使用模型集的 DeepSeek Key：{exc}。请在天策中运行此工具，或用 action=configure 配置工具 Key。") from exc
            if reply.get("ok") is not True:
                info = reply.get("error_info") or {}
                raise ToolError(info.get("code", "DEEPSEEK_BRIDGE_FAILED"),
                                reply.get("error") or "DeepSeek 能力桥请求失败。", info.get("details"))
            response = reply.get("data")
        if not isinstance(response, dict):
            raise ToolError("DEEPSEEK_INVALID_RESPONSE", "搜索接口返回值必须是 JSON 对象。")
        data = format_results(action, body, response, config["output"], source)
        summary = f"搜索返回 {data['result_count']} 条结果。" if action == "search" else "已读取网页。"
        return {"ok": True, "summary": summary, "data": data}
    except ToolError as exc:
        details = {**exc.details, "config_path": str(CONFIG_PATH.resolve())}
        if source:
            details["key_source"] = source
        message = exc.message.replace(key, "[REDACTED]") if key else exc.message
        return {"ok": False, "error": message,
                "error_info": {"code": exc.code, "message": message, "details": details}}
    except Exception as exc:
        message = f"DeepSeek 工具执行失败：{type(exc).__name__}: {exc}"
        if key:
            message = message.replace(key, "[REDACTED]")
        return {"ok": False, "error": message,
                "error_info": {"code": "DEEPSEEK_TOOL_FAILED", "message": message,
                               "details": {"key_source": source}}}


if __name__ == "__main__":
    run_tool(run)
