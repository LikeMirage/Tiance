"""Channel-neutral project/session addressing. Never reads or changes desktop selection."""
from pathlib import Path
from uuid import uuid4

from app.core.errors import BadRequestError, NotFoundError
from app.domain.project.conversation_hierarchy import visible_conversation_parents
from app.schemas.project.project_conversations import ProjectConversationCreateRequest
from app.services.application.conversation_creation import create_conversation
from app.services.project import get_project_service, get_project_conversation_service


COLLECTIONS = {"project": "项目集", "tool": "工具集", "knowledge": "知识集",
               "experience": "经验集", "role": "角色集", "provider": "模型集", "theme": "主题集"}
GROUPS = {"child": "AI 子会话", "fork": "对话分支", "automatic_naming": "自动命名",
          "memory_compaction": "记忆压缩", "project_memory_management": "项目记忆管理",
          "global_memory_management": "全局记忆管理"}


def resolve_target(target, *, session_required=True):
    if not target or not target.get("project_id"):
        raise BadRequestError("请先选择项目和会话。")
    project = get_project_service().get_project(target["project_id"])
    if project is None:
        raise NotFoundError("所选项目已不存在，请重新选择。")
    session = None
    if target.get("session_id"):
        session = get_project_conversation_service().get_session(project.project_id, target["session_id"])
        if session is None:
            raise NotFoundError("所选会话已不存在，请重新选择。")
    elif session_required:
        raise BadRequestError("请先选择会话，或使用 /new 新建会话。")
    return project, session


def target_header(target):
    if not target:
        return "天策 · 尚未选择项目／会话"
    try:
        project, session = resolve_target(target, session_required=False)
        return f"{COLLECTIONS.get(project.project_kind, '项目')} · {project.name}\n会话：{session.title if session else '未选择'}"
    except (BadRequestError, NotFoundError):
        return "天策 · 原项目／会话已不可用"


def new_conversation(target, title=None):
    project, _ = resolve_target(target, session_required=False)
    kwargs = dict(activate=False, created_by="user")
    if title:
        kwargs["title"] = title
    session = create_conversation(project.project_id, ProjectConversationCreateRequest(**kwargs))
    return {"project_id": project.project_id, "session_id": session.session_id}


def session_children(project_id, parent=None, group=None):
    service = get_project_conversation_service()
    _, sessions, nodes, _, _, _ = service.get_list_data(project_id, summaries_only=True)
    parents = visible_conversation_parents(sessions, nodes)
    nodes_by_id = {n.session_id: n for n in nodes}
    # get_list_data already supplies desktop order: pinned first, then newest.
    # Iterating branch nodes instead loses that order and omits unbranched roots.
    return [(s, nodes_by_id.get(s.session_id)) for s in sessions
            if (parents.get(s.session_id) == (parent, group) if parent
                else s.session_id not in parents)]


def incoming_path(target, filename, channel="Telegram"):
    project, _ = resolve_target(target)
    root = Path(project.root_path).resolve(strict=True)
    relative = Path("远程收件") / channel / uuid4().hex / filename
    destination = (root / relative).resolve()
    if not destination.is_relative_to(root):
        raise BadRequestError("收件目录指向工作区外，无法保存文件。")
    return destination, relative.as_posix()


def file_reference(target, relative, filename):
    return {"type": "file", "reference": {"id": uuid4().hex, "source": "project_file",
            "projectId": target["project_id"], "filePath": relative, "fileName": filename,
            "displayPath": relative, "kind": "file"}}
