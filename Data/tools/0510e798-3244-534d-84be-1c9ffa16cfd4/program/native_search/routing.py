import json
from pathlib import Path
from urllib.parse import urlsplit

from . import anthropic, gemini, openai_responses
from .common import SearchError, SearchTarget


ADAPTERS = {
    "openai_responses": openai_responses.search,
    "anthropic_messages": anthropic.search,
    "gemini_generate_content": gemini.search,
}
MANIFEST = Path(__file__).resolve().parents[2] / ".tool" / "tool.json"


def _origin(url):
    port = url.port if url.port is not None else (443 if url.scheme == "https" else 80)
    return url.scheme, url.hostname, port


def _match_endpoint(address, endpoints):
    path = address.path.rstrip("/")
    matches = []
    for name, entry in endpoints.items():
        target = urlsplit(entry["url"])
        if not target.hostname or _origin(target) != _origin(address):
            continue
        prefix = entry.get("search", {}).get("source_path_prefix", "").rstrip("/")
        if prefix and not prefix.startswith("/"):
            raise ValueError(f"{name} 的 source_path_prefix 须以 / 开头")
        if not prefix or path == prefix or path.startswith(prefix + "/"):
            matches.append((len(prefix), name))
    if matches:
        matches.sort(reverse=True)
        if len(matches) > 1 and matches[0][0] == matches[1][0]:
            raise ValueError("同一地址有多条同等优先级规则，请指定不同的 source_path_prefix")
        return matches[0][1]
    if path.endswith("/chat/completions"):
        return "responses_from_chat"
    if path.endswith("/responses"):
        return "generic_responses"
    if path.endswith("/messages"):
        return "generic_messages"
    if "/models/" in path and path.endswith((":{action}", ":generateContent", ":streamGenerateContent")):
        return "generic_gemini"
    raise SearchError("该生成地址没有匹配的搜索路由。请在搜索工具包中为此地址配置端点。",
                      code="provider_search_endpoint_missing")


def select_target(source):
    if "generation_url" not in source:
        raise SearchError("当前后端没有返回会话的生成地址，请重启更新后的天策。",
                          code="provider_search_host_update_required")
    address = urlsplit(source["generation_url"])
    if not address.hostname:
        raise SearchError("调用会话没有可用的供应商生成地址。", code="provider_search_endpoint_missing")
    try:
        endpoints = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))["runtime"]["session_model_endpoints"]
        name = _match_endpoint(address, endpoints)
        route = endpoints[name]
        protocol = route["protocol"]
        rule = route.get("search", {})
        tool = rule.get("model_tools", {}).get(source["model_id"], rule.get("responses_tool", "web_search"))
        include = rule.get("include_sources", False)
        if protocol not in ADAPTERS or not isinstance(tool, str) or not tool.strip() or not isinstance(include, bool):
            raise ValueError("搜索协议、工具名或 include_sources 无效")
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
        raise SearchError(f"请检查搜索工具包的端点和规则：{exc}", code="provider_search_rules_invalid") from exc
    return SearchTarget(
        provider_id=source["provider_id"], model_id=source["model_id"],
        protocol_family=protocol, endpoint=name, responses_tool=tool, include_sources=include,
    )
