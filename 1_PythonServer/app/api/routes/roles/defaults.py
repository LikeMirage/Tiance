from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.domain.project import ProjectKind
from app.services.application.role_configuration import get_role_configuration_application_service

router = APIRouter()


class DefaultRoleSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_project_id: str = Field(min_length=1)


@router.get("/defaults")
def read_default_roles() -> dict[str, str]:
    return get_role_configuration_application_service().get_default_roles()


@router.put("/defaults/{project_kind}", response_model=DefaultRoleSelection)
def save_default_role(project_kind: ProjectKind, payload: DefaultRoleSelection) -> DefaultRoleSelection:
    role_id = get_role_configuration_application_service().set_default_role(
        project_kind, payload.role_project_id,
    )
    return DefaultRoleSelection(role_project_id=role_id)
