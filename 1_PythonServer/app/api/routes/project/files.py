import json
import mimetypes

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import FileResponse, StreamingResponse

from app.core.errors import BadRequestError
from app.schemas.project import (
    ProjectFileCopyRequest,
    ProjectFileContentResponse,
    ProjectFileContentSaveRequest,
    ProjectFileCreateRequest,
    ProjectMarkdownToDocxRequest,
    ProjectMarkdownToDocxResponse,
    ProjectFileMoveRequest,
    ProjectFileNodeResponse,
    ProjectFileOpenExternalRequest,
    ProjectFileOpenExternalResponse,
    ProjectFileRenameRequest,
    ProjectFileRevealRequest,
    ProjectFileTreeResponse,
    ProjectImageUploadRequest,
    ProjectImageUploadResponse,
    ProjectUserFileUploadRequest,
    ProjectUserFileUploadResponse,
)
from app.services.project import get_project_file_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get(
    "/{project_id}/files",
    response_model=ProjectFileTreeResponse,
    summary="List project files",
)
def list_project_files(
    project_id: str,
    query: str | None = Query(default=None, description="按文件名递归搜索"),
    parent_path: str | None = Query(default=None, description="仅列出该目录下一层"),
) -> ProjectFileTreeResponse:
    service = get_project_file_service()
    tree = service.list_tree_result(project_id, query=query, parent_path=parent_path)
    items = [ProjectFileNodeResponse.from_domain(node) for node in tree.items]
    return ProjectFileTreeResponse(
        project_id=project_id,
        parent_path=parent_path,
        items=items,
    )


@router.get(
    "/{project_id}/files/events",
    summary="Watch project file changes",
)
async def watch_project_files(project_id: str) -> StreamingResponse:
    service = get_project_file_service()
    file_changes = service.watch_file_changes(project_id)

    async def event_generator():
        async for event in file_changes:
            payload = {"kind": event.kind}
            if event.kind == "changed":
                payload["paths"] = event.paths
            yield _sse_event(payload)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/{project_id}/files",
    response_model=ProjectFileNodeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a file or folder in project",
)
def create_project_file(project_id: str, payload: ProjectFileCreateRequest) -> ProjectFileNodeResponse:
    service = get_project_file_service()
    node = service.create_entry(
        project_id,
        parent_path=payload.parent_path,
        kind=payload.kind,
        name=payload.name,
    )
    return ProjectFileNodeResponse.from_domain(node)


@router.patch(
    "/{project_id}/files",
    response_model=ProjectFileNodeResponse,
    summary="Rename a project file or folder",
)
def rename_project_file(
    project_id: str,
    payload: ProjectFileRenameRequest,
) -> ProjectFileNodeResponse:
    service = get_project_file_service()
    node = service.rename_entry(
        project_id,
        target_path=payload.path,
        name=payload.name,
    )
    return ProjectFileNodeResponse.from_domain(node)


@router.delete(
    "/{project_id}/files",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project file or folder",
)
def delete_project_file(
    project_id: str,
    path: str = Query(..., description="要删除的文件或文件夹的路径"),
) -> Response:
    service = get_project_file_service()
    service.delete_entry(project_id, target_path=path)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{project_id}/files/move",
    response_model=ProjectFileNodeResponse,
    summary="Move a project file or folder",
)
def move_project_file(
    project_id: str,
    payload: ProjectFileMoveRequest,
) -> ProjectFileNodeResponse:
    service = get_project_file_service()
    node = service.move_entry(
        project_id,
        target_path=payload.path,
        target_parent_path=payload.target_parent_path,
    )
    return ProjectFileNodeResponse.from_domain(node)


@router.post(
    "/{project_id}/files/copy",
    response_model=ProjectFileNodeResponse,
    summary="Copy a project file or folder",
)
def copy_project_file(
    project_id: str,
    payload: ProjectFileCopyRequest,
) -> ProjectFileNodeResponse:
    service = get_project_file_service()
    node = service.copy_entry(
        project_id,
        target_path=payload.path,
        target_parent_path=payload.target_parent_path,
    )
    return ProjectFileNodeResponse.from_domain(node)


@router.post(
    "/{project_id}/files/reveal",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reveal a project file or folder in file explorer",
)
def reveal_project_file(
    project_id: str,
    payload: ProjectFileRevealRequest,
) -> Response:
    service = get_project_file_service()
    service.reveal_entry(project_id, target_path=payload.path)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{project_id}/files/open-external",
    response_model=ProjectFileOpenExternalResponse,
    summary="Open a project file with local Office/WPS or the default application",
)
def open_project_file_external(
    project_id: str,
    payload: ProjectFileOpenExternalRequest,
) -> ProjectFileOpenExternalResponse:
    service = get_project_file_service()
    result = service.open_entry_external(project_id, target_path=payload.path)
    return ProjectFileOpenExternalResponse(
        project_id=project_id,
        path=payload.path,
        app_name=result.app_name,
        used_default_app=result.used_default_app,
    )


