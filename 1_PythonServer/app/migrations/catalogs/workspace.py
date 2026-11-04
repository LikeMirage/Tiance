"""Normalize project navigation; session selection belongs to each project."""

import json
from pathlib import Path

from app.infra.database.sqlite import database_connection
from app.migrations.runner import backup_database, schema_transaction
from app.repositories.project.project_repository import ProjectRepository


def upgrade_workspace_selection(database_path: Path, repository: ProjectRepository) -> None:
    with database_connection(database_path) as db, schema_transaction(db):
        row = db.execute("SELECT value FROM app_metadata WHERE key='workspace.last_opened'").fetchone()
        if row is None:
            return
        payload = json.loads(row[0])
        if not isinstance(payload, dict):
            raise RuntimeError("Workspace selection is not an object; original data was retained.")
        selections = payload.get("category_selections", {})
        if not isinstance(selections, dict) or not all(isinstance(item, dict) for item in selections.values()):
            raise RuntimeError("Workspace category selections have an invalid format.")
        if not payload.get("active_category_id"):
            identifier = payload.get("project_id")
            project = repository.get_project(identifier.strip()) if isinstance(identifier, str) and identifier.strip() else None
            if project is not None:
                selections.setdefault(project.category_id, {key: payload.get(key) for key in ("project_id", "updated_at")})
                payload["category_selections"] = selections
                payload["active_category_id"] = project.category_id
        # Only this small global metadata row changes. Do not open project DBs
        # or overwrite their authoritative active_session_id with a stale hint.
        payload.pop("session_id", None)
        for selection in selections.values():
            selection.pop("session_id", None)
        updated = json.dumps(payload, ensure_ascii=False)
        if payload == json.loads(row[0]):
            return
        backup_database(db, "workspace-selection", "current")
        db.execute("UPDATE app_metadata SET value=? WHERE key='workspace.last_opened'", (updated,))
