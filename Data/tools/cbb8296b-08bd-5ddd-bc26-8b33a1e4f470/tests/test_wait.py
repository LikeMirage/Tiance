from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

TOOL_ROOT = Path(__file__).resolve().parents[1]
MODULE_SPEC = importlib.util.spec_from_file_location(
    "tiance_wait_tool_main",
    TOOL_ROOT / "program" / "main.py",
)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
main = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(main)


def test_wait_uses_requested_duration_and_reports_measured_time() -> None:
    with (
        patch.object(
            main,
            "utc_timestamp",
            side_effect=[
                "2026-01-01T00:00:00.000Z",
                "2026-01-01T00:00:02.500Z",
            ],
        ),
        patch.object(main.time, "monotonic", side_effect=[10.0, 12.5]),
        patch.object(main.time, "sleep") as sleep,
    ):
        result = main.run({"duration_seconds": 2.5})

    sleep.assert_called_once_with(2.5)
    assert result == {
        "ok": True,
        "summary": "已等待 2.5 秒。",
        "data": {
            "requested_seconds": 2.5,
            "elapsed_seconds": 2.5,
            "started_at": "2026-01-01T00:00:00.000Z",
            "completed_at": "2026-01-01T00:00:02.500Z",
        },
    }


@pytest.mark.parametrize(
    "value",
    [None, True, "1", 0, 0.09, 3600.01, float("inf"), float("nan")],
)
def test_wait_rejects_invalid_duration_without_sleeping(value: object) -> None:
    with patch.object(main.time, "sleep") as sleep:
        result = main.run({"duration_seconds": value})

    sleep.assert_not_called()
    assert result["ok"] is False
    assert result["error_info"]["code"] == "INVALID_DURATION"
    assert result["error_info"]["details"] == {
        "minimum_seconds": 0.1,
        "maximum_seconds": 3600.0,
    }


def test_contract_limits_match_program_and_outer_timeout() -> None:
    input_schema = json.loads(
        (TOOL_ROOT / ".tool" / "input.schema.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (TOOL_ROOT / ".tool" / "tool.json").read_text(encoding="utf-8")
    )
    duration_schema = input_schema["properties"]["duration_seconds"]

    assert duration_schema["minimum"] == main.MIN_WAIT_SECONDS
    assert duration_schema["maximum"] == main.MAX_WAIT_SECONDS
    assert manifest["runtime"]["timeout_seconds"] > main.MAX_WAIT_SECONDS
