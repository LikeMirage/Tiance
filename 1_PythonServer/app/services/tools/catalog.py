from __future__ import annotations

from functools import lru_cache

from app.core.errors import BadRequestError, NotFoundError
from app.domain.tools import (
    ToolExampleDetail,
    ToolExampleSummary,
    ToolMetadataSnapshot,
    ToolParameterDetail,
    ToolSummary,
)
from app.services.tools.tool_registry import ToolRegistryService, get_tool_registry_service
from app.services.tools.tool_metadata import (
    example_detail,
    example_enabled,
    example_summary,
    example_title,
    normalize_tool_name,
)


class ToolCatalogService:
    def __init__(
        self,
        registry_service: ToolRegistryService,
    ) -> None:
        self._registry_service = registry_service

    def list_tool_summaries(self) -> tuple[ToolSummary, ...]:
        return tuple(
            entry.to_summary()
            for entry in self._registry_service.list_entries(enabled_only=True)
        )

    def get_tool_summary(self, tool_name: str) -> ToolSummary:
        normalized_name = normalize_tool_name(tool_name)
        entry = self._registry_service.get_enabled_entry(normalized_name)
        if entry is not None:
            return entry.to_summary()
        disabled_entry = self._registry_service.get_entry(normalized_name)
        if disabled_entry is not None and not disabled_entry.enabled:
            raise NotFoundError("此工具已关闭。")
        raise NotFoundError(f"工具 '{normalized_name}' 不存在。")

    def get_tool_parameters(self, tool_name: str) -> ToolParameterDetail:
        metadata = self._find_enabled_metadata(tool_name)
        return ToolParameterDetail(
            name=metadata.name,
            input_schema=metadata.input_schema,
        )

    def list_tool_example_summaries(
        self,
        tool_name: str,
    ) -> tuple[ToolExampleSummary, ...]:
        metadata = self._find_enabled_metadata(tool_name)
        return tuple(
            example_summary(index, example)
            for index, example in metadata.examples
            if example_enabled(example)
        )

    def get_tool_examples(
        self,
        tool_name: str,
        *,
        titles: tuple[str, ...] = (),
        indexes: tuple[int, ...] = (),
        include_all: bool = False,
    ) -> tuple[ToolExampleDetail, ...]:
        metadata = self._find_enabled_metadata(tool_name)
        if include_all:
            return tuple(
                example_detail(index, example)
                for index, example in metadata.examples
                if example_enabled(example)
            )
        if not titles and not indexes:
            raise BadRequestError("必须指定要读取的示例标题、序号，或读取全部示例。")

        examples_by_index = {
            index: example
            for index, example in metadata.examples
            if example_enabled(example)
        }
        selected: list[ToolExampleDetail] = []
        seen_indexes: set[int] = set()
        for index in indexes:
            example = examples_by_index.get(index)
            if example is None:
                raise NotFoundError(f"工具示例序号 '{index}' 不存在。")
            if index not in seen_indexes:
                selected.append(example_detail(index, example))
                seen_indexes.add(index)

        normalized_titles = tuple(title.strip() for title in titles if title.strip())
        for title in normalized_titles:
            matched = False
            for index, example in metadata.examples:
                if not example_enabled(example):
                    continue
                if example_title(example) != title:
                    continue
                matched = True
                if index not in seen_indexes:
                    selected.append(example_detail(index, example))
                    seen_indexes.add(index)
            if not matched:
                raise NotFoundError(f"工具示例 '{title}' 不存在。")

        return tuple(selected)

    def _find_enabled_metadata(self, tool_name: str) -> ToolMetadataSnapshot:
        normalized_name = normalize_tool_name(tool_name)
        metadata = self._registry_service.get_enabled_metadata(normalized_name)
        if metadata is not None:
            return metadata
        disabled_entry = self._registry_service.get_entry(normalized_name)
        if disabled_entry is not None and not disabled_entry.enabled:
            raise NotFoundError("此工具已关闭。")
        raise NotFoundError(f"工具 '{normalized_name}' 不存在。")


@lru_cache
def get_tool_catalog_service() -> ToolCatalogService:
    return ToolCatalogService(get_tool_registry_service())
