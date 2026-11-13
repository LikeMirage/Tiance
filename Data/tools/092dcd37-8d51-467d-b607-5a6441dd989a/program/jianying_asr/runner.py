"""Standalone-tool adapter; the shared engine never reads tool configuration."""
import json
from pathlib import Path
from .common import ASRError, Budget
from .client import JianyingClient
from .engine import run as recognize, validate


def configured_budget() -> Budget:
    manifest = Path(__file__).resolve().parents[2] / ".tool" / "tool.json"
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))["runtime"]["timeout_seconds"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ASRError("CONFIG_ERROR", "无法读取 .tool/tool.json 的 runtime.timeout_seconds。") from exc
    return Budget(value)


def run(payload: dict, *, client_factory=JianyingClient, budget: Budget | None = None) -> dict:
    try:
        budget = budget or configured_budget()
    except ASRError as exc:
        return {"ok": False, "error_code": exc.code, "error": str(exc)}
    return recognize(payload, client_factory=client_factory, budget=budget)
