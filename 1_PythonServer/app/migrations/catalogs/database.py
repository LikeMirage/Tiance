"""Import every legacy project kind atomically per catalog, retaining source rows."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3

from app.domain.project import ProjectKind
from app.migrations.files import write_json
from app.repositories.project.project_repository import ProjectRepository

_MARKER = "migration.database_catalog.v1"


def migrate_project_catalogs(database_path: Path, repository: ProjectRepository) -> None:
    with closing(sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        has_tables = {"projects", "project_categories"} <= tables
        if not has_tables and tables & {"projects", "project_categories"}:
            raise RuntimeError("Legacy project catalog tables are incomplete; source data was retained.")
        flag = db.execute("SELECT value FROM app_metadata WHERE key='projects.default_project_bootstrapped'").fetchone()
        for kind in ProjectKind:
            catalog = repository.get_file_catalog(kind)
            if catalog is None:
                continue
            categories = [dict(row) for row in db.execute(
                "SELECT * FROM project_categories WHERE category_kind=? ORDER BY sort_order,created_at,category_id", (kind.value,))] if has_tables else []
            projects = [dict(row) for row in db.execute(
                "SELECT * FROM projects WHERE project_kind=? ORDER BY sort_order,created_at,project_id", (kind.value,))] if has_tables else []
            preserve_empty = kind is ProjectKind.PROJECT and flag is not None and flag[0] == "1"
            if not categories and not projects and not preserve_empty:
                continue
            with catalog._write_lock:
                payload = catalog._read_payload()
                if payload["metadata"].get(_MARKER) == "1":
                    continue
                existing_project_ids = {row["project_id"] for row in payload["projects"]}
                for category in categories:
                    category.pop("category_kind", None)
                    category["is_default"] = bool(category["is_default"])
                for project in projects:
                    project.pop("project_kind", None)
                    project["is_default"] = bool(project["is_default"])
                    root = Path(project.pop("root_path")).resolve()
                    # Literature paths moved before import; preserve the actual project folder name.
                    if kind is ProjectKind.KNOWLEDGE and root.parent.name == "literature":
                        root = catalog.root_path / root.name
                    if root.parent == catalog.root_path:
                        if root.name != project["project_id"]:
                            project["root_name"] = root.name
                    elif kind is ProjectKind.PROJECT:
                        project["root_path"] = str(root)
                    else:
                        raise RuntimeError(f"Legacy {kind.value} project root is outside its collection: {root}")
                for field, key, incoming in (("categories", "category_id", categories), ("projects", "project_id", projects)):
                    existing = {row[key]: row for row in payload[field]}
                    for row in incoming:
                        if row[key] in existing:
                            # A successfully written current catalog is authoritative; no old-data overwrite.
                            continue
                        payload[field].append(row)
                category_ids = {row["category_id"] for row in payload["categories"]}
                if any(row["category_id"] not in category_ids for row in payload["projects"]):
                    raise RuntimeError(f"Legacy {kind.value} project refers to a missing category.")
                if kind is ProjectKind.PROJECT:
                    if projects or preserve_empty:
                        payload["metadata"]["projects.default_project_bootstrapped"] = "1"
                    raw = db.execute("SELECT value FROM app_metadata WHERE key='projects.order'").fetchone()
                    if raw:
                        order = json.loads(raw[0])
                        if not isinstance(order, list) or not all(isinstance(v, str) for v in order):
                            raise RuntimeError("Legacy project order must be a list of project IDs.")
                        ranks = {value: index for index, value in enumerate(order)}
                        for row in payload["projects"]:
                            if row["project_id"] in ranks and row["project_id"] not in existing_project_ids:
                                row["sort_order"] = ranks[row["project_id"]]
                payload["metadata"][_MARKER] = "1"
                # Validate before replacement using the same current catalog contract.
                decoded_categories = [catalog._category_from_payload(row) for row in payload["categories"]]
                decoded_projects = [catalog._project_from_payload(row) for row in payload["projects"]]
                if sum(row.is_default for row in decoded_categories) > 1 or sum(row.is_default for row in decoded_projects) > 1:
                    raise RuntimeError(f"Legacy {kind.value} catalog has conflicting default records.")
                if len({row.root_path for row in decoded_projects}) != len(decoded_projects):
                    raise RuntimeError(f"Legacy {kind.value} catalog has duplicate project roots.")
                write_json(catalog.catalog_path, payload)
                catalog._index = None
