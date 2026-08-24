from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from json import JSONDecodeError, dumps, loads
from threading import RLock
from typing import Any

from app.core.errors import BadRequestError, NotFoundError
from app.domain.llm.generation_params import LlmReasoningMode
from app.domain.project import Project, ProjectCategory, ProjectKind
from app.domain.project.project_conversation import (
    ProjectConversationSession,
    ProjectConversationSessionSettings,
)
from app.services.llm.functional_model_settings import (
    LlmFunctionalModelSettingsService,
    get_llm_functional_model_settings_service,
)
from app.services.project.project_conversations import (
    ProjectConversationService,
    get_project_conversation_service,
)
from app.services.project.project_files import (
    ProjectFileService,
    get_project_file_service,
)
from app.services.project.projects import (
    ProjectService,
    get_project_service,
)

DEFAULT_ROLE_NAME = "默认角色"
_ROLE_CONFIGURATION_FILES = (
    "profile.json",
    "model.json",
    "generation.json",
    "prompt.json",
    "response.json",
    "context.json",
    "memory.json",
    "tools.json",
)
_DEFAULT_ROLE_LOCK = RLock()


@dataclass(frozen=True, slots=True)
class ConversationRoleSeed:
    role_project_id: str
    provider_id: str | None
    model_id: str | None
    reasoning_mode: str | None
    settings: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ConversationRoleCatalog:
    default_role_project_id: str
    categories: tuple[ProjectCategory, ...]
    roles: tuple["ConversationRoleCatalogItem", ...]


@dataclass(frozen=True, slots=True)
class ConversationRoleCatalogItem:
    project: Project
    description: str | None
    is_default: bool


