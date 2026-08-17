import asyncio

from fastapi import APIRouter, Query, status

from app.core.errors import ConflictError
from app.schemas.llm.usage import LlmSessionUsageSummaryResponse
from app.schemas.project import (
    ApplyConversationRoleRequest,
    ConversationImageAttachmentCreateRequest,
    ConversationImageAttachmentResponse,
    ProjectConversationAutomaticNamingSettleRequest,
    ProjectConversationAutomaticNamingSettleResponse,
    ProjectConversationAutomaticTitleRequest,
    ProjectConversationAutomaticTitleResponse,
    ProjectConversationBranchGroupDetailResponse,
    ProjectConversationBranchGroupListResponse,
    ProjectConversationBranchGroupResponse,
    ProjectConversationCreateRequest,
    ProjectConversationDataViewResponse,
    ProjectConversationForkRequest,
    ProjectConversationForkResponse,
    ProjectConversationListResponse,
    ProjectConversationMessageListResponse,
    ProjectConversationMessageResponse,
    ProjectConversationMessageTurnResponse,
    ProjectConversationBranchNodeResponse,
    ProjectConversationMessageVariantResponse,
    ProjectConversationSessionResponse,
    ProjectConversationSessionPinRequest,
    ProjectConversationSessionStateResponse,
    ProjectConversationSessionUpdateRequest,
    ProjectConversationStateResponse,
    ProjectConversationStateSaveRequest,
    SaveConversationAsRoleRequest,
    SaveConversationAsRoleResponse,
)
from app.schemas.project.projects import ProjectResponse
from app.services.application.role_configuration import (
    get_role_configuration_application_service,
)
from app.services.llm.usage import get_llm_usage_service
from app.services.project import (
    get_project_conversation_service,
    get_project_service,
)
from app.services.project.conversation_background_tasks import (
    get_conversation_background_task_registry,
)
from app.services.project.conversation_run_manager import get_conversation_run_manager
from app.services.project.conversation_naming import (
    get_project_conversation_naming_service,
)
from app.services.project.conversation_attachments import (
    get_conversation_attachment_service,
)
from app.repositories.project.conversation_data_view_repository import (
    ConversationDataViewName,
    ConversationDataViewRepository,
)
from app.repositories.project.project_repository import get_project_repository

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get(
    "/{project_id}/conversations/data-view",
    response_model=ProjectConversationDataViewResponse,
    summary="Read a conversation data dashboard view",
)
def read_conversation_data_view(
    project_id: str,
    name: ConversationDataViewName = Query(...),
    session_id: str | None = Query(default=None),
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=50, ge=1),
) -> ProjectConversationDataViewResponse:
    view = ConversationDataViewRepository(
        get_project_repository(),
    ).read(
        project_id,
        name=name,
        session_id=session_id,
        page=page,
        page_size=page_size,
    )
    return ProjectConversationDataViewResponse(
        project_id=project_id,
        session_id=session_id,
        name=name,
        content=view.content,
        revision_ms=view.revision_ms,
        total_count=view.total_count,
        page=view.page,
        page_size=view.page_size,
        total_pages=view.total_pages,
        has_previous=view.has_previous,
        has_next=view.has_next,
    )
@router.post(
    "/{project_id}/conversations/{session_id}/attachments/images",
    response_model=ConversationImageAttachmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save an image as a session-owned conversation attachment",
)
def create_conversation_image_attachment(
    project_id: str,
    session_id: str,
    payload: ConversationImageAttachmentCreateRequest,
) -> ConversationImageAttachmentResponse:
    image_ref = get_conversation_attachment_service().save_uploaded_image(
        project_id,
        session_id,
        filename=payload.filename,
        mime_type=payload.mime_type,
        data_base64=payload.data_base64,
        source_kind=payload.source_kind,
        source_path=payload.source_path,
    )
    return ConversationImageAttachmentResponse.from_domain(
        project_id=project_id,
        session_id=session_id,
        image_ref=image_ref,
    )


