import json

import pytest

from app.infra.database import database_connection, database_transaction, run_database_migrations
from app.infra.database.schema import MIGRATIONS
from app.services.application.knowledge_workspace_migration import migrate_knowledge_workspace


def test_knowledge_workspace_migration_preserves_project_data(tmp_path) -> None:
    legacy_root = tmp_path / "literature"
    project_root = legacy_root / "knowledge-project"
    project_root.mkdir(parents=True)
    (project_root / "source.pdf").write_bytes(b"knowledge-source")
    (legacy_root / "catalog.json").write_text(
        json.dumps({
            "schema_version": 1,
            "metadata": {},
            "categories": [{
                "category_id": "default-literature-category",
                "name": "基础文献",
                "is_default": True,
                "sort_order": 0,
                "created_at": "old",
                "updated_at": "old",
            }],
            "projects": [{
                "project_id": "knowledge-project",
                "name": "新建文献 2",
                "category_id": "default-literature-category",
                "is_default": False,
                "sort_order": 0,
                "created_at": "old",
                "updated_at": "old",
            }],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    knowledge_root = tmp_path / "knowledge"
    migrate_knowledge_workspace(knowledge_root)
    migrate_knowledge_workspace(knowledge_root)

    assert not legacy_root.exists()
    assert (knowledge_root / "knowledge-project" / "source.pdf").read_bytes() == b"knowledge-source"
    catalog = json.loads((knowledge_root / "catalog.json").read_text(encoding="utf-8"))
    assert catalog["categories"][0]["category_id"] == "default-knowledge-category"
    assert catalog["categories"][0]["name"] == "基础知识"
    assert catalog["projects"][0]["category_id"] == "default-knowledge-category"
    assert catalog["projects"][0]["name"] == "新建知识 2"


def test_knowledge_workspace_migration_refuses_to_merge_two_roots(tmp_path) -> None:
    (tmp_path / "literature").mkdir()
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    (knowledge_root / "user-file.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(RuntimeError, match="新旧目录同时存在"):
        migrate_knowledge_workspace(tmp_path / "knowledge")


def test_knowledge_workspace_migration_replaces_generated_empty_catalog(tmp_path) -> None:
    legacy_root = tmp_path / "literature"
    legacy_root.mkdir()
    (legacy_root / "catalog.json").write_text(
        json.dumps({"categories": [], "projects": []}),
        encoding="utf-8",
    )
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    (knowledge_root / "catalog.json").write_text(
        json.dumps({
            "categories": [{"category_id": "default-knowledge-category"}],
            "projects": [],
        }),
        encoding="utf-8",
    )

    migrate_knowledge_workspace(knowledge_root)

    assert not legacy_root.exists()
    assert knowledge_root.is_dir()


def test_database_migration_renames_legacy_literature_contract(tmp_path) -> None:
    database_path = tmp_path / "tiance.db"
    run_database_migrations(
        database_path,
        tuple(migration for migration in MIGRATIONS if migration.version <= 47),
    )
    with database_transaction(database_path) as connection:
        connection.execute(
            """
            INSERT INTO project_categories (
                category_id, name, is_default, sort_order,
                created_at, updated_at, category_kind
            ) VALUES (?, ?, 1, 0, 'old', 'old', 'literature')
            """,
            ("default-literature-category", "基础文献"),
        )
        connection.execute(
            """
            INSERT INTO projects (
                project_id, name, root_path, category_id, is_default,
                sort_order, created_at, updated_at, project_kind
            ) VALUES (?, ?, ?, ?, 0, 0, 'old', 'old', 'literature')
            """,
            (
                "knowledge-project",
                "新建文献",
                str(tmp_path / "literature" / "knowledge-project"),
                "default-literature-category",
            ),
        )

    run_database_migrations(database_path, MIGRATIONS)

    with database_connection(database_path) as connection:
        category = connection.execute(
            """
            SELECT category_id, name, category_kind
            FROM project_categories
            WHERE category_id = 'default-knowledge-category'
            """
        ).fetchone()
        project = connection.execute(
            """
            SELECT name, root_path, category_id, project_kind
            FROM projects
            WHERE project_id = 'knowledge-project'
            """
        ).fetchone()
    assert tuple(category) == ("default-knowledge-category", "基础知识", "knowledge")
    assert project[0] == "新建知识"
    assert "knowledge" in project[1]
    assert project[2] == "default-knowledge-category"
    assert project[3] == "knowledge"