class RoleConfigurationApplicationService:
    """角色配置与会话之间的应用层边界。"""

    def __init__(
        self,
        project_service: ProjectService,
        conversation_service: ProjectConversationService,
        project_file_service: ProjectFileService,
        functional_model_settings_service: LlmFunctionalModelSettingsService,
    ) -> None:
        self._project_service = project_service
        self._conversation_service = conversation_service
        self._project_file_service = project_file_service
        self._functional_model_settings_service = functional_model_settings_service

    def ensure_default_role(self) -> Project:
        with _DEFAULT_ROLE_LOCK:
            existing = self._find_default_role()
            if existing is not None:
                self._ensure_default_conversation_role_setting(existing)
                return existing

            project = self._project_service.create_role_project(
                name=DEFAULT_ROLE_NAME,
                category_id=None,
            )
            try:
                seed = self._default_conversation_seed(project.project_id)
                session = self._conversation_service.create_session(
                    project.project_id,
                    provider_id=seed.provider_id,
                    model_id=seed.model_id,
                    reasoning_mode=seed.reasoning_mode,
                    settings=seed.settings,
                    role_project_id=project.project_id,
                )
                self.write_role_configuration(project.project_id, session)
            except Exception:
                self._project_service.delete_project(project.project_id)
                raise
            self._ensure_default_conversation_role_setting(project)
            return project

    def get_catalog(self) -> ConversationRoleCatalog:
        default_role = self.ensure_default_role()
        categories = tuple(
            category
            for category in self._project_service.list_project_categories()
            if category.category_kind is ProjectKind.ROLE
        )
        roles = []
        for project in self._role_projects():
            profile = self._read_json_file(project.project_id, "profile.json")
            roles.append(
                ConversationRoleCatalogItem(
                    project=project,
                    description=_optional_nonempty_string(profile.get("description")),
                    is_default=project.project_id == default_role.project_id,
                )
            )
        return ConversationRoleCatalog(
            default_role_project_id=default_role.project_id,
            categories=categories,
            roles=tuple(roles),
        )

    def build_new_session_seed(
        self,
        role_project_id: str | None = None,
    ) -> ConversationRoleSeed:
        default_role = self.ensure_default_role()
        role = (
            self._require_role_project(role_project_id)
            if role_project_id
            else self._resolve_default_conversation_role(default_role)
        )
        seed = self._default_conversation_seed(role.project_id)
        return self._overlay_role_on_seed(seed, role.project_id)

    def apply_role(
        self,
        project_id: str,
        session_id: str,
        role_project_id: str,
    ) -> ProjectConversationSession:
        self._require_role_project(role_project_id)
        current = self._require_session(project_id, session_id)
        patch = self._read_role_patch(role_project_id)
        return self._conversation_service.update_session(
            project_id,
            session_id,
            provider_id=patch.get("provider_id"),
            should_update_provider="provider_id" in patch,
            model_id=patch.get("model_id"),
            should_update_model="model_id" in patch,
            reasoning_mode=patch.get("reasoning_mode"),
            should_update_reasoning="reasoning_mode" in patch,
            settings=patch.get("settings"),
            should_update_settings=bool(patch.get("settings")),
            role_project_id=role_project_id,
            should_update_role_project_id=True,
        )

    def save_session_as_role(
        self,
        project_id: str,
        session_id: str,
        *,
        name: str,
        category_id: str | None,
    ) -> tuple[Project, ProjectConversationSession]:
        normalized_name = name.strip()
        if not normalized_name:
            raise BadRequestError("角色名称不能为空。")
        source_session = self._require_session(project_id, session_id)
        role_project = self._project_service.create_role_project(
            name=normalized_name,
            category_id=category_id,
        )
        try:
            self.write_role_configuration(role_project.project_id, source_session)
            role_session = self._conversation_service.create_session(
                role_project.project_id,
                provider_id=source_session.provider_id,
                model_id=source_session.model_id,
                reasoning_mode=source_session.reasoning_mode,
                settings=asdict(source_session.settings),
                role_project_id=role_project.project_id,
            )
        except Exception:
            self._project_service.delete_project(role_project.project_id)
            raise

        updated_source = self._conversation_service.update_session(
            project_id,
            session_id,
            role_project_id=role_project.project_id,
            should_update_role_project_id=True,
        )
        return role_project, updated_source

    def initialize_role_project(
        self,
        role_project_id: str,
    ) -> ProjectConversationSession:
        seed = self.build_new_session_seed()
        session = self._conversation_service.create_session(
            role_project_id,
            provider_id=seed.provider_id,
            model_id=seed.model_id,
            reasoning_mode=seed.reasoning_mode,
            settings=seed.settings,
            role_project_id=role_project_id,
        )
        self.write_role_configuration(role_project_id, session)
        return session

    def write_role_configuration(
        self,
        role_project_id: str,
        session: ProjectConversationSession,
    ) -> None:
        settings = session.settings
        documents = {
            "profile.json": {"description": ""},
            "model.json": {
                "provider_id": session.provider_id or "",
                "model_id": session.model_id or "",
                "reasoning_mode": session.reasoning_mode,
            },
            "generation.json": {
                "temperature": settings.temperature,
                "top_p": settings.top_p,
                "max_output_tokens": settings.max_output_tokens,
            },
            "prompt.json": {"system_prompt": settings.system_prompt},
            "response.json": {
                "return_cancelled_messages": settings.return_cancelled_messages,
                "return_user_before_cancelled": settings.return_user_before_cancelled,
                "streaming_enabled": settings.streaming_enabled,
                "auto_collapse_assistant_process": (
                    settings.auto_collapse_assistant_process
                ),
                "malformed_tool_call_recovery_enabled": (
                    settings.malformed_tool_call_recovery_enabled
                ),
                "upstream_retry_count": settings.upstream_retry_count,
            },
            "context.json": {
                "inject_message_timestamps": settings.inject_message_timestamps,
            },
            "memory.json": {
                "global_memory_enabled": settings.global_memory_enabled,
                "global_memory_extraction_enabled": (
                    settings.global_memory_extraction_enabled
                ),
                "project_memory_enabled": settings.project_memory_enabled,
                "project_memory_extraction_enabled": (
                    settings.project_memory_extraction_enabled
                ),
                "memory_compression_enabled": settings.memory_compression_enabled,
                "memory_context_token_trigger_threshold": (
                    settings.memory_context_token_trigger_threshold
                ),
                "memory_raw_context_token_reserve": (
                    settings.memory_raw_context_token_reserve
                ),
            },
            "tools.json": {
                "tools_enabled": settings.tools_enabled,
                "enabled_tool_names": (
                    list(settings.enabled_tool_names)
                    if settings.enabled_tool_names is not None
                    else None
                ),
                "max_tool_calls": settings.max_tool_calls,
                "tool_approval_mode": settings.tool_approval_mode,
            },
        }
        for file_name, payload in documents.items():
            self._project_file_service.write_text_file(
                role_project_id,
                file_name,
                f"{dumps(payload, ensure_ascii=False, indent=2)}\n",
            )

    def _find_default_role(self) -> Project | None:
        return next(
            (
                project
                for project in self._role_projects()
                if project.name == DEFAULT_ROLE_NAME
            ),
            None,
        )

    def _role_projects(self) -> tuple[Project, ...]:
        order_index = {
            project_id: index
            for index, project_id in enumerate(self._project_service.get_project_order())
        }
        return tuple(
            sorted(
                (
                    project
                    for project in self._project_service.list_projects()
                    if project.project_kind is ProjectKind.ROLE
                ),
                key=lambda item: (
                    (0, order_index[item.project_id])
                    if item.project_id in order_index
                    else (1, item.sort_order),
                    item.created_at,
                    item.project_id,
                ),
            )
        )

    def _ensure_default_conversation_role_setting(
        self,
        default_role: Project,
    ) -> None:
        self._resolve_default_conversation_role(default_role)

    def _resolve_default_conversation_role(
        self,
        default_role: Project,
    ) -> Project:
        profile = self._functional_model_settings_service.get_profile_settings(
            "defaultConversation",
        )
        payload = profile.settings if profile is not None else {}
        configured_role_id = _strict_nonempty_string(payload.get("roleProjectId"))
        try:
            configured_role = (
                self._project_service.get_project(configured_role_id)
                if configured_role_id
                else None
            )
        except BadRequestError:
            configured_role = None
        if (
            configured_role is not None
            and configured_role.project_kind is ProjectKind.ROLE
        ):
            return configured_role

        if profile is None:
            raise RuntimeError("默认会话角色设置不可用。")
        self._functional_model_settings_service.save_profile_settings(
            profile_key="defaultConversation",
            settings={"roleProjectId": default_role.project_id},
            version=profile.version,
        )
        return default_role

    def _require_role_project(self, role_project_id: str) -> Project:
        project = self._project_service.get_project(role_project_id.strip())
        if project is None or project.project_kind is not ProjectKind.ROLE:
            raise NotFoundError("选择的角色不存在。")
        return project

    def _require_session(
        self,
        project_id: str,
        session_id: str,
    ) -> ProjectConversationSession:
        session = self._conversation_service.get_session(project_id, session_id)
        if session is None:
            raise NotFoundError("会话不存在。")
        return session

    def _default_conversation_seed(
        self,
        role_project_id: str,
    ) -> ConversationRoleSeed:
        return ConversationRoleSeed(
            role_project_id=role_project_id,
            provider_id=None,
            model_id=None,
            reasoning_mode=None,
            settings=asdict(ProjectConversationSessionSettings()),
        )

    def _overlay_role_on_seed(
        self,
        seed: ConversationRoleSeed,
        role_project_id: str,
    ) -> ConversationRoleSeed:
        patch = self._read_role_patch(role_project_id)
        settings = dict(seed.settings)
        settings.update(patch.get("settings", {}))
        return ConversationRoleSeed(
            role_project_id=role_project_id,
            provider_id=patch.get("provider_id", seed.provider_id),
            model_id=patch.get("model_id", seed.model_id),
            reasoning_mode=patch.get("reasoning_mode", seed.reasoning_mode),
            settings=settings,
        )

    def _read_role_patch(self, role_project_id: str) -> dict[str, Any]:
        patch: dict[str, Any] = {"settings": {}}
        model = self._read_json_file(role_project_id, "model.json")
        provider_id = _strict_nonempty_string(model.get("provider_id"))
        model_id = _strict_nonempty_string(model.get("model_id"))
        if provider_id and model_id:
            patch["provider_id"] = provider_id
            patch["model_id"] = model_id
        if "reasoning_mode" in model:
            reasoning_value = model["reasoning_mode"]
            if reasoning_value is None:
                patch["reasoning_mode"] = None
            else:
                reasoning_mode = _valid_reasoning_mode(reasoning_value)
                if reasoning_mode is not None:
                    patch["reasoning_mode"] = reasoning_mode

        settings = patch["settings"]
        generation = self._read_json_file(role_project_id, "generation.json")
        _assign_valid_optional_float(
            settings,
            "temperature",
            generation,
            "temperature",
            minimum=0,
            maximum=2,
        )
        _assign_valid_optional_float(
            settings,
            "top_p",
            generation,
            "top_p",
            minimum=0,
            maximum=1,
        )
        _assign_valid_positive_int(
            settings,
            "max_output_tokens",
            generation.get("max_output_tokens"),
        )

        prompt = self._read_json_file(role_project_id, "prompt.json")
        if isinstance(prompt.get("system_prompt"), str):
            settings["system_prompt"] = prompt["system_prompt"]

        bool_files = {
            "response.json": (
                "return_cancelled_messages",
                "return_user_before_cancelled",
                "streaming_enabled",
                "auto_collapse_assistant_process",
                "malformed_tool_call_recovery_enabled",
            ),
            "context.json": (
                "inject_message_timestamps",
            ),
            "memory.json": (
                "global_memory_enabled",
                "global_memory_extraction_enabled",
                "project_memory_enabled",
                "project_memory_extraction_enabled",
                "memory_compression_enabled",
            ),
            "tools.json": ("tools_enabled",),
        }
        payloads: dict[str, dict[str, Any]] = {}
        for file_name, field_names in bool_files.items():
            payload = self._read_json_file(role_project_id, file_name)
            payloads[file_name] = payload
            for field_name in field_names:
                if isinstance(payload.get(field_name), bool):
                    settings[field_name] = payload[field_name]
        response = payloads.get("response.json", {})
        _assign_valid_nonnegative_int(
            settings,
            "upstream_retry_count",
            response.get("upstream_retry_count"),
        )

        memory = payloads["memory.json"]
        _assign_valid_positive_int(
            settings,
            "memory_context_token_trigger_threshold",
            memory.get("memory_context_token_trigger_threshold"),
        )
        _assign_valid_nonnegative_int(
            settings,
            "memory_raw_context_token_reserve",
            memory.get("memory_raw_context_token_reserve"),
        )

        tools = payloads["tools.json"]
        _assign_valid_tool_names(settings, tools)
        _assign_valid_positive_int(
            settings,
            "max_tool_calls",
            tools.get("max_tool_calls"),
        )
        tool_approval_mode = tools.get("tool_approval_mode")
        if tool_approval_mode in {"follow_tool_policy", "auto_allow_ask"}:
            settings["tool_approval_mode"] = tool_approval_mode
        return patch

    def _read_json_file(
        self,
        project_id: str,
        file_name: str,
    ) -> dict[str, Any]:
        if file_name not in _ROLE_CONFIGURATION_FILES:
            return {}
        try:
            content, _mtime = self._project_file_service.read_text_file(
                project_id,
                file_name,
            )
            payload = loads(content)
        except (NotFoundError, JSONDecodeError, TypeError, ValueError, OSError):
            return {}
        return payload if isinstance(payload, dict) else {}


