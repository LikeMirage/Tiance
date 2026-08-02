from __future__ import annotations

from datetime import UTC, datetime
from dataclasses import dataclass
from functools import lru_cache
from json import dumps
from pathlib import Path
from threading import RLock

from app.core.errors import ConflictError
from app.domain.tools import ToolMetadataSnapshot, ToolRegistryEntry, ToolSummary
from app.infra.tools.tool_project_config_constants import TOOL_FOLDER_MANIFEST_FILE
from app.services.tools.tool_metadata import build_summary, is_enabled, load_tool
from app.services.tools.tool_projects import ToolProjectService, get_tool_project_service


@dataclass(frozen=True, slots=True)
class _ToolRegistryIndex:
    entries: tuple[ToolRegistryEntry, ...]
    by_name: dict[str, ToolRegistryEntry]
    enabled_by_name: dict[str, ToolRegistryEntry]
    metadata_by_name: dict[str, ToolMetadataSnapshot]
    search_text_by_name: dict[str, str]


_EMPTY_INDEX = _ToolRegistryIndex(
    entries=(),
    by_name={},
    enabled_by_name={},
    metadata_by_name={},
    search_text_by_name={},
)


class ToolRegistryService:
    def __init__(
        self,
        project_service: ToolProjectService,
    ) -> None:
        self._projects = project_service
        self._lock = RLock()
        self._index = _EMPTY_INDEX

    def rebuild_registry(self) -> tuple[ToolRegistryEntry, ...]:
        entries, metadata_by_name = self._scan_entries()
        next_index = _build_index(entries, metadata_by_name)
        with self._lock:
            self._index = next_index
        return entries

    def list_entries(self, *, enabled_only: bool = False) -> tuple[ToolRegistryEntry, ...]:
        with self._lock:
            entries = self._index.entries
        if enabled_only:
            entries = tuple(entry for entry in entries if entry.enabled)
        return _sort_entries(entries)

    def get_enabled_entry(self, tool_name: str) -> ToolRegistryEntry | None:
        with self._lock:
            return self._index.enabled_by_name.get(tool_name)

    def get_entry(self, tool_name: str) -> ToolRegistryEntry | None:
        with self._lock:
            return self._index.by_name.get(tool_name)

    def get_enabled_metadata(self, tool_name: str) -> ToolMetadataSnapshot | None:
        with self._lock:
            if tool_name not in self._index.enabled_by_name:
                return None
            return self._index.metadata_by_name.get(tool_name)

    def get_metadata(self, tool_name: str) -> ToolMetadataSnapshot | None:
        with self._lock:
            return self._index.metadata_by_name.get(tool_name)

    def search_entries(self, query: str, *, enabled_only: bool = True) -> tuple[ToolRegistryEntry, ...]:
        normalized_query = query.strip().casefold()
        if not normalized_query:
            return self.list_entries(enabled_only=enabled_only)

        with self._lock:
            entries = self._index.entries
            search_text_by_name = dict(self._index.search_text_by_name)

        matched = tuple(
            entry
            for entry in entries
            if (not enabled_only or entry.enabled)
            and normalized_query in search_text_by_name.get(entry.tool_name, "")
        )
        return _sort_entries(matched)

    def _scan_entries(self) -> tuple[tuple[ToolRegistryEntry, ...], dict[str, ToolMetadataSnapshot]]:
        indexed_at = datetime.now(UTC).isoformat()
        entries: list[ToolRegistryEntry] = []
        metadata_by_name: dict[str, ToolMetadataSnapshot] = {}
        seen_tool_names: set[str] = set()
        for category in self._projects.list_toolsets():
            for project in self._projects.list_tool_folders(category.category_id):
                if not (Path(project.root_path) / TOOL_FOLDER_MANIFEST_FILE).is_file():
                    continue
                loaded_tool = load_tool(project.root_path)
                summary = build_summary(loaded_tool, category=category.name)
                if summary.name in seen_tool_names:
                    raise ConflictError(
                        f"工具调用名称 '{summary.name}' 已重复，无法重建工具注册表。"
                    )
                seen_tool_names.add(summary.name)
                metadata_by_name[summary.name] = ToolMetadataSnapshot(
                    name=loaded_tool.name,
                    manifest=loaded_tool.manifest,
                    input_schema=loaded_tool.input_schema,
                    output_schema=loaded_tool.output_schema,
                    examples=loaded_tool.examples,
                )
                entries.append(
                    ToolRegistryEntry(
                        project_id=project.project_id,
                        category_id=category.category_id,
                        category_name=category.name,
                        tool_name=summary.name,
                        display_name=summary.display_name,
                        description=summary.description,
                        keywords=summary.keywords,
                        enabled=is_enabled(loaded_tool.manifest),
                        dynamic=summary.dynamic,
                        root_path=project.root_path,
                        runtime_entry=_read_runtime_entry(loaded_tool.manifest),
                        parameter_names=summary.parameter_names,
                        example_titles=summary.example_titles,
                        indexed_at=indexed_at,
                        updated_at=project.updated_at,
                        parallel=summary.parallel,
                        full_injection_char_count=_full_injection_char_count(
                            summary,
                            loaded_tool.input_schema,
                        ),
                        dynamic_injection_char_count=_dynamic_injection_char_count(summary),
                    )
                )
        return tuple(entries), metadata_by_name

