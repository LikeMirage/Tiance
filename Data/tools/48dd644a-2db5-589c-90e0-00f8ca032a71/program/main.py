from __future__ import annotations

from typing import Any

from tiance_runtime import call_host_capability, run_tool


def run(payload: dict[str, Any]) -> dict[str, Any]:
    return call_host_capability(
        "memory_management",
        payload,
        timeout_seconds=30,
    )


if __name__ == "__main__":
    run_tool(run)
