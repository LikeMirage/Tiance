from app.core.errors import AppError, BadRequestError, NotFoundError
from app.services.project.project_conversations import get_project_conversation_service
from app.services.tools.tool_metadata import normalize_tool_name


def assert_session_tool_allowed(
    tool_name: str,
    *,
    project_id: str | None,
    session_id: str | None,
) -> None:
    if not project_id and not session_id:
        return
    if not project_id or not session_id:
        raise BadRequestError("project_id 和 session_id 必须同时提供。")

    try:
        normalized_tool_name = normalize_tool_name(tool_name)
    except AppError as exc:
        raise BadRequestError("工具调用名称无效。") from exc

    session = get_project_conversation_service().get_session(project_id, session_id)
    if session is None:
        raise NotFoundError("当前会话不存在，无法确认目标工具是否在会话中启用。")

    if not session.settings.tools_enabled:
        raise NotFoundError("会话工具总开关已关闭。")

    enabled_tool_names = session.settings.enabled_tool_names
    if enabled_tool_names is None:
        return

    normalized_allowed_names: set[str] = set()
    for enabled_tool_name in enabled_tool_names:
        try:
            normalized_allowed_names.add(normalize_tool_name(enabled_tool_name))
        except AppError as exc:
            raise BadRequestError("会话工具启用配置无效。") from exc

    if normalized_tool_name not in normalized_allowed_names:
        raise NotFoundError("此工具已关闭。")
