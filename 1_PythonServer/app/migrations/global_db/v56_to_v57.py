"""Remove retired overview display modes from workspace preferences."""
from datetime import UTC, datetime
import json


def upgrade(connection):
    row = connection.execute(
        "SELECT value FROM app_metadata WHERE key = 'workspace.layout_preferences'"
    ).fetchone()
    if row is not None:
        try:
            preferences = json.loads(row[0])
        except (ValueError, TypeError):
            preferences = None
        if isinstance(preferences, dict):
            preferences.pop("project_overview_layout_modes", None)
            preferences["version"] = 7
            connection.execute(
                "UPDATE app_metadata SET value = ? WHERE key = 'workspace.layout_preferences'",
                (json.dumps(preferences, ensure_ascii=False, separators=(",", ":")),),
            )
    connection.execute(
        "INSERT INTO schema_migrations VALUES (57, ?, ?)",
        ("project_overview_grid_only", datetime.now(UTC).isoformat()),
    )