@router.get(
    "/{project_id}/conversation-branches",
    response_model=ProjectConversationBranchGroupListResponse,
    summary="List project conversation branch groups",
)
async def list_project_conversation_branch_groups(
    project_id: str,
) -> ProjectConversationBranchGroupListResponse:
    groups = await asyncio.to_thread(
        get_project_conversation_service().list_branch_groups,
        project_id,
    )
    items = [
        ProjectConversationBranchGroupResponse.from_domain(group)
        for group in groups
    ]
    return ProjectConversationBranchGroupListResponse(
        project_id=project_id,
        count=len(items),
        items=items,
    )


@router.get(
    "/{project_id}/conversation-branches/{group_id}",
    response_model=ProjectConversationBranchGroupDetailResponse,
    summary="Get a project conversation branch group",
)
async def get_project_conversation_branch_group(
    project_id: str,
    group_id: str,
) -> ProjectConversationBranchGroupDetailResponse:
    detail = await asyncio.to_thread(
        get_project_conversation_service().get_branch_group_detail,
        project_id,
        group_id,
    )
    return ProjectConversationBranchGroupDetailResponse.from_domain(project_id, detail)


@router.get(
    "/{project_id}/conversations",
    response_model=ProjectConversationListResponse,
    summary="List project conversation sessions",
)
def list_project_conversations(project_id: str) -> ProjectConversationListResponse:
    service = get_project_conversation_service()
    (
        revision,
        sessions,
        branch_nodes,
        message_variants,
        assistant_title,
        active_session_id,
        session_states,
    ) = service.get_list_data(project_id)
    items = [ProjectConversationSessionResponse.from_domain(session) for session in sessions]
    return ProjectConversationListResponse(
        project_id=project_id,
        revision=revision,
        count=len(items),
        assistant_title=assistant_title,
        active_session_id=active_session_id,
        session_states={
            session_id: ProjectConversationSessionStateResponse.from_domain(state)
            for session_id, state in session_states.items()
        },
        items=items,
        branch_nodes=[
            ProjectConversationBranchNodeResponse.from_domain(node)
            for node in branch_nodes
        ],
        message_variants=[
            ProjectConversationMessageVariantResponse.from_domain(variant)
            for variant in message_variants
        ],
    )


@router.post(
    "/{project_id}/conversations",
    response_model=ProjectConversationSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project conversation session",
)
def create_project_conversation(
    project_id: str,
    payload: ProjectConversationCreateRequest,
) -> ProjectConversationSessionResponse:
    service = get_project_conversation_service()
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
    if payload.created_by == "user":
        seed = get_role_configuration_application_service().build_new_session_seed(
            payload.role_project_id,
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
            None if has_explicit_configuration else seed.role_project_id
        )
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
        role_project_id=role_project_id,
        settings=settings,
    )
    return ProjectConversationSessionResponse.from_domain(session)


@router.patch(
    "/{project_id}/conversations/state",
    response_model=ProjectConversationStateResponse,
    summary="Save project conversation state",
)
def save_project_conversation_state(
    project_id: str,
    payload: ProjectConversationStateSaveRequest,
) -> ProjectConversationStateResponse:
    service = get_project_conversation_service()
    assistant_title, active_session_id, session_states = service.save_state(
        project_id,
        assistant_title=payload.assistant_title,
        should_update_assistant_title="assistant_title" in payload.model_fields_set,
        active_session_id=payload.active_session_id,
        should_update_active_session="active_session_id" in payload.model_fields_set,
        session_states={
            session_id: state.model_dump(exclude_none=True, by_alias=True)
            for session_id, state in payload.session_states.items()
        },
    )
    return ProjectConversationStateResponse(
        project_id=project_id,
        assistant_title=assistant_title,
        active_session_id=active_session_id,
        session_states={
            session_id: ProjectConversationSessionStateResponse.from_domain(state)
            for session_id, state in session_states.items()
        },
    )