@router.get(
    "/{project_id}/files/content",
    response_model=ProjectFileContentResponse,
    summary="Read a project file's content",
)
def read_project_file_content(
    project_id: str,
    path: str = Query(..., description="文件路径"),
) -> ProjectFileContentResponse:
    service = get_project_file_service()
    content, mtime_ms = service.read_text_file(project_id, target_path=path)
    return ProjectFileContentResponse(project_id=project_id, path=path, content=content, mtime_ms=mtime_ms)


@router.get(
    "/{project_id}/files/asset",
    summary="Read a project media asset",
)
def read_project_file_asset(
    project_id: str,
    path: str = Query(..., description="媒体文件路径"),
) -> FileResponse:
    service = get_project_file_service()
    file_path = service.get_file_path(project_id, target_path=path)
    media_type = _asset_media_type(file_path)
    return FileResponse(
        file_path,
        media_type=media_type,
        headers={"Cache-Control": "no-store"},
    )


@router.put(
    "/{project_id}/files/content",
    response_model=ProjectFileNodeResponse,
    summary="Write content to a project file",
)
def save_project_file_content(
    project_id: str,
    path: str = Query(..., description="文件路径"),
    payload: ProjectFileContentSaveRequest = ...,  # type: ignore
) -> ProjectFileNodeResponse:
    service = get_project_file_service()
    node = service.write_text_file(
        project_id,
        target_path=path,
        content=payload.content,
        expected_mtime_ms=payload.expected_mtime_ms,
    )
    return ProjectFileNodeResponse.from_domain(node)


@router.post(
    "/{project_id}/files/markdown-to-docx",
    response_model=ProjectMarkdownToDocxResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a Word document from current Markdown content",
)
def generate_project_markdown_docx(
    project_id: str,
    payload: ProjectMarkdownToDocxRequest,
) -> ProjectMarkdownToDocxResponse:
    service = get_project_file_service()
    node, warnings = service.convert_markdown_content_to_docx(
        project_id,
        target_path=payload.path,
        content=payload.content,
        page_orientation=payload.page_orientation,
        page_size=payload.page_size,
    )
    return ProjectMarkdownToDocxResponse(
        project_id=project_id,
        source_path=payload.path,
        output_path=node.path,
        node=ProjectFileNodeResponse.from_domain(node),
        warnings=list(warnings),
    )


@router.post(
    "/{project_id}/uploads/images",
    response_model=ProjectImageUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save a pasted image in project uploads",
)
def upload_project_image(
    project_id: str,
    payload: ProjectImageUploadRequest,
) -> ProjectImageUploadResponse:
    service = get_project_file_service()
    node, mime_type, size_bytes = service.save_uploaded_image(
        project_id,
        filename=payload.filename,
        mime_type=payload.mime_type,
        data_base64=payload.data_base64,
    )
    return ProjectImageUploadResponse(
        project_id=project_id,
        path=node.path,
        mime_type=mime_type,
        size_bytes=size_bytes,
        node=ProjectFileNodeResponse.from_domain(node),
    )


@router.post(
    "/{project_id}/uploads/files",
    response_model=ProjectUserFileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save a dropped file in project uploads",
)
def upload_project_user_file(
    project_id: str,
    payload: ProjectUserFileUploadRequest,
) -> ProjectUserFileUploadResponse:
    service = get_project_file_service()
    node, original_filename, mime_type, size_bytes = service.save_uploaded_file(
        project_id,
        filename=payload.filename,
        mime_type=payload.mime_type,
        data_base64=payload.data_base64,
    )
    return ProjectUserFileUploadResponse(
        project_id=project_id,
        path=node.path,
        original_filename=original_filename,
        mime_type=mime_type,
        size_bytes=size_bytes,
        node=ProjectFileNodeResponse.from_domain(node),
    )


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _asset_media_type(file_path) -> str:
    media_type, _ = mimetypes.guess_type(str(file_path))
    office_media_types = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xls": "application/vnd.ms-excel",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    extension = file_path.suffix.lower()
    if extension in office_media_types:
        return media_type or office_media_types[extension]
    if not media_type or (
        media_type != "application/pdf"
        and not media_type.startswith(("image/", "video/"))
    ):
        raise BadRequestError("仅支持读取图片、视频、PDF 或 Office 资源。")
    return media_type
