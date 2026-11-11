from app.core.errors import NotFoundError
from app.services.project import get_project_conversation_service, get_project_service
from app.services.application.role_configuration import get_role_configuration_application_service
from app.schemas.project.project_conversations import ProjectConversationCreateRequest, ProjectConversationSessionResponse


def create_conversation(project_id: str, payload: ProjectConversationCreateRequest, *,
                        service=None, projects=None, roles=None) -> ProjectConversationSessionResponse:
    service = service or get_project_conversation_service()
    payload_settings = (
        payload.settings.model_dump(exclude_unset=True)
        if payload.settings
        else None
    )
    provider_id = payload.provider_id
    model_id = payload.model_id
    reasoning_mode = (
        payload.reasoning_mode.value if payload.reasoning_mode else None
    )
    settings = payload_settings
    role_project_id = payload.role_project_id
    if payload.created_by == "user" or payload.role_project_id:
        project = (projects or get_project_service()).get_project(project_id)
        if project is None:
            raise NotFoundError("项目不存在。")
        seed = (roles or get_role_configuration_application_service()).build_new_session_seed(
            payload.role_project_id,
            project_kind=project.project_kind,
        )
        provider_id = (
            payload.provider_id
            if "provider_id" in payload.model_fields_set
            else seed.provider_id
        )
        model_id = (
            payload.model_id
            if "model_id" in payload.model_fields_set
            else seed.model_id
        )
        if "reasoning_mode" in payload.model_fields_set:
            reasoning_mode = (
                payload.reasoning_mode.value
                if payload.reasoning_mode
                else None
            )
        else:
            reasoning_mode = seed.reasoning_mode
        settings = dict(seed.settings)
        settings.update(payload_settings or {})
        has_explicit_configuration = bool(
            {"provider_id", "model_id", "reasoning_mode", "settings"}
            & payload.model_fields_set
        )
        role_project_id = (
            None if has_explicit_configuration and payload.created_by == "user" else seed.role_project_id
        )
        if payload.created_by == "ai" and (
            provider_id != seed.provider_id or model_id != seed.model_id
            or reasoning_mode != seed.reasoning_mode or settings != seed.settings
        ):
            role_project_id = None
    session = service.create_session(
        project_id,
        title=payload.title,
        provider_id=provider_id,
        model_id=model_id,
        reasoning_mode=reasoning_mode,
        manual_title="title" in payload.model_fields_set,
        set_active=payload.activate,
        parent_session_id=payload.parent_session_id,
        created_by=payload.created_by,
        inherit_configuration=not bool(payload.role_project_id),
        reasoning_mode_set="reasoning_mode" in payload.model_fields_set,
        role_project_id=role_project_id,
        settings=settings,
    )
    return ProjectConversationSessionResponse.from_domain(session)
