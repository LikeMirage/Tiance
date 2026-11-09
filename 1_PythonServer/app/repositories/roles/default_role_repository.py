"""Collection defaults are user settings, separate from functional model profiles."""
from functools import lru_cache
import json
from pathlib import Path

from app.core.config import get_settings
from app.domain.project import ProjectKind
from app.infra.database.sqlite import database_connection, database_transaction


class DefaultRoleRepository:
    def __init__(self, database_path: Path, *, initial_defaults_path: Path | None = None) -> None:
        self._database_path = database_path
        self._initial_defaults_path = initial_defaults_path

    def get_all(self) -> dict[str, str]:
        with database_connection(self._database_path) as connection:
            saved = dict(connection.execute(
                "SELECT project_kind, role_project_id FROM collection_default_roles"
            ).fetchall())
        # Public installation defaults are data, not role names or IDs in code.
        # Migrated and explicitly saved choices always take precedence.
        if all(kind.value in saved for kind in ProjectKind) or self._initial_defaults_path is None:
            return saved
        try:
            payload = json.loads(self._initial_defaults_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return saved
        if (not isinstance(payload, dict) or payload.get("schemaVersion") != 1
                or set(payload) != {"schemaVersion", "defaults"}
                or not isinstance(payload["defaults"], dict)):
            raise ValueError("初始默认角色配置格式错误。")
        initial = payload["defaults"]
        if any(key not in {kind.value for kind in ProjectKind}
               or not isinstance(value, str) or not value.strip()
               for key, value in initial.items()):
            raise ValueError("初始默认角色配置包含无效的项目集或角色 ID。")
        return {**{key: value.strip() for key, value in initial.items()}, **saved}

    def save(self, project_kind: ProjectKind, role_project_id: str) -> None:
        # Update one collection only; simultaneous edits to other collections survive.
        with database_transaction(self._database_path) as connection:
            connection.execute(
                "INSERT INTO collection_default_roles (project_kind, role_project_id) VALUES (?, ?) "
                "ON CONFLICT(project_kind) DO UPDATE SET role_project_id=excluded.role_project_id",
                (project_kind.value, role_project_id),
            )


@lru_cache
def get_default_role_repository() -> DefaultRoleRepository:
    settings = get_settings()
    return DefaultRoleRepository(
        settings.app_database_file,
        initial_defaults_path=settings.roles_data_path / "initial-defaults.json",
    )
