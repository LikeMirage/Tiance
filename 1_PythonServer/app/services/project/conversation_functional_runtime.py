from __future__ import annotations

from dataclasses import dataclass, replace

from app.domain.llm.generation_params import LlmGenerationParams
from app.domain.project.project_conversation import (
    ProjectConversationSession,
    ProjectConversationSessionSettings,
)
from app.services.project.conversation_functional_settings import (
    generation_from_settings,
    parse_model_key,
    string_setting,
)
from app.services.project.conversation_run_snapshot import ConversationRunSnapshot


@dataclass(frozen=True, slots=True)
class FunctionalConversationModelTarget:
    generation: LlmGenerationParams
    mode: str
    model_id: str
    provider_id: str
    reasoning_mode: str | None
    session_settings: ProjectConversationSessionSettings


def resolve_functional_conversation_model_target(
    settings: dict,
    *,
    source_session: ProjectConversationSession,
    run_snapshot: ConversationRunSnapshot,
    task_prompt: str,
) -> FunctionalConversationModelTarget | None:
    use_session_model = settings.get("modelSource") != "dedicated"
    provider_id, model_id = (
        (
            run_snapshot.model_request.provider_id,
            run_snapshot.model_request.model_id,
        )
        if use_session_model
        else parse_model_key(string_setting(settings, "modelKey"))
    )
    if provider_id is None or model_id is None:
        return None

    generation = (
        run_snapshot.model_request.generation
        if use_session_model
        else generation_from_settings(settings.get("generation"))
    )
    reasoning_mode = (
        generation.reasoning.mode.value
        if generation.reasoning is not None
        else source_session.reasoning_mode
    )
    session_settings = functional_session_settings(
        source_session.settings,
        generation,
    )
    if not use_session_model:
        session_settings = replace(
            session_settings,
            system_prompt=task_prompt,
        )
    return FunctionalConversationModelTarget(
        generation=generation,
        mode="session" if use_session_model else "dedicated",
        model_id=model_id,
        provider_id=provider_id,
        reasoning_mode=reasoning_mode,
        session_settings=session_settings,
    )


def functional_session_settings(
    source: ProjectConversationSessionSettings,
    generation: LlmGenerationParams,
) -> ProjectConversationSessionSettings:
    return replace(
        source,
        max_output_tokens=(
            generation.max_output_tokens
            if generation.max_output_tokens is not None
            else source.max_output_tokens
        ),
        temperature=generation.temperature,
        top_p=generation.top_p,
    )
