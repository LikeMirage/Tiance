from __future__ import annotations

import socket


PORT_PROBE_TIMEOUT_SECONDS = 0.05


def is_port_open(
    host: str,
    port: int,
    timeout: float = PORT_PROBE_TIMEOUT_SECONDS,
) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
