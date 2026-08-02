from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GithubConnectionContract(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class GithubRepositorySummary(GithubConnectionContract):
    id: int
    full_name: str = Field(alias="fullName")
    private: bool
    default_branch: str = Field(alias="defaultBranch")
    can_push: bool = Field(default=False, alias="canPush")


class GithubAccountSummary(GithubConnectionContract):
    login: str
    name: str | None = None
    avatar_url: str = Field(alias="avatarUrl")
    profile_url: str = Field(alias="profileUrl")


class GithubConnectionStatusResponse(GithubConnectionContract):
    connected: bool
    account: GithubAccountSummary | None = None
    repositories: list[GithubRepositorySummary] = Field(default_factory=list)
    permissions: dict[str, str] = Field(default_factory=dict)
    missing_permissions: list[str] = Field(default_factory=list, alias="missingPermissions")
    requires_reauthorization: bool = Field(default=False, alias="requiresReauthorization")
    authorization_url: str = Field(alias="authorizationUrl")


class GithubDeviceFlowStartResponse(GithubConnectionContract):
    flow_id: str = Field(alias="flowId")
    user_code: str = Field(alias="userCode")
    verification_uri: str = Field(alias="verificationUri")
    expires_in: int = Field(alias="expiresIn")
    interval: int


class GithubDeviceFlowPollRequest(GithubConnectionContract):
    flow_id: str = Field(alias="flowId")


class GithubDeviceFlowPollResponse(GithubConnectionContract):
    status: Literal["pending", "slow_down", "completed"]
    retry_after: int | None = Field(default=None, alias="retryAfter")
    connection: GithubConnectionStatusResponse | None = None


class GithubLogoutResponse(GithubConnectionContract):
    connected: Literal[False] = False
