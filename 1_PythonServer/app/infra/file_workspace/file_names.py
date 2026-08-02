from pathlib import Path


def is_internal_write_temp_path(path: str | Path) -> bool:
    name = Path(path).name
    parts = name.rsplit(".", 2)
    return len(parts) == 3 and parts[0].startswith(".") and parts[2] == "tmp" and _is_hex_uuid(parts[1])


def _is_hex_uuid(value: str) -> bool:
    return len(value) == 32 and all(char in "0123456789abcdef" for char in value)