def _read_runtime_entry(manifest: dict[str, object]) -> str:
    runtime = manifest.get("runtime")
    if not isinstance(runtime, dict):
        return ""
    entry = runtime.get("entry")
    return entry.strip() if isinstance(entry, str) else ""


def _build_index(
    entries: tuple[ToolRegistryEntry, ...],
    metadata_by_name: dict[str, ToolMetadataSnapshot],
) -> _ToolRegistryIndex:
    return _ToolRegistryIndex(
        entries=entries,
        by_name={entry.tool_name: entry for entry in entries},
        enabled_by_name={
            entry.tool_name: entry
            for entry in entries
            if entry.enabled
        },
        metadata_by_name=dict(metadata_by_name),
        search_text_by_name={
            entry.tool_name: _build_search_text(entry).casefold()
            for entry in entries
        },
    )


def _sort_entries(entries: tuple[ToolRegistryEntry, ...]) -> tuple[ToolRegistryEntry, ...]:
    return tuple(sorted(
        entries,
        key=lambda entry: (
            entry.category_name.casefold(),
            entry.display_name.casefold(),
            entry.tool_name,
        ),
    ))


def _build_search_text(entry: ToolRegistryEntry) -> str:
    return "\n".join(
        token
        for token in (
            entry.tool_name,
            entry.display_name,
            entry.description,
            entry.category_name,
            *entry.keywords,
            *entry.parameter_names,
            *entry.example_titles,
        )
        if token
    )


def _full_injection_char_count(summary: ToolSummary, input_schema: dict[str, object]) -> int:
    payload = {
        "name": summary.name,
        "description": summary.description,
        "parameters": input_schema,
    }
    return len(dumps(payload, ensure_ascii=False, sort_keys=True))


def _dynamic_injection_char_count(summary: ToolSummary) -> int:
    lines = [
        "",
        f"工具：{summary.name}",
        f"显示名称：{summary.display_name}",
        f"说明：{summary.description}",
        f"参数名：{', '.join(summary.parameter_names) if summary.parameter_names else '无'}",
    ]
    if summary.example_titles:
        lines.append("应用示例：")
        for index, title in enumerate(summary.example_titles, start=1):
            lines.append(f"{index}. {title}")
    return len("\n".join(lines))


@lru_cache
def get_tool_registry_service() -> ToolRegistryService:
    return ToolRegistryService(get_tool_project_service())
