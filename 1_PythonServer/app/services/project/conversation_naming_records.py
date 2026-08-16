from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatCompletionResult,
    ChatMessage,
    ChatUsage,
)
from app.domain.llm.generation_params import LlmGenerationParams, LlmOutputOptions
from app.domain.project.project_conversation import ProjectConversationNamingCallRecord
from app.services.project.project_conversations import ProjectConversationService


class ConversationNamingCallRecorder:
    def __init__(self, conversation_service: ProjectConversationService) -> None:
        self._conversation_service = conversation_service

    def append(
        self,
        *,
        project_id: str,
        session_id: str,
        request: ChatCompletionRequest,
        created_at: str,
        status: str,
        response: dict | None = None,
        error: str | None = None,
    ) -> None:
        self._conversation_service.append_naming_call_record(
            project_id,
            session_id,
            ProjectConversationNamingCallRecord(
                naming_call_id=f"naming_call_{uuid4().hex[:16]}",
                session_id=session_id,
                provider_id=request.provider_id,
                model_id=request.model_id,
                request=naming_request_payload(request),
                response=response,
                status=status,
                error=error,
                created_at=created_at,
                completed_at=utc_now(),
            ),
        )


def naming_response_payload(
    result: ChatCompletionResult,
    selected_title: str | None,
) -> dict[str, Any]:
    return {
        "provider_id": result.provider_id,
        "model_id": result.model_id,
        "message": _chat_message_payload(result.message),
        "thinking_content": result.thinking_content,
        "finish_reason": result.finish_reason,
        "usage": _usage_payload(result.usage),
        "selected_api_key_hint": result.selected_api_key_hint,
        "raw_response": result.raw_response,
        "selected_title": selected_title,
    }


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def naming_request_payload(request: ChatCompletionRequest) -> dict[str, Any]:
    return {
        "provider_id": request.provider_id,
        "model_id": request.model_id,
        "project_id": request.project_id,
        "session_id": request.session_id,
        "messages": [_chat_message_payload(message) for message in request.messages],
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in request.tools
        ],
        "generation": _generation_payload(request.generation),
        "output": _output_payload(request.output),
        "record_usage": request.record_usage,
        "usage_message_id": request.usage_message_id,
        "usage_feature_key": request.usage_feature_key,
    }


def _chat_message_payload(message: ChatMessage) -> dict[str, Any]:
    return {
        "role": message.role.value,
        "content": message.content,
        "name": message.name,
        "tool_call_id": message.tool_call_id,
        "tool_calls": [
            {
                "call_id": tool_call.call_id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
            }
            for tool_call in message.tool_calls
        ],
        "content_parts": [
            {
                "type": part.type.value,
                "text": part.text,
                "image_url": {
                    "url": part.image_url.url,
                    "detail": part.image_url.detail,
                } if part.image_url else None,
                "image_ref": {
                    "path": part.image_ref.path,
                    "mime_type": part.image_ref.mime_type,
                    "detail": part.image_ref.detail,
                    "name": part.image_ref.name,
                    "size_bytes": part.image_ref.size_bytes,
                } if part.image_ref else None,
            }
            for part in message.content_parts
        ],
    }


def _generation_payload(generation: LlmGenerationParams) -> dict[str, Any]:
    return {
        "temperature": generation.temperature,
        "top_p": generation.top_p,
        "max_output_tokens": generation.max_output_tokens,
        "reasoning": {
            "mode": generation.reasoning.mode.value,
            "budget_tokens": generation.reasoning.budget_tokens,
        } if generation.reasoning else None,
    }


def _output_payload(output: LlmOutputOptions) -> dict[str, Any]:
    return {"format": output.format.value}


def _usage_payload(usage: ChatUsage | None) -> dict[str, int | None] | None:
    if usage is None:
        return None
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
        "prompt_cache_hit_tokens": usage.prompt_cache_hit_tokens,
        "prompt_cache_miss_tokens": usage.prompt_cache_miss_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
    }