@router.patch(
    "/{project_id}/conversations/{session_id}",
    response_model=ProjectConversationSessionResponse,
    summary="Update a project conversation session",
)
def update_project_conversation(
    project_id: str,
    session_id: str,
    payload: ProjectConversationSessionUpdateRequest,
) -> ProjectConversationSessionResponse:
    service = get_project_conversation_service()
    session = service.update_session(
        project_id,
        session_id,
        title=payload.title,
        should_update_title="title" in payload.model_fields_set,
        provider_id=payload.provider_id,
        should_update_provider="provider_id" in payload.model_fields_set,
        model_id=payload.model_id,
        should_update_model="model_id" in payload.model_fields_set,
        reasoning_mode=payload.reasoning_mode.value if payload.reasoning_mode else None,
        should_update_reasoning="reasoning_mode" in payload.model_fields_set,
        manual_title=True,
        should_update_manual_title="title" in payload.model_fields_set,
        settings=payload.settings.model_dump(exclude_unset=True) if payload.settings else None,
        should_update_settings="settings" in payload.model_fields_set,
    )
    return ProjectConversationSessionResponse.from_domain(session)


@router.post(
    "/{project_id}/conversations/{session_id}/role",
    response_model=ProjectConversationSessionResponse,
    summary="Apply a role to a project conversation session",
)
def apply_project_conversation_role(
    project_id: str,
    session_id: str,
    payload: ApplyConversationRoleRequest,
) -> ProjectConversationSessionResponse:
    session = get_role_configuration_application_service().apply_role(
        project_id,
        session_id,
        payload.role_project_id,
    )
    return ProjectConversationSessionResponse.from_domain(session)


@router.post(
    "/{project_id}/conversations/{session_id}/save-as-role",
    response_model=SaveConversationAsRoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save a project conversation session as a role",
)
def save_project_conversation_as_role(
    project_id: str,
    session_id: str,
    payload: SaveConversationAsRoleRequest,
) -> SaveConversationAsRoleResponse:
    role, session = (
        get_role_configuration_application_service().save_session_as_role(
            project_id,
            session_id,
            name=payload.name,
            category_id=payload.category_id,
        )
    )
    project_service = get_project_service()
    return SaveConversationAsRoleResponse(
        role=ProjectResponse.from_domain(
            role,
            is_managed=project_service.is_managed_project(role),
        ),
        session=ProjectConversationSessionResponse.from_domain(session),
    )


@router.post(
    "/{project_id}/conversations/{function_session_id}/automatic-title",
    response_model=ProjectConversationAutomaticTitleResponse,
    summary="Apply an automatic title from a naming functional conversation",
)
def apply_project_conversation_automatic_title(
    project_id: str,
    function_session_id: str,
    payload: ProjectConversationAutomaticTitleRequest,
) -> ProjectConversationAutomaticTitleResponse:
    result = get_project_conversation_naming_service().name_parent_session(
        project_id,
        function_session_id,
        title=payload.title,
    )
    return ProjectConversationAutomaticTitleResponse.model_validate(result)


@router.post(
    "/{project_id}/conversations/{function_session_id}/automatic-naming/settle",
    response_model=ProjectConversationAutomaticNamingSettleResponse,
    summary="Settle an automatic naming functional conversation",
)
def settle_project_conversation_automatic_naming(
    project_id: str,
    function_session_id: str,
    payload: ProjectConversationAutomaticNamingSettleRequest,
) -> ProjectConversationAutomaticNamingSettleResponse:
    result = get_project_conversation_naming_service().settle_automatic_naming(
        project_id,
        function_session_id,
        outcome=payload.outcome,
    )
    return ProjectConversationAutomaticNamingSettleResponse.model_validate(result)


@router.patch(
    "/{project_id}/conversations/{session_id}/pin",
    response_model=ProjectConversationSessionResponse,
    summary="Pin or unpin a project conversation session",
)
def set_project_conversation_pinned(
    project_id: str,
    session_id: str,
    payload: ProjectConversationSessionPinRequest,
) -> ProjectConversationSessionResponse:
    session = get_project_conversation_service().set_session_pinned(
        project_id,
        session_id,
        pinned=payload.pinned,
    )
    return ProjectConversationSessionResponse.from_domain(session)


