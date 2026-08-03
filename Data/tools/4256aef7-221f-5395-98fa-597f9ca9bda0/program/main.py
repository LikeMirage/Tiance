from __future__ import annotations

import sys
from typing import Any

from package_environment import EnvironmentError, resolve_runtime_paths
from package_operations import execute_request
from package_spec import InputError, parse_request
from package_target import resolve_package_target
from result_payload import failure
from tiance_runtime import run_tool


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        request = parse_request(payload)
        runtime_paths = resolve_runtime_paths(sys.executable)
        target = resolve_package_target(request, runtime_paths)
        return execute_request(request, runtime_paths, target)
    except InputError as exc:
        return failure(exc.code, exc.message, exc.details)
    except EnvironmentError as exc:
        return failure(exc.code, exc.message, exc.details)
    except Exception as exc:
        return failure("UNEXPECTED_ERROR", str(exc) or exc.__class__.__name__)


if __name__ == "__main__":
    run_tool(run)
