from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import BadRequestError, NotFoundError
from app.domain.tools.host_capabilities import HostCapability
from app.schemas.tools.catalog import ToolExampleDetailResponse, ToolSummaryResponse
from app.services.tools.catalog import get_tool_catalog_service
from app.services.tools.catalog_access import assert_session_tool_allowed
from app.services.tools.tool_metadata import normalize_tool_name
from app.services.tools.host_capability_access import (
    RUN_OBSERVER_LEASE_SECONDS, get_host_capability_access_service,
)
from app.services.project.conversation_run_manager import get_conversation_run_manager

router = APIRouter(prefix='/tools/capabilities', tags=['tools'])


class CatalogRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation: Literal['get_parameters', 'get_examples']
    tool_name: str
    indexes: list[int] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)
    include_all: bool = False


class RunStatusRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['status', 'watch'] = 'status'


def _authorize(authorization: str | None, capability: HostCapability):
    scheme, _, token = (authorization or '').partition(' ')
    access = get_host_capability_access_service()
    grant = access.authorize(token if scheme.lower() == 'bearer' else '', capability)
    if grant is None:
        raise HTTPException(401, '后端能力授权无效或已过期。', headers={'WWW-Authenticate': 'Bearer'})
    return grant


@router.post('/catalog')
def read_catalog(payload: CatalogRequest, authorization: Annotated[str | None, Header()] = None):
    grant = _authorize(authorization, HostCapability.TOOL_CATALOG)
    name = normalize_tool_name(payload.tool_name)
    if grant.enabled_tool_names is not None and name not in {
        normalize_tool_name(value) for value in grant.enabled_tool_names
    }:
        raise NotFoundError('此工具未在本次调用范围中启用。')
    assert_session_tool_allowed(name, project_id=grant.project_id, session_id=grant.session_id)
    catalog = get_tool_catalog_service()
    if payload.operation == 'get_parameters':
        detail = catalog.get_tool_parameters(name)
        return {'name': name, 'input_schema': detail.input_schema,
                'summary': ToolSummaryResponse.from_domain(catalog.get_tool_summary(name)).model_dump()}
    examples = catalog.get_tool_examples(name, titles=tuple(payload.titles),
        indexes=tuple(payload.indexes), include_all=payload.include_all)
    return {'name': name, 'count': len(examples),
            'items': [ToolExampleDetailResponse.from_domain(item).model_dump() for item in examples]}


@router.post('/run-status')
async def read_run_status(payload: RunStatusRequest, authorization: Annotated[str | None, Header()] = None):
    grant = _authorize(authorization, HostCapability.RUN_STATUS)
    if not grant.project_id or not grant.session_id or not grant.run_id:
        raise BadRequestError('此能力要求当前项目、会话和生成任务身份。')
    access = get_host_capability_access_service()
    status = await get_conversation_run_manager().get_run_status(grant.project_id, grant.session_id)
    if not status.get('running') or status.get('run_id') != grant.run_id:
        access.revoke(grant.token)
        return {'running': False, 'run_id': None}
    if payload.action == 'watch':
        if grant.observer:
            raise BadRequestError('观察租约不能再创建其他租约。')
        try:
            observer = access.delegate_run_observer(grant)
        except ValueError as exc:
            raise HTTPException(401, str(exc)) from exc
        return {'running': True, 'run_id': grant.run_id, 'token': observer.token,
                'lease_seconds': RUN_OBSERVER_LEASE_SECONDS}
    if grant.observer and not access.renew_run_observer(grant.token):
        raise HTTPException(401, '任务观察租约已过期。')
    return {'running': True, 'run_id': grant.run_id}
