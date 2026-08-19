from copy import deepcopy

import pytest

from app.core.errors import BadRequestError
from app.domain.llm.functional_model_defaults import (
    DEFAULT_CONVERSATION_ROLE_SETTINGS_VERSION,
    DEFAULT_FUNCTIONAL_MAX_OUTPUT_TOKENS,
    GLOBAL_MEMORY_MANAGEMENT_SETTINGS_VERSION,
    NAMING_SETTINGS_VERSION,
    PROJECT_MEMORY_MANAGEMENT_SETTINGS_VERSION,
    get_default_functional_model_profile_settings,
    get_functional_model_profile_settings_version,
)
from app.infra.database.schema import ensure_database_schema
from app.repositories.llm.functional_model_settings_repository import (
    LlmFunctionalModelSettingsRepository,
)
from app.schemas.llm.functional_model_settings import LlmFunctionalModelSettingsResponse
from app.services.llm.functional_model_settings import LlmFunctionalModelSettingsService


def test_empty_functional_model_response_keeps_backend_defaults():
    defaults = get_default_functional_model_profile_settings("memoryCompression")
    expected_version = get_functional_model_profile_settings_version("memoryCompression")
    assert defaults is not None

    response = LlmFunctionalModelSettingsResponse.empty(
        default_settings=defaults,
        profile_key="memoryCompression",
        version=expected_version,
    )

    assert response.has_settings is False
    assert response.profile_key == "memoryCompression"
    assert response.version == expected_version
    assert response.default_settings is not None
    assert response.default_settings["modelSource"] == "session"
    assert response.default_settings["prompt"] == defaults["prompt"]


def test_memory_compression_uses_current_prompt_contract_version():
    assert get_functional_model_profile_settings_version("memoryCompression") == 32
    assert get_functional_model_profile_settings_version("naming") == (
        NAMING_SETTINGS_VERSION
    )
    assert get_functional_model_profile_settings_version(
        "projectMemoryManagement"
    ) == PROJECT_MEMORY_MANAGEMENT_SETTINGS_VERSION
    assert get_functional_model_profile_settings_version(
        "globalMemoryManagement"
    ) == GLOBAL_MEMORY_MANAGEMENT_SETTINGS_VERSION
    assert get_functional_model_profile_settings_version("defaultConversation") == (
        DEFAULT_CONVERSATION_ROLE_SETTINGS_VERSION
    )


