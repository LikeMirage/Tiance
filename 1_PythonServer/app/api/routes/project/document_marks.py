"""Small, independent text annotations owned by each project."""
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

from app.core.errors import BadRequestError
from app.services.project import get_project_file_service

router = APIRouter(prefix="/projects", tags=["projects"])


class DocumentMark(BaseModel):
    id: UUID
    surface: Literal["source", "preview"]
    start: int = Field(ge=0)
    length: int = Field(gt=0)
    startLine: int = Field(ge=1)
    endLine: int = Field(ge=1)
    head: str = Field(min_length=1, max_length=48)
    tail: str = Field(min_length=1, max_length=48)
    before: str = Field(max_length=32)
    after: str = Field(max_length=32)
    digest: str = Field(pattern=r"^[0-9a-f]{16}$")


class MarkChanges(BaseModel):
    add: list[DocumentMark] = Field(default_factory=list)
    remove: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def distinct_operations(self):
        if {mark.id for mark in self.add}.intersection(self.remove):
            raise ValueError("Conflicting annotation operations")
        return self


def _location(project_id: str, path: str) -> tuple[Path, str]:
    files = get_project_file_service()
    root = Path(files.get_project_root(project_id)).resolve()
    document = Path(files.get_file_path(project_id, target_path=path)).resolve()
    db = root / ".Tiance" / "document-marks.sqlite3"
    if not db.resolve().is_relative_to(root) or not document.is_relative_to(root):
        raise BadRequestError("勾选文件路径超出项目目录。")
    return db, os.path.normcase(str(document.relative_to(root))).replace("\\", "/")


@router.get("/{project_id}/document-marks")
def list_marks(project_id: str, path: str) -> list[dict]:
    db, key = _location(project_id, path)
    if not db.is_file():
        return []
    with closing(sqlite3.connect(db, timeout=5)) as conn:
        # A concurrent first writer may still be creating the schema.
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='marks'").fetchone():
            return []
        return [json.loads(row[0]) for row in conn.execute(
            "SELECT payload FROM marks WHERE document=? ORDER BY rowid", (key,)
        )]


@router.patch("/{project_id}/document-marks")
def change_marks(project_id: str, path: str, changes: MarkChanges) -> dict:
    db, key = _location(project_id, path)
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db, timeout=5)) as conn, conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS marks (
            document TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(document, id))""")
        conn.executemany("INSERT OR IGNORE INTO marks VALUES(?,?,?)",
                         [(key, str(mark.id), mark.model_dump_json()) for mark in changes.add])
        conn.executemany("DELETE FROM marks WHERE document=? AND id=?",
                         [(key, str(mark_id)) for mark_id in changes.remove])
    return {"ok": True}
