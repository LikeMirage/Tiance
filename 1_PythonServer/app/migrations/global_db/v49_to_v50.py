"""Move the shared conversation role choice to independent collection defaults."""
from datetime import UTC, datetime
import json
import sqlite3


def upgrade(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE collection_default_roles (
        project_kind TEXT PRIMARY KEY,
        role_project_id TEXT NOT NULL
    )""")
    previous = connection.execute(
        "SELECT settings_json FROM llm_functional_model_settings WHERE settings_id='defaultConversation'"
    ).fetchone()
    if previous:
        payload = json.loads(previous[0])
        if not isinstance(payload, dict):
            raise ValueError("默认会话角色配置格式错误；原配置未被修改。")
        role_id = payload.get("roleProjectId", "")
        if not isinstance(role_id, str):
            raise ValueError("默认会话角色 ID 格式错误；原配置未被修改。")
        if role_id.strip():
            connection.executemany(
                "INSERT INTO collection_default_roles VALUES (?, ?)",
                ((kind, role_id.strip()) for kind in (
                    "project", "tool", "knowledge", "experience", "role", "provider", "theme",
                )),
            )
        connection.execute("DELETE FROM llm_functional_model_settings WHERE settings_id='defaultConversation'")
    connection.execute(
        "INSERT INTO schema_migrations(version, name, applied_at) VALUES (50, ?, ?)",
        ("collection_default_roles", datetime.now(UTC).isoformat()),
    )
