from __future__ import annotations

from pathlib import Path
import subprocess

import uvicorn
from uvicorn.config import Config
from uvicorn.main import run as run_uvicorn
from uvicorn.server import Server

import run as server_entrypoint


def test_server_entrypoint_does_not_depend_on_uvicorn_package_reexports(
    monkeypatch,
) -> None:
    monkeypatch.delattr(uvicorn, "Config", raising=False)
    monkeypatch.delattr(uvicorn, "Server", raising=False)
    monkeypatch.delattr(uvicorn, "run", raising=False)

    loaded_config, loaded_server, loaded_run = server_entrypoint._load_uvicorn_runtime()

    assert loaded_config is Config
    assert loaded_server is Server
    assert loaded_run is run_uvicorn


def test_embedded_backend_runtime_contains_uvicorn_implementation() -> None:
    project_root = Path(__file__).resolve().parents[2]
    embedded_python = project_root / "Data" / "runtime" / "python" / "py313" / "python.exe"
    backend_packages = (
        project_root
        / "Data"
        / "runtime"
        / "python-packages"
        / "backend"
        / "py313"
        / "site-packages"
    )
    if not embedded_python.is_file():
        return

    completed = subprocess.run(
        [
            str(embedded_python),
            "-c",
            (
                "import sys; "
                f"sys.path.insert(0, {str(backend_packages)!r}); "
                "from uvicorn.config import Config; "
                "from uvicorn.server import Server; "
                "from uvicorn.main import run"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
