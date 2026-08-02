from __future__ import annotations
import json, os
from pathlib import Path
from tiance_runtime import call_host_capability, run_tool
CONFIG_PATH=Path(__file__).with_name("config.json")
def run(payload):
    _install_optional_token(); return call_host_capability("github_platform",{"action":payload["action"],"dryRun":bool(payload.get("dry_run",False)),"parameters":payload.get("parameters") or {}},timeout_seconds=1170)
def _install_optional_token():
    try: data=json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError: return
    except (OSError,json.JSONDecodeError) as exc: raise ValueError("program/config.json 不是有效 JSON。") from exc
    token=data.get("github_token") if isinstance(data,dict) else None
    if token: os.environ["TIANCE_GITHUB_TOKEN"]=str(token).strip()
if __name__=="__main__": run_tool(run)