def _strict_nonempty_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _optional_nonempty_string(value: object) -> str | None:
    return _strict_nonempty_string(value)


def _valid_reasoning_mode(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return LlmReasoningMode(value).value
    except ValueError:
        return None


def _assign_valid_positive_int(
    target: dict[str, Any],
    key: str,
    value: object,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return
    target[key] = value


def _assign_valid_nonnegative_int(
    target: dict[str, Any],
    key: str,
    value: object,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return
    target[key] = value


def _assign_valid_optional_float(
    target: dict[str, Any],
    target_key: str,
    source: dict[str, Any],
    source_key: str,
    *,
    minimum: float,
    maximum: float,
) -> None:
    if source_key not in source:
        return
    value = source[source_key]
    if value is None:
        target[target_key] = None
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return
    parsed = float(value)
    if minimum <= parsed <= maximum:
        target[target_key] = parsed


def _assign_valid_tool_names(
    target: dict[str, Any],
    tools: dict[str, Any],
) -> None:
    if "enabled_tool_names" not in tools:
        return
    value = tools["enabled_tool_names"]
    if value is None:
        target["enabled_tool_names"] = None
        return
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return
    names: list[str] = []
    seen: set[str] = set()
    for item in value:
        name = item.strip()
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    target["enabled_tool_names"] = names


@lru_cache
def get_role_configuration_application_service() -> (
    RoleConfigurationApplicationService
):
    return RoleConfigurationApplicationService(
        get_project_service(),
        get_project_conversation_service(),
        get_project_file_service(),
        get_llm_functional_model_settings_service(),
    )
