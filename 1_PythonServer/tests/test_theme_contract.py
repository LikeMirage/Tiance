import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.themes import ThemePackageDefinition
from app.domain.project import Project, ProjectKind
from app.infra.database import (
    database_transaction,
    ensure_database_schema,
    run_database_migrations,
)
from app.infra.database.schema import MIGRATIONS
from app.services.themes import theme_catalog
from tests.formal_tool_paths import resolve_formal_tool_root


PROJECT_ROOT = Path(__file__).resolve().parents[2]
THEMES_ROOT = PROJECT_ROOT / "Data" / "themes"
THEME_BACKUPS_ROOT = (
    resolve_formal_tool_root("theme_designer")
    / "assets/theme_backups"
)
EMBEDDED_RECOVERY_ROOT = PROJECT_ROOT / "1_PythonServer" / "app" / "resources" / "themes"


def test_all_theme_packages_and_builtin_backups_follow_current_contract() -> None:
    theme_files = sorted(THEMES_ROOT.glob("*/theme.json"))
    backup_files = sorted(THEME_BACKUPS_ROOT.glob("*.json"))

    assert theme_files
    assert {path.stem for path in backup_files} == {"dark-gold", "light"}

    for path in [*theme_files, *backup_files]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        theme = ThemePackageDefinition.model_validate(payload)
        expected_id = path.parent.name if path.name == "theme.json" else path.stem

        assert theme.schema_version == 2
        assert theme.id == expected_id
        assert 1 <= theme.tokens.structure.width <= 2

    for backup_path in backup_files:
        embedded_path = EMBEDDED_RECOVERY_ROOT / backup_path.name
        assert json.loads(embedded_path.read_text(encoding="utf-8")) == json.loads(
            backup_path.read_text(encoding="utf-8")
        )


def test_structure_tokens_are_required_per_theme() -> None:
    source_path = next(iter(sorted(THEMES_ROOT.glob("*/theme.json"))))
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    payload["tokens"].pop("structure")

    with pytest.raises(ValidationError):
        ThemePackageDefinition.model_validate(payload)


def test_theme_project_is_opened_by_project_id(monkeypatch, tmp_path) -> None:
    source_path = next(iter(sorted(THEMES_ROOT.glob("*/theme.json"))))
    theme_root = tmp_path / "theme-project"
    theme_root.mkdir()
    target_path = theme_root / "theme.json"
    target_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
    project = Project(
        project_id="theme-project-id",
        name="项目主题名",
        root_path=str(theme_root),
        category_id="themes",
        project_kind=ProjectKind.THEME,
        is_default=False,
        sort_order=0,
        created_at="now",
        updated_at="now",
    )
    renamed = []

    class FakeProjectService:
        def list_projects(self):
            return (project,)

        def rename_project(self, project_id, *, name):
            renamed.append((project_id, name))
            return project

    monkeypatch.setattr(theme_catalog, "get_project_service", FakeProjectService)

    loaded = theme_catalog.get_theme(project.project_id)
    saved = theme_catalog.save_theme(
        project.project_id,
        loaded.model_copy(update={"name": "新主题名"}),
    )

    assert loaded.id == source_path.parent.name
    assert loaded.name == project.name
    assert renamed == [(project.project_id, "新主题名")]
    assert saved.id == loaded.id
    saved_package = ThemePackageDefinition.model_validate_json(
        target_path.read_text(encoding="utf-8")
    )
    source_package = ThemePackageDefinition.model_validate_json(
        source_path.read_text(encoding="utf-8")
    )
    assert saved_package.registration_name == source_package.registration_name


def test_schema_migration_removes_only_legacy_active_theme_metadata(tmp_path) -> None:
    database_path = tmp_path / "tiance.db"
    run_database_migrations(
        database_path,
        tuple(migration for migration in MIGRATIONS if migration.version <= 44),
    )
    with database_transaction(database_path) as connection:
        connection.executemany(
            "INSERT INTO app_metadata (key, value, updated_at) VALUES (?, ?, ?)",
            (
                ("theme.active_theme_id", "legacy-theme", "now"),
                ("workspace.last_opened", "{}", "now"),
            ),
        )

    ensure_database_schema(database_path)

    with database_transaction(database_path) as connection:
        rows = connection.execute(
            "SELECT key, value FROM app_metadata ORDER BY key"
        ).fetchall()
        migration = connection.execute(
            "SELECT name FROM schema_migrations WHERE version = 45"
        ).fetchone()

    assert [(row["key"], row["value"]) for row in rows] == [
        ("workspace.last_opened", "{}")
    ]
    assert migration["name"] == "remove_legacy_active_theme_metadata"
