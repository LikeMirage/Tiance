from __future__ import annotations

from datetime import datetime, timezone
import math
import time
from typing import Any

from tiance_runtime import run_tool


MIN_WAIT_SECONDS = 0.1
MAX_WAIT_SECONDS = 3600.0


class InvalidDurationError(ValueError):
    pass


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        duration_seconds = parse_duration_seconds(payload.get("duration_seconds"))
    except InvalidDurationError as exc:
        message = str(exc)
        return {
            "ok": False,
            "error": f"INVALID_DURATION: {message}",
            "error_info": {
                "code": "INVALID_DURATION",
                "message": message,
                "details": {
                    "minimum_seconds": MIN_WAIT_SECONDS,
                    "maximum_seconds": MAX_WAIT_SECONDS,
                },
            },
        }

    started_at = utc_timestamp()
    started_monotonic = time.monotonic()
    time.sleep(duration_seconds)
    elapsed_seconds = max(0.0, time.monotonic() - started_monotonic)
    completed_at = utc_timestamp()

    return {
        "ok": True,
        "summary": f"已等待 {duration_seconds:g} 秒。",
        "data": {
            "requested_seconds": duration_seconds,
            "elapsed_seconds": round(elapsed_seconds, 3),
            "started_at": started_at,
            "completed_at": completed_at,
        },
    }


def parse_duration_seconds(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidDurationError("duration_seconds 必须是数字。")

    duration_seconds = float(value)
    if not math.isfinite(duration_seconds):
        raise InvalidDurationError("duration_seconds 必须是有限数字。")
    if not MIN_WAIT_SECONDS <= duration_seconds <= MAX_WAIT_SECONDS:
        raise InvalidDurationError(
            f"duration_seconds 必须在 {MIN_WAIT_SECONDS:g}–{MAX_WAIT_SECONDS:g} 秒之间。"
        )
    return duration_seconds


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


if __name__ == "__main__":
    run_tool(run)