@router.post(
    "/{project_id}/conversations/{session_id}/fork",
    response_model=ProjectConversationForkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Fork a project conversation from a user message",
)
async def fork_project_conversation(
    project_id: str,
    session_id: str,
    payload: ProjectConversationForkRequest,
) -> ProjectConversationForkResponse:
    if await get_conversation_run_manager().is_running(project_id, session_id):
        raise ConflictError("当前会话正在生成，完成或停止后才能创建分支。")
    result = await asyncio.to_thread(
        get_project_conversation_service().fork_session,
        project_id,
        session_id,
        source_message_id=payload.source_message_id,
        draft=payload.draft,
        references=payload.references.to_payload(),
    )
    branch_nodes, message_variants = await asyncio.to_thread(
        get_project_conversation_service().list_branch_graph,
        project_id,
    )
    return ProjectConversationForkResponse(
        session=ProjectConversationSessionResponse.from_domain(result.session),
        state=ProjectConversationSessionStateResponse.from_domain(result.state),
        branch=ProjectConversationBranchNodeResponse.from_domain(result.branch),
        source_message=ProjectConversationMessageResponse.from_domain(result.source_message),
        branch_nodes=[
            ProjectConversationBranchNodeResponse.from_domain(node)
            for node in branch_nodes
        ],
        message_variants=[
            ProjectConversationMessageVariantResponse.from_domain(variant)
            for variant in message_variants
        ],
    )


@router.delete(
    "/{project_id}/conversations/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project conversation session",
)
async def delete_project_conversation(
    project_id: str,
    session_id: str,
) -> None:
    await get_conversation_run_manager().stop(project_id, session_id)
    await get_conversation_background_task_registry().cancel_session(project_id, session_id)
    service = get_project_conversation_service()
    await asyncio.to_thread(service.delete_session, project_id, session_id)


@router.get(
    "/{project_id}/conversations/{session_id}/usage-summary",
    response_model=LlmSessionUsageSummaryResponse,
    summary="Get usage summary for a project conversation session",
)
def get_project_conversation_usage_summary(
    project_id: str,
    session_id: str,
) -> LlmSessionUsageSummaryResponse:
    summary = get_llm_usage_service().get_session_summary(
        project_id=project_id,
        session_id=session_id,
    )
    return LlmSessionUsageSummaryResponse.from_domain(summary)


@router.get(
    "/{project_id}/conversations/{session_id}/messages",
    response_model=ProjectConversationMessageListResponse,
    summary="List project conversation messages",
)
def list_project_conversation_messages(
    project_id: str,
    session_id: str,
    limit: int | None = Query(default=None, ge=1),
    before_message_id: str | None = Query(default=None),
) -> ProjectConversationMessageListResponse:
    service = get_project_conversation_service()
    page = service.list_messages_page(
        project_id,
        session_id,
        limit=limit,
        before_message_id=before_message_id,
    )
    items = [ProjectConversationMessageResponse.from_domain(message) for message in page.items]
    return ProjectConversationMessageListResponse(
        project_id=project_id,
        session_id=session_id,
        count=len(items),
        total_count=page.total_count,
        has_more=page.has_more,
        next_before_message_id=page.next_before_message_id,
        items=items,
    )


@router.get(
    "/{project_id}/conversations/{session_id}/messages/{user_message_id}/turn",
    response_model=ProjectConversationMessageTurnResponse,
    summary="Get one project conversation turn by its user message",
)
def get_project_conversation_message_turn(
    project_id: str,
    session_id: str,
    user_message_id: str,
) -> ProjectConversationMessageTurnResponse:
    turn = get_project_conversation_service().get_message_turn(
        project_id,
        session_id,
        user_message_id,
    )
    items = [
        ProjectConversationMessageResponse.from_domain(message)
        for message in turn.items
    ]
    return ProjectConversationMessageTurnResponse(
        project_id=project_id,
        session_id=session_id,
        user_message_id=turn.user_message_id,
        count=len(items),
        items=items,
    )
