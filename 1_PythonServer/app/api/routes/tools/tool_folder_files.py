import mimetypes

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import FileResponse

from app.core.errors import BadRequestError
from app.schemas.tools import (
    ToolFolderFileContentResponse,
    ToolFolderFileContentSaveRequest,
    ToolFolderFileCopyRequest,
    ToolFolderFileCreateRequest,
    ToolFolderFileMoveRequest,
    ToolFolderFileNodeResponse,
    ToolFolderFileOpenExternalRequest,
    ToolFolderFileOpenExternalResponse,
    ToolFolderFileRenameRequest,
    ToolFolderFileRevealRequest,
    ToolFolderFileTreeResponse,
)
from app.services.tools import get_tool_folder_file_service

router = APIRouter(prefix="/tools/categories", tags=["tools"])


@router.get(
    "/{category_id}/projects/{project_id}/files",
    response_model=ToolFolderFileTreeResponse,
    summary="List files in a tool folder",
)
def list_tool_folder_files(
    category_id: str,
    project_id: str,
    query: str | None = Query(default=None, description="按文件名递归搜索"),
    parent_path: str | None = Query(default=None, description="仅列出该目录下一层"),
) -> ToolFolderFileTreeResponse:
    service = get_tool_folder_file_service()
    tree = service.list_tree_result(
        category_id,
        project_id,
        query=query,
        parent_path=parent_path,
    )
    items = [ToolFolderFileNodeResponse.from_domain(node) for node in tree.items]
    return ToolFolderFileTreeResponse(
        category_id=category_id,
        project_id=project_id,
        parent_path=parent_path,
        items=items,
    )


@router.post(
    "/{category_id}/projects/{project_id}/files",
    response_model=ToolFolderFileNodeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a file or folder in a tool folder",
)
def create_tool_folder_file(
    category_id: str,
    project_id: str,
    payload: ToolFolderFileCreateRequest,
) -> ToolFolderFileNodeResponse:
    service = get_tool_folder_file_service()
    node = service.create_entry(
        category_id,
        project_id,
        parent_path=payload.parent_path,
        kind=payload.kind,
        name=payload.name,
    )
    return ToolFolderFileNodeResponse.from_domain(node)


@router.patch(
    "/{category_id}/projects/{project_id}/files",
    response_model=ToolFolderFileNodeResponse,
    summary="Rename a tool folder file or folder",
)
def rename_tool_folder_file(
    category_id: str,
    project_id: str,
    payload: ToolFolderFileRenameRequest,
) -> ToolFolderFileNodeResponse:
    service = get_tool_folder_file_service()
    node = service.rename_entry(
        category_id,
        project_id,
        target_path=payload.path,
        name=payload.name,
    )
    return ToolFolderFileNodeResponse.from_domain(node)


@router.delete(
    "/{category_id}/projects/{project_id}/files",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a tool folder file or folder",
)
def delete_tool_folder_file(
    category_id: str,
    project_id: str,
    path: str = Query(..., description="要删除的文件或文件夹路径"),
) -> Response:
    service = get_tool_folder_file_service()
    service.delete_entry(category_id, project_id, target_path=path)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{category_id}/projects/{project_id}/files/move",
    response_model=ToolFolderFileNodeResponse,
    summary="Move a tool folder file or folder",
)
def move_tool_folder_file(
    category_id: str,
    project_id: str,
    payload: ToolFolderFileMoveRequest,
) -> ToolFolderFileNodeResponse:
    service = get_tool_folder_file_service()
    node = service.move_entry(
        category_id,
        project_id,
        target_path=payload.path,
        target_parent_path=payload.target_parent_path,
    )
    return ToolFolderFileNodeResponse.from_domain(node)


@router.post(
    "/{category_id}/projects/{project_id}/files/copy",
    response_model=ToolFolderFileNodeResponse,
    summary="Copy a tool folder file or folder",
)
def copy_tool_folder_file(
    category_id: str,
    project_id: str,
    payload: ToolFolderFileCopyRequest,
) -> ToolFolderFileNodeResponse:
    service = get_tool_folder_file_service()
    node = service.copy_entry(
        category_id,
        project_id,
        target_path=payload.path,
        target_parent_path=payload.target_parent_path,
    )
    return ToolFolderFileNodeResponse.from_domain(node)


@router.post(
    "/{category_id}/projects/{project_id}/files/reveal",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reveal a tool folder file or folder in file explorer",
)
def reveal_tool_folder_file(
    category_id: str,
    project_id: str,
    payload: ToolFolderFileRevealRequest,
) -> Response:
    service = get_tool_folder_file_service()
    service.reveal_entry(category_id, project_id, target_path=payload.path)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{category_id}/projects/{project_id}/files/open-external",
    response_model=ToolFolderFileOpenExternalResponse,
    summary="Open a tool folder file with local Office/WPS or the default application",
)
def open_tool_folder_file_external(
    category_id: str,
    project_id: str,
    payload: ToolFolderFileOpenExternalRequest,
) -> ToolFolderFileOpenExternalResponse:
    service = get_tool_folder_file_service()
    result = service.open_entry_external(category_id, project_id, target_path=payload.path)
    return ToolFolderFileOpenExternalResponse(
        category_id=category_id,
        project_id=project_id,
        path=payload.path,
        app_name=result.app_name,
        used_default_app=result.used_default_app,
    )


@router.get(
    "/{category_id}/projects/{project_id}/files/content",
    response_model=ToolFolderFileContentResponse,
    summary="Read a tool folder file's content",
)
def read_tool_folder_file_content(
    category_id: str,
    project_id: str,
    path: str = Query(..., description="文件路径"),
) -> ToolFolderFileContentResponse:
    service = get_tool_folder_file_service()
    content, mtime_ms = service.read_editor_text_file(category_id, project_id, target_path=path)
    return ToolFolderFileContentResponse(
        category_id=category_id,
        project_id=project_id,
        path=path,
        content=content,
        mtime_ms=mtime_ms,
    )


@router.get(
    "/{category_id}/projects/{project_id}/files/asset",
    summary="Read a tool folder media asset",
)
def read_tool_folder_file_asset(
    category_id: str,
    project_id: str,
    path: str = Query(..., description="媒体文件路径"),
) -> FileResponse:
    service = get_tool_folder_file_service()
    file_path = service.get_file_path(category_id, project_id, target_path=path)
    media_type = _asset_media_type(file_path)
    return FileResponse(
        file_path,
        media_type=media_type,
        headers={"Cache-Control": "no-store"},
    )


@router.put(
    "/{category_id}/projects/{project_id}/files/content",
    response_model=ToolFolderFileNodeResponse,
    summary="Write content to a tool folder file",
)
def save_tool_folder_file_content(
    category_id: str,
    project_id: str,
    path: str = Query(..., description="文件路径"),
    payload: ToolFolderFileContentSaveRequest = ...,  # type: ignore
) -> ToolFolderFileNodeResponse:
    service = get_tool_folder_file_service()
    node = service.write_text_file(
        category_id,
        project_id,
        target_path=path,
        content=payload.content,
        expected_mtime_ms=payload.expected_mtime_ms,
    )
    return ToolFolderFileNodeResponse.from_domain(node)


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
