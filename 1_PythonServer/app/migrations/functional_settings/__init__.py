"""Upgrade known persisted configuration contracts, preserving user customization."""

from copy import deepcopy
from datetime import UTC, datetime
from functools import lru_cache
import json
from pathlib import Path

from app.core.errors import BadRequestError
from app.infra.database.sqlite import database_connection
from app.migrations.runner import backup_database, check_integrity, schema_transaction


@lru_cache
def _history() -> dict:
    return json.loads(Path(__file__).with_name("defaults_history.json").read_text(encoding="utf-8"))


def _merge_missing(settings: dict, defaults: dict) -> dict:
    result = deepcopy(settings)
    for key, value in defaults.items():
        if key not in result:
            result[key] = deepcopy(value)
        elif isinstance(value, dict) and isinstance(result[key], dict):
            result[key] = _merge_missing(result[key], value)
    return result


def convert(profile: str, version: int, settings: dict) -> tuple[int, dict]:
    versions = _history()[profile]
    target = max(map(int, versions))
    if version == target:
        return version, settings
    if str(version) not in versions:
        raise BadRequestError(f"功能配置 {profile} 的版本 {version} 没有已知升级路径（当前 {target}）；原配置未被修改。")
    result = deepcopy(settings)
    for next_version in sorted(int(v) for v in versions if int(v) > version):
        defaults = versions[str(next_version)][-1]
        old_prompts = {item.get("prompt") for item in versions[str(version)]}
        # Only recognized shipped defaults follow a prompt revision; user text is exact.
        if "prompt" in result and result["prompt"] in old_prompts:
            result["prompt"] = defaults["prompt"]
        result = _merge_missing(result, defaults)
        version = next_version
    return version, result


def upgrade_profiles(database_path: Path, profile_key: str | None = None) -> None:
    with database_connection(database_path) as connection, schema_transaction(connection):
        rows = connection.execute("SELECT settings_id,version,settings_json FROM llm_functional_model_settings").fetchall()
        changes = []
        for key, version, raw in rows:
            if key not in _history() or (profile_key is not None and key != profile_key):
                continue
            target = max(map(int, _history()[key]))
            if version == target:
                continue
            settings = json.loads(raw)
            if not isinstance(settings, dict):
                raise BadRequestError(f"功能配置 {key} 格式损坏；原配置已保留。")
            target, converted = convert(key, version, settings)
            changes.append((target, json.dumps(converted, ensure_ascii=False, sort_keys=True),
                            datetime.now(UTC).isoformat(), key))
        if not changes:
            return
        check_integrity(connection)
        # These are record-level versions, independent of the global schema marker.
        backup_database(connection, "functional-settings", "current")
        connection.executemany(
            "UPDATE llm_functional_model_settings SET version=?,settings_json=?,updated_at=? WHERE settings_id=?",
            changes,
        )
        check_integrity(connection)
