from app.domain.llm.chat import ChatCompletionRequest, ChatMessage, ChatMessageRole
from app.domain.llm.token_estimation_settings import (
    DEFAULT_TOKEN_ESTIMATION_SETTINGS,
    TokenEstimationSettings,
)
from app.infra.database import ensure_database_schema
from app.repositories.llm.token_estimation_settings_repository import (
    TokenEstimationSettingsRepository,
)
from app.services.llm.token_estimation_settings import (
    TokenEstimationSettingsService,
)
from app.services.llm.usage.estimation import (
    estimate_request_context_tokens,
    estimate_token_count,
)


def test_token_estimation_settings_persist_in_sqlite(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    service = TokenEstimationSettingsService(
        TokenEstimationSettingsRepository(database_path),
    )
    saved = service.save_settings(
        TokenEstimationSettings(
            ascii_chars_per_token=5,
            other_chars_per_token=1.5,
            message_overhead_tokens=6,
            image_placeholder_tokens=512,
        ),
    )

    reloaded = service.get_settings()

    assert saved.updated_at
    assert reloaded.ascii_chars_per_token == 5
    assert reloaded.other_chars_per_token == 1.5
    assert reloaded.message_overhead_tokens == 6
    assert reloaded.image_placeholder_tokens == 512


def test_token_estimation_settings_use_defaults_before_first_save(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    service = TokenEstimationSettingsService(
        TokenEstimationSettingsRepository(database_path),
    )

    assert service.get_settings() == DEFAULT_TOKEN_ESTIMATION_SETTINGS
    assert service.get_settings().other_chars_per_token == 2
    assert service.get_settings().image_placeholder_tokens == 2000


def test_estimator_uses_configured_character_ratios_and_message_overhead():
    settings = TokenEstimationSettings(
        ascii_chars_per_token=2,
        other_chars_per_token=2,
        message_overhead_tokens=10,
        image_placeholder_tokens=0,
    )
    request = ChatCompletionRequest(
        provider_id="test",
        model_id="test",
        messages=(
            ChatMessage(
                role=ChatMessageRole.USER,
                content="abcd中文",
            ),
        ),
    )

    assert estimate_token_count("abcd中文", settings) == 3
    assert estimate_request_context_tokens(request, settings) == 16


def test_json_estimate_uses_current_saved_settings(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    service = TokenEstimationSettingsService(
        TokenEstimationSettingsRepository(database_path),
    )
    service.save_settings(
        TokenEstimationSettings(
            ascii_chars_per_token=2,
            other_chars_per_token=2,
            message_overhead_tokens=0,
            image_placeholder_tokens=0,
        ),
    )

    assert service.estimate_json_tokens({"value": "abcd中文"}) == 10
