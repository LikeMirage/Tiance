"""Authenticated editor access to explicitly referenced local files."""
from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.errors import BadRequestError
from app.infra.file_workspace import get_file_workspace_storage
from app.schemas.project import ProjectFileContentSaveRequest, ProjectFileNodeResponse
from app.services.editor_local_files import local_path, read_local_text, resolve_file_reference
from app.services.file_preview.assets import asset_media_type
from app.services.file_preview.runtime import preview_file, validate_asset_version

router = APIRouter(prefix="/editor", tags=["editor"])


class FileReferenceRequest(BaseModel):
    path: str
    kind: Literal["file", "folder"] = "file"
    source: Literal["project_file", "external_path"]
    project_id: str | None = None
    session_id: str | None = None
    owner_project_id: str


@router.post("/file-references/resolve")
def resolve_reference(payload: FileReferenceRequest) -> dict:
    return resolve_file_reference(**payload.model_dump())


@router.get("/local/files/content")
def read_content(path: str) -> dict:
    return read_local_text(path)


@router.put("/local/files/content", response_model=ProjectFileNodeResponse)
def save_content(path: str, payload: ProjectFileContentSaveRequest) -> ProjectFileNodeResponse:
    target = local_path(path, must_exist=False)
    try:
        node = get_file_workspace_storage().write_text_file(
            str(target.parent), target.name, payload.content, payload.expected_mtime_ms,
        )
    except PermissionError as exc:
        raise BadRequestError("没有写入这个文件的权限。") from exc
    return ProjectFileNodeResponse.from_domain(node)


@router.get("/local/files/metadata")
def read_metadata(path: str) -> dict:
    target = local_path(path)
    return {"mtime_ms": int(target.stat().st_mtime * 1000)}


@router.get("/local/files/asset")
def read_asset(path: str, preview_version: str | None = None) -> FileResponse:
    target = local_path(path)
    validate_asset_version(target, preview_version)
    return FileResponse(target, media_type=asset_media_type(target), headers={"Cache-Control": "no-store"})


@router.get("/local/files/preview")
async def inspect_preview(request: Request, path: str,
                          encoding: str = Query("auto", max_length=16),
                          delimiter: str = Query("auto", max_length=16)) -> dict:
    return await preview_file(request, local_path(path), encoding=encoding, delimiter=delimiter)


@router.get("/local/files/preview/spreadsheet")
async def read_spreadsheet(request: Request, path: str, version: str,
                           sheet: int = Query(0, ge=0), row: int = Query(0, ge=0, lt=1048576),
                           column: int = Query(0, ge=0, lt=16384),
                           encoding: str = Query("auto", max_length=16),
                           delimiter: str = Query("auto", max_length=16)) -> dict:
    target = local_path(path)
    validate_asset_version(target, version)
    return await preview_file(request, target, "spreadsheet", version=version, sheet=sheet,
                              row=row, column=column, encoding=encoding, delimiter=delimiter)


@router.get("/local/files/preview/word")
async def read_word(request: Request, path: str, version: str, chunk: int = Query(0, ge=0)) -> dict:
    target = local_path(path)
    validate_asset_version(target, version)
    return await preview_file(request, target, "word", version=version, chunk=chunk)
