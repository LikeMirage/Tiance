from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.llm.chat import ChatMessage, ChatMessageRole
from app.services.project.conversation_message_groups import (
    protocol_safe_message_ids,
)
from app.services.project.conversation_memory_compaction import (
    COMPACTION_SOURCE_TYPE,
    compaction_source_message_ids,
    compaction_summary_text,
    latest_completed_compaction,
)
from app.services.project.conversation_request_provenance import conversation_message_id
from app.services.tools.tool_result_content import (
    restore_tool_resource_messages,
    without_tool_resource_messages,
)


@dataclass(frozen=True, slots=True)
class CompressedContextMessages:
    messages: tuple[ChatMessage, ...]
    used_compression_ids: tuple[str, ...]
    replaced_message_ids: tuple[str, ...]


def build_compressed_context_messages(
    *,
    messages: tuple[ChatMessage, ...],
    compression_records: list[dict[str, Any]],
) -> CompressedContextMessages | None:
    source_messages = without_tool_resource_messages(messages)
    active_record = latest_completed_compaction(compression_records)
    if active_record is None:
        return None

    active_source_ids = protocol_safe_message_ids(
        source_messages,
        compaction_source_message_ids(active_record),
    )
    active_source_id_set = set(active_source_ids)
    if not active_source_id_set:
        return None

    records_by_id = {
        compression_id: record
        for record in compression_records
        if (
            isinstance((compression_id := record.get("compression_id")), str)
            and compression_id
        )
    }
    represented_source_ids = {
        message_id
        for message in source_messages
        if (
            (message_id := conversation_message_id(message))
            and message_id in active_source_id_set
        )
    }
    summary_source_ids_by_index: dict[int, set[str]] = {}
    for index, message in enumerate(source_messages):
        compression_id = _summary_compression_id(message)
        record = records_by_id.get(compression_id)
        if record is None or record.get("source_type") != COMPACTION_SOURCE_TYPE:
            continue
        source_ids = set(compaction_source_message_ids(record))
        if not source_ids or not source_ids.issubset(active_source_id_set):
            continue
        summary_source_ids_by_index[index] = source_ids
        represented_source_ids.update(source_ids)

    if not active_source_id_set.issubset(represented_source_ids):
        return None

    output: list[ChatMessage] = []
    summary_inserted = False
    for index, message in enumerate(source_messages):
        message_id = conversation_message_id(message)
        replaces_source = (
            message_id is not None
            and message_id in active_source_id_set
        )
        replaces_summary = index in summary_source_ids_by_index
        if not replaces_source and not replaces_summary:
            output.append(message)
            continue
        if not summary_inserted:
            output.append(_compression_summary_message(active_record))
            summary_inserted = True

    if not summary_inserted:
        return None
    compression_id = active_record.get("compression_id")
    return CompressedContextMessages(
        messages=restore_tool_resource_messages(output),
        used_compression_ids=(
            (compression_id,)
            if isinstance(compression_id, str) and compression_id
            else ()
        ),
        replaced_message_ids=active_source_ids,
    )


def _summary_compression_id(message: ChatMessage) -> str:
    metadata = message.preview_metadata.get("memory_compression")
    if not isinstance(metadata, dict):
        return ""
    compression_id = metadata.get("compression_id")
    return compression_id if isinstance(compression_id, str) else ""


def _compression_summary_message(record: dict[str, Any]) -> ChatMessage:
    return ChatMessage(
        role=ChatMessageRole.ASSISTANT,
        content=compaction_summary_text(record),
        preview_metadata={
            "memory_compression": {
                "compression_id": record.get("compression_id"),
                "status": record.get("status"),
                "source_type": record.get("source_type"),
                "source_message_count": len(
                    compaction_source_message_ids(record)
                ),
                "item_count": len(
                    record.get("result", {}).get("items", [])
                    if isinstance(record.get("result"), dict)
                    else []
                ),
            }
        },
    )
