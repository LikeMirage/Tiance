from dataclasses import asdict
from time import monotonic

from tiance_runtime import call_host_capability, run_tool
from native_search.common import SearchError
from native_search.routing import ADAPTERS, select_target


def run(payload):
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        return {"ok": False, "error": "query 不能为空。"}
    deadline = monotonic() + 150
    try:
        metadata = call_host_capability("session_model", {"operation": "source"}, timeout_seconds=10)
        target = select_target(metadata)
        usage = None

        def post(body):
            nonlocal usage
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise SearchError("供应商内置网络搜索超时。", code="provider_web_search_timeout")
            reply = call_host_capability("session_model", {
                "operation": "post", "protocol_family": target.protocol_family, "body": body,
                "endpoint": target.endpoint,
            }, timeout_seconds=remaining)
            data = reply["data"]
            if not 200 <= reply["status"] < 300:
                error = data.get("error")
                detail = error.get("message") if isinstance(error, dict) else error
                raise SearchError(f"上游请求失败（HTTP {reply['status']}）：{detail or data.get('message') or '未提供原因'}")
            if reply.get("usage"):
                if usage is None:
                    usage = dict(reply["usage"])
                else:
                    for name, value in reply["usage"].items():
                        if isinstance(value, int):
                            usage[name] = (usage.get(name) or 0) + value
            return data

        result = ADAPTERS[target.protocol_family](target, query.strip(), post)
        return {"ok": True, "summary": f"内置网络搜索完成，返回 {len(result.sources)} 条来源记录。",
                "data": {**asdict(result), "usage": usage}}
    except SearchError as exc:
        return {"ok": False, "error": str(exc), "error_info": {"code": exc.code, "details": exc.details}}
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}


if __name__ == "__main__":
    run_tool(run)
