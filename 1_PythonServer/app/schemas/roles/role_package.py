from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domain.llm.generation_params import LlmReasoningMode


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
    return_thinking_content: bool
    return_cancelled_messages: bool
    return_user_before_cancelled: bool
    streaming_enabled: bool
    auto_collapse_assistant_process: bool


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
