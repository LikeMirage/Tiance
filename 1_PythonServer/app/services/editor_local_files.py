"""Local editor files use the same text storage and preview pipeline as project files.

Paths here are explicit host paths, protected by the normal API authentication.
Project file endpoints retain their project-root boundary checks.
"""
from pathlib import Path

from app.core.errors import BadRequestError, NotFoundError
from app.infra.file_workspace import get_file_workspace_storage
from app.repositories.project.conversation_attachment_repository import (
    ATTACHMENT_URI_PREFIX, get_conversation_attachment_repository,
)
from app.services.file_workspace_text import read_editor_text_file
from app.services.project import get_project_file_service


def local_path(path: str, *, must_exist: bool = True) -> Path:
    target = Path(path)
    if not target.is_absolute():
        raise BadRequestError("本地文件必须使用绝对路径。")
    try:
        target = target.resolve()
        if must_exist and not target.is_file():
            raise NotFoundError("找不到文件，请检查路径或确认文件是否已移动、删除。")
        if not must_exist and target.exists() and not target.is_file():
            raise BadRequestError("保存目标不是文件。")
        return target
    except (OSError, ValueError) as exc:
        raise BadRequestError("无法访问这个本地文件。") from exc


def read_local_text(path: str) -> dict:
    target = local_path(path)
    try:
        content, mtime = read_editor_text_file(get_file_workspace_storage(), str(target.parent), target.name)
    except FileNotFoundError as exc:
        raise NotFoundError("文件不存在。") from exc
    except PermissionError as exc:
        raise BadRequestError("没有读取这个文件的权限。") from exc
    return {"path": target.as_posix(), "content": content, "mtime_ms": mtime}


def resolve_file_reference(*, path: str, source: str, project_id: str | None,
                           session_id: str | None, owner_project_id: str, kind: str = "file") -> dict:
    service = get_project_file_service()
    if kind == "folder":
        from app.repositories.project import get_project_repository
        if source == "project_file":
            if not project_id:
                raise BadRequestError("缺少文件夹所属项目。")
            root = Path(service.get_project_root(project_id)).resolve()
            target = (root / path).resolve()
            if not target.is_relative_to(root):
                raise BadRequestError("文件夹超出项目目录。")
        else:
            target = Path(path)
            if not target.is_absolute():
                raise BadRequestError("本地文件夹必须使用绝对路径。")
            target = target.resolve()
        if not target.is_dir():
            raise NotFoundError("文件夹不存在。")
        repository = get_project_repository()
        project = repository.get_project_by_root_path(str(target))
        category = repository.get_project_category(project.category_id) if project else None
        return {"kind": "folder", "path": target.as_posix(), "name": target.name,
                "project": {"project_id": project.project_id, "name": project.name,
                            "project_kind": project.project_kind, "category_id": project.category_id,
                            "category_name": category.name if category else ""} if project else None}
    if path.startswith(ATTACHMENT_URI_PREFIX):
        if not project_id or not session_id:
            raise BadRequestError("缺少附件所属会话，无法打开图片。")
        attachment, target = get_conversation_attachment_repository().read(project_id, session_id, path)
        target = target.resolve()
        name = attachment.display_name
    elif source == "project_file":
        if not project_id:
            raise BadRequestError("缺少文件所属项目。")
        target = service.get_file_path(project_id, target_path=path).resolve()
        name = target.name
    else:
        target = local_path(path)
        name = target.name

    # Explicit host paths inside the current project reuse the project tab, too.
    root = Path(service.get_project_root(owner_project_id)).resolve()
    if target.is_relative_to(root):
        kind, file_path = "project", target.relative_to(root).as_posix()
    else:
        kind, root = "local", Path(target.anchor)
        file_path = target.relative_to(root).as_posix()
    try:
        mtime_ms = int(target.stat().st_mtime * 1000)
    except FileNotFoundError as exc:
        raise NotFoundError("文件不存在。") from exc
    return {"kind": kind, "root": root.as_posix(), "path": file_path,
            "name": name, "mtime_ms": mtime_ms}