def test_functional_model_old_version_resets_to_current_defaults(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    repository = LlmFunctionalModelSettingsRepository(database_path)
    service = LlmFunctionalModelSettingsService(repository)
    expected_version = get_functional_model_profile_settings_version("memoryCompression")

    old_settings = deepcopy(get_default_functional_model_profile_settings("memoryCompression"))
    old_settings["prompt"] = "旧提示词不做迁移修补"
    repository.save_settings(
        settings_id="memoryCompression",
        settings=old_settings,
        version=expected_version - 1,
    )

    settings = service.get_profile_settings("memoryCompression")

    assert settings is not None
    assert settings.version == expected_version
    assert settings.settings == get_default_functional_model_profile_settings("memoryCompression")


def test_functional_model_save_rejects_stale_version(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    repository = LlmFunctionalModelSettingsRepository(database_path)
    service = LlmFunctionalModelSettingsService(repository)
    defaults = get_default_functional_model_profile_settings("naming")
    expected_version = get_functional_model_profile_settings_version("naming")

    with pytest.raises(BadRequestError):
        service.save_profile_settings(
            profile_key="naming",
            settings=defaults,
            version=expected_version - 1,
        )


def test_functional_model_current_version_preserves_user_settings(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    repository = LlmFunctionalModelSettingsRepository(database_path)
    service = LlmFunctionalModelSettingsService(repository)
    expected_version = get_functional_model_profile_settings_version("memoryCompression")

    defaults = deepcopy(get_default_functional_model_profile_settings("memoryCompression"))
    custom_prompt = "你负责把历史上下文压缩成一份累计摘要。"
    defaults["generation"]["reasoning"]["mode"] = "off"
    defaults["prompt"] = custom_prompt
    saved = service.save_profile_settings(
        profile_key="memoryCompression",
        settings=defaults,
        version=expected_version,
    )
    loaded = service.get_profile_settings("memoryCompression")

    assert saved.settings["generation"]["reasoning"]["mode"] == "off"
    assert loaded is not None
    assert loaded.settings["prompt"] == custom_prompt


@pytest.mark.parametrize("profile_key", ["toolAgent", "visionPreprocessing"])
def test_removed_functional_model_profiles_are_rejected(tmp_path, profile_key):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    repository = LlmFunctionalModelSettingsRepository(database_path)
    service = LlmFunctionalModelSettingsService(repository)

    with pytest.raises(BadRequestError):
        service.get_profile_settings(profile_key)

    assert get_default_functional_model_profile_settings(profile_key) is None


def test_functional_model_defaults_use_32k_output_tokens():
    for profile_key in (
        "projectMemoryManagement",
        "globalMemoryManagement",
        "memoryCompression",
        "naming",
    ):
        defaults = get_default_functional_model_profile_settings(profile_key)
        assert defaults is not None
        assert defaults["generation"]["maxOutputTokens"] == DEFAULT_FUNCTIONAL_MAX_OUTPUT_TOKENS


def test_conversation_naming_defaults_to_cache_hit_optimization_mode():
    defaults = get_default_functional_model_profile_settings("naming")

    assert defaults is not None
    assert defaults["modelSource"] == "session"
    assert defaults["triggerTokenThreshold"] == 20_000
    assert defaults["output"]["format"] == "text"
    assert "当前唯一任务是" in defaults["prompt"]
    assert "只能调用一次 manage_ai_conversations" in defaults["prompt"]
    assert "action 必须使用 name_parent_session" in defaults["prompt"]
    assert "不得传入 session_id" in defaults["prompt"]
    assert "工具参数必须严格使用以下结构" not in defaults["prompt"]
    assert "如果工具执行失败，立即停止" in defaults["prompt"]


def test_memory_compression_defaults_use_single_prompt_and_high_reasoning():
    defaults = get_default_functional_model_profile_settings("memoryCompression")
    assert defaults is not None

    assert defaults["generation"]["maxOutputTokens"] == DEFAULT_FUNCTIONAL_MAX_OUTPUT_TOKENS
    assert defaults["generation"]["reasoning"]["mode"] == "high"
    assert defaults["blockingEnabled"] is False
    assert set(defaults) == {
        "blockingEnabled",
        "generation",
        "modelKey",
        "modelSource",
        "output",
        "prompt",
    }
    assert "累计摘要" in defaults["prompt"]
    assert "交接总结" in defaults["prompt"]
    assert "最近用户请求：" in defaults["prompt"]
    assert "只调用一次 submit_memory_compaction" in defaults["prompt"]
    assert '"result": {' in defaults["prompt"]
    assert "字段不得增加、删除或改名" in defaults["prompt"]
    assert "如果工具执行失败，立即停止" in defaults["prompt"]
    assert "不提出历史中没有的建议" in defaults["prompt"]
    assert '"handoff"' in defaults["prompt"]
    assert "【长期记忆变更开始｜在本条用户消息前生效】" in defaults["prompt"]
    assert "【长期记忆变更结束】" in defaults["prompt"]
    assert "逐字保留整个通知块" in defaults["prompt"]
    assert "对应事项的 content" in defaults["prompt"]
    assert "retained_user_requests" not in defaults["prompt"]
    assert '"source"' not in defaults["prompt"]
    assert '"title"' not in defaults["prompt"]


@pytest.mark.parametrize(
    ("profile_key", "threshold", "scope", "memory_label"),
    [
        ("projectMemoryManagement", 50_000, "project", "项目记忆"),
        ("globalMemoryManagement", 100_000, "global", "全局记忆"),
    ],
)
def test_memory_management_defaults_are_scoped(
    profile_key,
    threshold,
    scope,
    memory_label,
):
    defaults = get_default_functional_model_profile_settings(profile_key)

    assert defaults is not None
    assert defaults["modelSource"] == "session"
    assert defaults["triggerTokenThreshold"] == threshold
    assert defaults["blockingEnabled"] is False
    assert defaults["output"]["format"] == "text"
    assert "必须且只能调用 manage_memory 工具" in defaults["prompt"]
    assert "使用 operation=list 读取全部当前有效" in defaults["prompt"]
    assert "必须先完成一次全量读取" in defaults["prompt"]
    assert f"scope={scope}" in defaults["prompt"]
    assert f"{memory_label}已核对，无需更新。" in defaults["prompt"]
    assert f"{memory_label}管理已完成。" in defaults["prompt"]
    assert "不得继续、补做、重试或验证历史任务" in defaults["prompt"]
    assert "如果任意一次工具调用失败，立即停止" in defaults["prompt"]


def test_default_conversation_role_settings_are_available(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    repository = LlmFunctionalModelSettingsRepository(database_path)
    service = LlmFunctionalModelSettingsService(repository)

    settings = service.get_profile_settings("defaultConversation")

    assert settings is not None
    assert settings.version == DEFAULT_CONVERSATION_ROLE_SETTINGS_VERSION
    assert settings.settings == {"roleProjectId": ""}


def test_default_conversation_role_is_user_controlled(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    repository = LlmFunctionalModelSettingsRepository(database_path)
    service = LlmFunctionalModelSettingsService(repository)

    defaults = deepcopy(get_default_functional_model_profile_settings("defaultConversation"))
    defaults["roleProjectId"] = "role-1"
    saved = service.save_profile_settings(
        profile_key="defaultConversation",
        settings=defaults,
        version=DEFAULT_CONVERSATION_ROLE_SETTINGS_VERSION,
    )

    assert saved.settings["roleProjectId"] == "role-1"
