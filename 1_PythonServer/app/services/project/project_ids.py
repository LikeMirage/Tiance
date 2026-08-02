from uuid import UUID

from app.core.errors import BadRequestError


def normalize_project_id(project_id: str) -> str:
    """验证并规范化项目 ID 为 UUID 格式。"""
    normalized_project_id = project_id.strip()
    try:
        return str(UUID(normalized_project_id))
    except ValueError as exc:
        raise BadRequestError("Project id must be a valid UUID.") from exc
