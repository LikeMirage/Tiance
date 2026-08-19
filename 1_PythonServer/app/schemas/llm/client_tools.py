from typing import Any

from pydantic import BaseModel

from app.services.tools.client_tool_bridge import ClientToolResultPayload


class ClientToolResultRequestBody(BaseModel):
    executor_id: str
    claim_id: str
    ok: bool
    content: Any = None
    error: str | None = None

    def to_domain(self) -> ClientToolResultPayload:
        return ClientToolResultPayload(
            ok=self.ok,
            content=self.content,
            error=self.error.strip() if self.error else None,
        )


class ClientToolResultAck(BaseModel):
    accepted: bool


class ClientToolClaimAck(BaseModel):
    acquired: bool
    claim_id: str | None = None
    lease_duration_seconds: float | None = None
    resumed: bool = False


class ClientToolClaimRequestBody(BaseModel):
    executor_id: str


class ClientToolLeaseRenewRequestBody(BaseModel):
    executor_id: str
    claim_id: str


class ClientToolLeaseRenewAck(BaseModel):
    renewed: bool
