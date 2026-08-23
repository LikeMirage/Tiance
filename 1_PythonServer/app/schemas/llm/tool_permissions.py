from typing import Literal

from pydantic import BaseModel


class ToolPermissionDecisionRequestBody(BaseModel):
    decision: Literal["allow", "deny"]


class ToolPermissionDecisionAck(BaseModel):
    accepted: bool
