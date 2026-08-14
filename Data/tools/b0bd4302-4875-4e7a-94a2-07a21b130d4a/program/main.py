from __future__ import annotations

from typing import Any

from tiance_runtime import run_tool


try:
    from service import execute
except ModuleNotFoundError as import_error:
    if import_error.name != "dulwich":
        raise

    def execute(_: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": False,
            "error": "DEPENDENCY_MISSING: 缺少内嵌 Git 引擎依赖 dulwich，请在工具依赖看板安装 program/requirements.txt 中声明的依赖。",
            "error_info": {
                "code": "DEPENDENCY_MISSING",
                "message": "缺少内嵌 Git 引擎依赖 dulwich。",
                "details": {"requirement": "dulwich>=1.2,<2.0"},
            },
        }


if __name__ == "__main__":
    run_tool(execute)
