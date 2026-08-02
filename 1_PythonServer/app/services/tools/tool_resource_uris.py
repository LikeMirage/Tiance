from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse


PROJECT_RESOURCE_SCHEME = "tiance-project"
LOCAL_RESOURCE_SCHEME = "tiance-local"


def project_relative_path(value: object) -> str | None:
    parsed = _parse_resource_uri(value, PROJECT_RESOURCE_SCHEME)
    if parsed is None or parsed.netloc or not parsed.path.startswith("/"):
        return None
    decoded = unquote(parsed.path).lstrip("/")
    if not decoded or "\\" in decoded or "\x00" in decoded:
        return None
    raw_parts = decoded.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        return None
    path = PurePosixPath(decoded)
    if path.is_absolute():
        return None
    return path.as_posix()


def local_absolute_path(value: object) -> Path | None:
    parsed = _parse_resource_uri(value, LOCAL_RESOURCE_SCHEME, allow_netloc=True)
    if parsed is None or not parsed.path.startswith("/"):
        return None
    decoded_path = unquote(parsed.path)
    if "\x00" in decoded_path:
        return None

    if parsed.netloc:
        raw_path = f"//{unquote(parsed.netloc)}{decoded_path}"
    elif os.name == "nt" and re.match(r"^/[A-Za-z]:/", decoded_path):
        raw_path = decoded_path[1:]
    else:
        raw_path = decoded_path

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        return None
    return path.resolve(strict=False)


def canonical_local_resource_uri(value: object) -> str | None:
    path = local_absolute_path(value)
    if path is None:
        return None
    file_uri = path.as_uri()
    return f"{LOCAL_RESOURCE_SCHEME}:{file_uri.removeprefix('file:')}"


def _parse_resource_uri(
    value: object,
    scheme: str,
    *,
    allow_netloc: bool = False,
):
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlparse(value.strip())
    if (
        parsed.scheme.lower() != scheme
        or (parsed.netloc and not allow_netloc)
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        return None
    return parsed
