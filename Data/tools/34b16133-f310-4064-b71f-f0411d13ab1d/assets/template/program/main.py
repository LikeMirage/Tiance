"""Replace run() with the business implementation; keep the standard JSON entry."""
from __future__ import annotations


def run(payload: dict) -> dict:
    if payload:
        return {"ok": False, "error": "空白模板不接收参数，请先实现业务和输入 Schema。"}
    return {
        "ok": False,
        "error": "工具尚未实现。请先阅读 docs/tool-development/README.md 并完成制作。",
        "error_info": {"code": "TOOL_NOT_IMPLEMENTED"},
    }


if __name__ == "__main__":
    from tiance_runtime import run_tool

    run_tool(run)
