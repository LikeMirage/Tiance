from functools import lru_cache
from json import dumps
from typing import Literal

from app.core.errors import NotFoundError
from app.domain.usage_statistics import StatisticsMonth
from app.repositories.llm.usage_repository import LlmUsageRepository, get_llm_usage_repository
from app.repositories.llm.provider_catalog_repository import ProviderCatalogRepository, get_provider_catalog_repository
from app.repositories.llm.provider_file_store import ProviderFileStoreError
from app.repositories.project.conversation_repository import ProjectConversationRepository, get_project_conversation_repository
from app.repositories.workspace_activity_repository import WorkspaceActivityRepository, get_workspace_activity_repository
from app.services.tools.tool_call_records import ToolCallRecordService, get_tool_call_record_service

StatisticsKind = Literal["tokens", "runtime", "tools"]


class WorkspaceStatisticsService:
    def __init__(self, activity: WorkspaceActivityRepository, usage: LlmUsageRepository,
                 conversations: ProjectConversationRepository, tools: ToolCallRecordService,
                 providers: ProviderCatalogRepository) -> None:
        self._activity = activity
        self._usage = usage
        self._conversations = conversations
        self._tools = tools
        self._providers = providers

    def get_statistics(self, kind: StatisticsKind, month: str, timezone: str) -> dict:
        window = StatisticsMonth.parse(month, timezone)
        if kind == "tokens":
            result = self._usage.monthly_statistics(window)
            result["ranking"] = [self._model_details(row) for row in result.pop("top_models")]
            result.update(conversation_count=self._activity.count_conversations_created(),
                          sent_message_count=self._activity.count_user_messages_sent())
        elif kind == "runtime":
            result = self._activity.runtime_statistics(window.bounds)
            result["ranking"] = [self._task_details(row) for row in result.pop("top")]
        else:
            result = self._tools.monthly_statistics(window)
        result["daily"] = [{"date": date, "value": value}
                           for date, value in zip(window.dates, result["daily"])]
        return result

    def _model_details(self, row: dict) -> dict:
        # Historical IDs remain authoritative even when configuration is removed.
        provider_id, model_id = row["provider_id"], row["model_id"]
        try:
            provider = self._providers.get_entry(provider_id)
        except (ProviderFileStoreError, ValueError):
            # Names are optional; a broken/removed configuration cannot hide usage.
            provider = None
        provider_name = provider.display_name if provider is not None else provider_id
        return {"id": dumps([provider_id, model_id], ensure_ascii=False),
                "value": row["value"], "label": f"{provider_name} · {model_id}",
                "detail": f"{provider_id} · {model_id}",
                "provider_id": provider_id, "model_id": model_id}

    def _task_details(self, row: dict) -> dict:
        # Only the already-ranked rows reach project storage. Removed/unlinked tasks
        # retain their historical duration and can still be identified by source ID.
        result = {"id": row["source_id"], "value": row["amount"],
                  "project_id": row["project_id"], "session_id": row["session_id"],
                  "user_message_id": row["user_message_id"]}
        if not row["project_id"] or not row["session_id"]:
            return result
        try:
            session = self._conversations.get_session(row["project_id"], row["session_id"])
            if session is not None:
                result["label"] = session.title
                if row["user_message_id"]:
                    result["detail"] = self._conversations.get_task_excerpt(
                        row["project_id"], row["session_id"], row["user_message_id"],
                    )
        except NotFoundError:
            pass
        return result


@lru_cache
def get_workspace_statistics_service() -> WorkspaceStatisticsService:
    return WorkspaceStatisticsService(get_workspace_activity_repository(), get_llm_usage_repository(),
                                      get_project_conversation_repository(), get_tool_call_record_service(),
                                      get_provider_catalog_repository())
