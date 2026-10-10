from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.llm.generation_params import LlmReasoningMode
from app.domain.llm.output_limit import DEFAULT_OUTPUT_LIMIT_MESSAGE, OutputLimitAction


class RoleConfigurationContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoleProfileConfiguration(RoleConfigurationContract):
    description: str


class RoleModelConfiguration(RoleConfigurationContract):
    provider_id: str
    model_id: str
    reasoning_mode: LlmReasoningMode | None


class RoleGenerationConfiguration(RoleConfigurationContract):
    temperature: float | None = Field(ge=0, le=2)
    top_p: float | None = Field(ge=0, le=1)
    max_output_tokens: int = Field(ge=1)


class RolePromptConfiguration(RoleConfigurationContract):
    system_prompt: str


class RoleResponseConfiguration(RoleConfigurationContract):
    output_limit_action: OutputLimitAction = "retry"
    output_limit_save_partial: bool = False
    output_limit_message: str = DEFAULT_OUTPUT_LIMIT_MESSAGE
    output_limit_max_recoveries: int | None = Field(default=None, ge=0)
    streaming_enabled: bool
    auto_collapse_assistant_process: bool
    malformed_tool_call_recovery_enabled: bool
    upstream_retry_count: int = Field(ge=0)

    @model_validator(mode="before")
    @classmethod
    def discard_removed_cancellation_settings(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        # Older role packages may still contain these retired options.
        return {
            key: item
            for key, item in value.items()
            if key not in {"return_cancelled_messages", "return_user_before_cancelled"}
        }


class RoleContextConfiguration(RoleConfigurationContract):
    inject_message_timestamps: bool


class RoleMemoryConfiguration(RoleConfigurationContract):
    global_memory_enabled: bool
    global_memory_extraction_enabled: bool
    project_memory_enabled: bool
    project_memory_extraction_enabled: bool
    memory_compression_enabled: bool
    memory_context_token_trigger_threshold: int = Field(ge=1)
    memory_raw_context_token_reserve: int = Field(ge=0)


class RoleToolsConfiguration(RoleConfigurationContract):
    tools_enabled: bool
    enabled_tool_names: list[str] | None
    max_tool_calls: int = Field(ge=1)
    tool_approval_mode: Literal["follow_tool_policy", "auto_allow_ask"]


ROLE_CONFIGURATION_MODELS: dict[str, type[RoleConfigurationContract]] = {
    "profile.json": RoleProfileConfiguration,
    "model.json": RoleModelConfiguration,
    "generation.json": RoleGenerationConfiguration,
    "prompt.json": RolePromptConfiguration,
    "response.json": RoleResponseConfiguration,
    "context.json": RoleContextConfiguration,
    "memory.json": RoleMemoryConfiguration,
    "tools.json": RoleToolsConfiguration,
}
ROLE_PACKAGE_FILE_NAMES = frozenset({"manifest.json", *ROLE_CONFIGURATION_MODELS})
