from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from json import loads
from pathlib import PurePosixPath
import re

from app.core.errors import BadRequestError, NotFoundError
from app.domain.llm.chat import (
    ChatImageRef,
    ChatMessage,
    ChatMessageContentPart,
    ChatMessageContentPartType,
    ChatMessageRole,
    ChatToolResult,
)
from app.services.tools.tool_resource_uris import (
    canonical_local_resource_uri,
    project_relative_path,
)

_SUPPORTED_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "image/bmp",
}


def image_parts_from_tool_results(
    results: Iterable[ChatToolResult],
) -> tuple[ChatMessageContentPart, ...]:
    return deduplicate_image_parts(
        part
        for result in results
        if result.ok
        for part in image_parts_from_tool_content(result.content)
    )


def image_parts_from_tool_messages(
    messages: Iterable[ChatMessage],
) -> tuple[ChatMessageContentPart, ...]:
    return deduplicate_image_parts(
        part
        for message in messages
        if message.role == ChatMessageRole.TOOL
        for part in message.content_parts
        if part.type == ChatMessageContentPartType.IMAGE_REF
        and part.image_ref is not None
    )


def image_parts_from_tool_content(
    content: str, *, snapshot: Callable[[ChatImageRef, str | None], ChatImageRef] | None = None,
) -> tuple[ChatMessageContentPart, ...]:
    try:
        payload = loads(content)
    except (TypeError, ValueError):
        return ()
    if not isinstance(payload, dict) or payload.get("ok") is False:
        return ()
    blocks = payload.get("content")
    if not isinstance(blocks, list):
        return ()

    parts: list[ChatMessageContentPart] = []
    for block in blocks:
        part = _image_part_from_resource_link(block)
        if part is None or part.image_ref is None:
            continue
        if snapshot is not None:
            ref = _snapshot_tool_image(block, part.image_ref, snapshot)
            part = replace(part, image_ref=ref)
        parts.append(part)
    return deduplicate_image_parts(parts)


def _snapshot_tool_image(block: dict, returned: ChatImageRef, snapshot: Callable) -> ChatImageRef:
    metadata = block.get("_meta")
    source = metadata.get("tiance/imageSource") if isinstance(metadata, dict) else None
    if isinstance(source, dict):
        digest = source.get("sha256")
        scale = source.get("scalePercent")
        path = canonical_local_resource_uri(source.get("uri"))
        mime = _normalize_mime_type(source.get("mimeType"))
        valid_scale = type(scale) is int and 1 <= scale <= 100
        valid_digest = isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)
        if path and mime and valid_scale and valid_digest:
            ref = ChatImageRef(path=path, name=_optional_string(source.get("name")), mime_type=mime,
                               detail=returned.detail, scale_percent=scale)
            try:
                return snapshot(ref, digest)
            except (BadRequestError, NotFoundError, FileNotFoundError, PermissionError):
                # A renamed or edited source must not replace what the tool actually read.
                pass
    return snapshot(returned, None)


def tool_resource_message(
    parts: tuple[ChatMessageContentPart, ...],
) -> ChatMessage | None:
    if not parts:
        return None
    return ChatMessage(
        role=ChatMessageRole.USER,
        content="工具返回了以下图片资源。",
        content_parts=parts,
        internal_metadata={"derived_tool_resource_message": True},
    )


def without_tool_resource_messages(
    messages: Iterable[ChatMessage],
) -> tuple[ChatMessage, ...]:
    restored: list[ChatMessage] = []
    for message in messages:
        if not message.internal_metadata.get("derived_tool_resource_message"):
            restored.append(message)
            continue
        if not restored or restored[-1].role != ChatMessageRole.TOOL:
            continue
        target_index = len(restored) - 1
        target = restored[target_index]
        restored[target_index] = replace(
            target,
            content_parts=deduplicate_image_parts(
                (
                    *target.content_parts,
                    *message.content_parts,
                )
            ),
        )
    return tuple(restored)


def restore_tool_resource_messages(
    messages: Iterable[ChatMessage],
) -> tuple[ChatMessage, ...]:
    source_messages = without_tool_resource_messages(messages)
    restored: list[ChatMessage] = []
    index = 0
    while index < len(source_messages):
        message = source_messages[index]
        restored.append(message)
        index += 1
        if message.role != ChatMessageRole.ASSISTANT or not message.tool_calls:
            continue

        tool_messages: list[ChatMessage] = []
        while (
            index < len(source_messages)
            and source_messages[index].role == ChatMessageRole.TOOL
        ):
            tool_message = source_messages[index]
            tool_messages.append(tool_message)
            restored.append(
                replace(
                    tool_message,
                    content_parts=tuple(
                        part
                        for part in tool_message.content_parts
                        if part.type != ChatMessageContentPartType.IMAGE_REF
                    ),
                )
            )
            index += 1
        resource_message = tool_resource_message(
            image_parts_from_tool_messages(tool_messages)
        )
        if resource_message is not None:
            restored.append(resource_message)
    return tuple(restored)


def _image_part_from_resource_link(block: object) -> ChatMessageContentPart | None:
    if not isinstance(block, dict) or block.get("type") != "resource_link":
        return None
    if not _is_for_assistant(block.get("annotations")):
        return None

    mime_type = _normalize_mime_type(block.get("mimeType"))
    path = (
        project_relative_path(block.get("uri"))
        or canonical_local_resource_uri(block.get("uri"))
    )
    if mime_type is None or path is None:
        return None

    return ChatMessageContentPart(
        type=ChatMessageContentPartType.IMAGE_REF,
        image_ref=ChatImageRef(
            path=path,
            mime_type=mime_type,
            detail="auto",
            name=_optional_string(block.get("name")) or PurePosixPath(path).name,
            size_bytes=_positive_int(block.get("size")),
        ),
    )


def _normalize_mime_type(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.split(";", 1)[0].strip().lower()
    return normalized if normalized in _SUPPORTED_IMAGE_MIME_TYPES else None


def _is_for_assistant(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict):
        return False
    audience = value.get("audience")
    if audience is None:
        return True
    return isinstance(audience, list) and "assistant" in audience


def deduplicate_image_parts(
    parts: Iterable[ChatMessageContentPart],
) -> tuple[ChatMessageContentPart, ...]:
    unique: list[ChatMessageContentPart] = []
    seen: set[tuple[str, int]] = set()
    for part in parts:
        if part.image_ref is None:
            continue
        key = (part.image_ref.path, part.image_ref.scale_percent)
        if key in seen:
            continue
        unique.append(part)
        seen.add(key)
    return tuple(unique)


def _optional_string(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
