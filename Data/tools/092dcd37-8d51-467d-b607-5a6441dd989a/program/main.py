"""Standalone stdin JSON -> stdout JSON entry; also compatible with Tiance."""
from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        from jianying_asr.runner import run
        result = run(payload)
    except ModuleNotFoundError as exc:
        result = {"ok": False, "error_code": "DEPENDENCY_MISSING",
                  "error": f"缺少依赖 {exc.name}，请安装 program/requirements.txt。"}
    except (ValueError, UnicodeDecodeError):
        result = {"ok": False, "error_code": "INVALID_ARGUMENTS", "error": "输入必须是合法 JSON 对象。"}
    except Exception as exc:
        result = {"ok": False, "error_code": "LOCAL_ERROR", "error": f"工具启动失败（{type(exc).__name__}）。"}
    json.dump(result, sys.stdout, ensure_ascii=False, allow_nan=False)
    sys.stdout.write("\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
