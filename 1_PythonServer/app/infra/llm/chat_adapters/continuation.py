from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatMessage,
    ChatProtocolContinuation,
    ChatProtocolContinuationKind,
)
from app.domain.llm.provider_catalog import ProviderProtocolFamily


def build_protocol_continuation(
    request: ChatCompletionRequest,
    protocol_family: ProviderProtocolFamily,
    kind: ChatProtocolContinuationKind,
    items: tuple[dict[str, object], ...],
) -> ChatProtocolContinuation | None:
    if not items:
        return None
    return ChatProtocolContinuation(
        schema_version=1,
        protocol_family=protocol_family.value,
        provider_id=request.provider_id,
        model_id=request.model_id,
        kind=kind,
        items=items,
    )


def matching_continuation_items(
    message: ChatMessage,
    request: ChatCompletionRequest,
    protocol_family: ProviderProtocolFamily,
    kind: ChatProtocolContinuationKind,
) -> tuple[dict[str, object], ...]:
    continuation = message.protocol_continuation
    if continuation is None:
        return ()
    if (
        continuation.schema_version != 1
        or continuation.protocol_family != protocol_family.value
        or continuation.provider_id != request.provider_id
        or continuation.model_id != request.model_id
        or continuation.kind != kind
    ):
        return ()
    return tuple(dict(item) for item in continuation.items)
