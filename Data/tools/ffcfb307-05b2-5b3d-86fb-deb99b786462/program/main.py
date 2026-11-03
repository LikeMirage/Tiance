from pathlib import Path
import json

from tiance_runtime import call_host_capability, run_tool

def run(payload):
    config = json.loads((Path(__file__).resolve().parents[1] / ".tool/tool.json").read_text(encoding="utf-8"))
    return call_host_capability("conversation_naming", payload, timeout_seconds=config["runtime"]["timeout_seconds"])

if __name__ == "__main__":
    run_tool(run)
