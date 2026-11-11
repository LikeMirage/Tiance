"""Install missing authoring files in a registered collection workspace."""
from pathlib import Path, PurePosixPath

from app.core.config import get_settings
from app.core.errors import BadRequestError, NotFoundError
from app.domain.file_workspace import TextFileUpdate
from app.services.project import get_project_service, get_project_file_service
from app.services.tools.tool_folder_files import get_tool_folder_file_service


def require_collection_workspace(project_id: str, kind: str, workspace_root: str | None = None):
    settings = get_settings()
    roots = {"tool": settings.tools_data_path, "role": settings.roles_data_path,
             "theme": settings.themes_data_path}
    if kind not in roots:
        raise BadRequestError("仅支持工具集、角色集和主题集的标准内容初始化。")
    service = get_project_service()
    project = service.get_project(project_id)
    if project is None:
        raise NotFoundError("当前工作区未登记为项目。")
    root = Path(project.root_path)
    category = next((item for item in service.list_project_categories()
                     if item.category_id == project.category_id), None)
    if (project.project_kind.value != kind or category is None
            or category.category_kind.value != kind
            or root.is_symlink() or root.is_junction()
            or root.resolve().parent != Path(roots[kind]).resolve()
            or not root.is_dir()
            or (workspace_root is not None and Path(workspace_root).resolve() != root.resolve())):
        raise BadRequestError(f"只能在 {kind} 集下已登记项目的根目录初始化，当前工作区不符合要求。")
    return project


def install_project_scaffold(project_id: str, kind: str, files: list[TextFileUpdate],
                             workspace_root: str | None = None) -> dict:
    project = require_collection_workspace(project_id, kind, workspace_root)
    root = Path(project.root_path).resolve()
    updates, skipped, seen = [], [], set()
    for item in files:
        path = PurePosixPath(item.path)
        if (not item.path or path.is_absolute() or "\\" in item.path or ":" in item.path
                or any(part in {"", ".", ".."} or part.lower() == ".tiance"
                       or part.endswith((".", " ")) for part in item.path.split("/"))):
            raise BadRequestError(f"无效模板路径：{item.path}")
        key = item.path.casefold()
        if key in seen:
            raise BadRequestError("模板目标重复。")
        seen.add(key)
        target = root.joinpath(*path.parts)
        for part in (target, *target.parents):
            if part == root:
                break
            if part.is_symlink() or part.is_junction():
                raise BadRequestError("模板目录不能包含符号链接或目录链接。")
        if not target.resolve().is_relative_to(root):
            raise BadRequestError("模板路径超出当前项目。")
        if target.exists():
            if not target.is_file():
                raise BadRequestError(f"模板目标不是文件：{item.path}")
            skipped.append(item.path)
        else:
            updates.append(TextFileUpdate(item.path, item.content, create_only=True))
    # Existing user files are never overwritten. The common text transaction rolls
    # back every newly written file if any member fails; a retry fills only missing files.
    if updates:
        if kind == "tool":
            # Keep standard-file validation, unique call names and the registry
            # refresh in the same transaction as ordinary tool settings saves.
            get_tool_folder_file_service().write_text_files(project.category_id, project_id, updates)
        else:
            get_project_file_service().write_text_files(project_id, updates)
    return {"project_id": project_id, "root_path": str(root),
            "written_files": [item.path for item in updates], "preserved_files": skipped}
