"""Convert old single-project workspace selection after catalogs are available."""

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
        if isinstance(payload.get("category_selections"), dict) and payload.get("active_category_id"):
            return
        identifier = payload.get("project_id")
        if not isinstance(identifier, str) or not identifier.strip():
            return
        project = repository.get_project(identifier.strip())
        if project is None:
            return
        selections = payload.setdefault("category_selections", {})
        if not isinstance(selections, dict):
            raise RuntimeError("Workspace category selections have an invalid format.")
        selections.setdefault(project.category_id, {key: payload.get(key) for key in ("project_id", "session_id", "updated_at")})
        if not payload.get("active_category_id"):
            payload["active_category_id"] = project.category_id
        backup_database(db, "workspace-selection", "current")
        db.execute("UPDATE app_metadata SET value=? WHERE key='workspace.last_opened'", (json.dumps(payload, ensure_ascii=False),))
