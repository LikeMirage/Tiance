from tiance_runtime import call_host_capability, run_tool


BACKEND_REQUEST_TIMEOUT_SECONDS = 165


def run(payload):
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        return {"ok": False, "error": "query 不能为空。"}

    result = call_host_capability(
        "web_search",
        {"query": query.strip()},
        timeout_seconds=BACKEND_REQUEST_TIMEOUT_SECONDS,
    )
    sources = result.get("sources")
    source_count = len(sources) if isinstance(sources, list) else 0
    return {
        "ok": True,
        "summary": f"当前模型的内置网络搜索已完成，供应商返回 {source_count} 条来源记录。",
        "data": result,
    }


if __name__ == "__main__":
    run_tool(run)
