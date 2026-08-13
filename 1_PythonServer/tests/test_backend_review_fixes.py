import asyncio
import sqlite3

import httpx
import pytest
from watchfiles import Change

from app.core.config import Settings
from app.core.errors import BadRequestError, normalize_upstream_http_error
from app.domain.llm.chat import ChatStreamEventKind
from app.domain.llm.discovered_model import DiscoveredModel
from app.domain.llm.provider_catalog import (
    AuthScheme,
    ModelDiscoveryStrategy,
    ProviderCatalogEntry,
    ProviderEndpointTemplate,
    ProviderProtocolFamily,
    default_model_discovery_strategy,
)
from app.domain.llm.provider_cloud_model import ProviderCloudModelCache
from app.domain.llm.provider_config import ProviderApiKeyConfig, ProviderConfig
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.domain.llm.usage import LlmProviderModelUsageSummary, LlmUsageSummary
from app.domain.project import Project
from app.infra.database import ensure_database_schema, run_database_migrations
from app.infra.database.schema import MIGRATIONS
from app.infra.secrets import secret_codec as secret_codec_module
from app.infra.llm import chat_remote_client as chat_remote_client_module
from app.infra.llm.anthropic_auth import build_anthropic_auth_headers
from app.infra.llm.chat_adapters import OpenAICompatibleChatAdapter
from app.infra.llm.chat_remote_client import ChatRemoteClient
from app.infra.llm.openai_client import OpenAIModelDiscoveryClient
from app.infra.llm.provider_model_probe_client import ProviderModelProbeClient
from app.infra.llm.provider_remote_client import ProviderRemoteClient
from app.infra.projects import project_file_watcher as project_file_watcher_module
from app.infra.projects.project_file_watcher import (
    _coalesce_changes,
    project_file_change_paths,
    watch_project_file_changes,
)
from app.repositories.llm.provider_cloud_model_repository import ProviderCloudModelRepository
from app.repositories.llm.provider_config_repository import ProviderConfigRepository
from app.repositories.llm.provider_file_store import ProviderFileStore
from app.schemas.llm.provider_configs import ProviderConfigResponse
from app.services.llm.provider import config_runtime as config_runtime_module
from app.services.llm.provider import config_writer as config_writer_module
from app.services.llm.provider.api_base_url_validation import normalize_provider_api_base_url
from app.services.llm.provider.config_runtime import ProviderConfigRuntimeResolver
from app.services.llm.provider.config_writer import ProviderApiKeyConfigInput, ProviderConfigWriter
from app.services.llm.provider.storage_bootstrap import ensure_provider_file_storage
from app.services.llm.usage.service import LlmUsageService
from app.services.project.projects import ProjectService


def test_create_app_does_not_bootstrap_during_factory(monkeypatch):
    from app import main

    calls = []
    monkeypatch.setattr(main, "bootstrap_application", lambda: calls.append("bootstrapped"))
    monkeypatch.setattr(main, "start_shared_http_client", lambda: calls.append("http-started"))

    main.create_app()

    assert calls == []


def test_create_app_mounts_frontend_dist_when_index_exists(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app import main

    dist_path = tmp_path / "dist"
    dist_path.mkdir()
    (dist_path / "index.html").write_text("<!doctype html><title>Tiance App</title>", encoding="utf-8")
    settings = Settings(
        frontend_dist_dir=str(dist_path),
        database_file=str(tmp_path / "tiance.db"),
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)

    application = main.create_app()
    response = TestClient(application).get("/app/")

    assert response.status_code == 200
    assert "Tiance App" in response.text


def test_app_lifespan_bootstraps_http_client_and_closes(monkeypatch):
    from app import main

    calls = []
    monkeypatch.setattr(main, "bootstrap_application", lambda: calls.append("bootstrapped"))
    monkeypatch.setattr(main, "start_shared_http_client", lambda: calls.append("http-started"))

    async def close_http_clients():
        calls.append("http-closed")

    monkeypatch.setattr(main, "close_shared_http_clients", close_http_clients)

    async def run_lifespan():
        async with main._lifespan(None):
            assert calls == ["bootstrapped", "http-started"]

    asyncio.run(run_lifespan())

    assert calls == ["bootstrapped", "http-started", "http-closed"]


def test_shared_http_client_reuses_and_closes_within_event_loop():
    from app.infra.http_client import close_shared_http_clients, get_shared_http_client

    async def run_client_lifecycle():
        first = get_shared_http_client()
        second = get_shared_http_client()

        assert first is second
        assert not first.is_closed

        await close_shared_http_clients()

        assert first.is_closed

    asyncio.run(run_client_lifecycle())


def test_stream_body_reads_error_response_before_raising(monkeypatch):
    fake_response = _UnreadErrorStreamResponse()
    monkeypatch.setattr(
        chat_remote_client_module,
        "get_shared_http_client",
        lambda: _FakeStreamingHttpClient(fake_response),
    )

    async def collect():
        return [
            chunk
            async for chunk in ChatRemoteClient()._stream_body(
                "https://example.test/chat/completions",
                {},
                {},
            )
        ]

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(collect())

    assert fake_response.was_read is True


def test_normalize_upstream_http_error_handles_unread_streaming_response():
    request = httpx.Request("POST", "https://example.test/chat/completions")
    response = httpx.Response(
        400,
        request=request,
        stream=httpx.ByteStream(b'{"error":{"message":"bad request"}}'),
    )

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        response.raise_for_status()

    normalized = normalize_upstream_http_error(exc_info.value)

    assert normalized.code == "upstream_invalid_request"
    assert normalized.message == "上游供应商返回 400。"


def test_cors_defaults_are_explicit_and_do_not_allow_null_or_any_localhost():
    settings = Settings()

    assert "null" not in settings.cors_origins
    assert "file://" not in settings.cors_origins
    assert settings.cors_origin_regex is None
    assert "http://127.0.0.1:18100" in settings.cors_origins


def test_project_file_change_paths_keeps_user_directories_visible(tmp_path):
    root = tmp_path
    changes = {
        (Change.modified, str(root / "src" / "app.py")),
        (Change.added, str(root / "node_modules" / "pkg" / "index.js")),
        (Change.modified, str(root / ".git" / "index")),
        (Change.deleted, str(root / "dist" / "bundle.js")),
    }

    assert project_file_change_paths(root, changes) == [
        ".git/index",
        "dist/bundle.js",
        "node_modules/pkg/index.js",
        "src/app.py",
    ]


def test_project_file_change_paths_marks_bulk_changes_as_overflow(tmp_path):
    root = tmp_path
    changes = {
        (Change.added, str(root / "cloned-repository" / "src" / f"file-{index}.py"))
        for index in range(300)
    }

    assert project_file_change_paths(root, changes) is None


def test_project_file_change_paths_ignores_internal_tiance_directory(tmp_path):
    root = tmp_path / "project"
    changes = {
        (Change.modified, str(root / ".Tiance" / "conversations" / "messages.jsonl")),
        (Change.modified, str(root / "notes.md")),
    }

    assert project_file_change_paths(root, changes) == ["notes.md"]


def test_project_file_watcher_uses_native_notifications_and_only_filters_internal_data(
    monkeypatch,
    tmp_path,
):
    observed_options = {}
    monkeypatch.setattr(project_file_watcher_module.sys, "platform", "linux")

    async def fake_awatch(*_args, **options):
        observed_options.update(options)
        if False:
            yield set()

    monkeypatch.setattr(project_file_watcher_module, "awatch", fake_awatch)
    async def consume():
        return [
            change
            async for change in watch_project_file_changes(
                tmp_path,
                project_id="project-1",
            )
        ]

    events = asyncio.run(consume())
    assert [event.kind for event in events] == ["ready"]
    assert "force_polling" not in observed_options
    watch_filter = observed_options["watch_filter"]
    assert watch_filter(Change.added, str(tmp_path / "node_modules" / "pkg" / "index.js"))
    assert not watch_filter(Change.modified, str(tmp_path / ".Tiance" / "tiance.db-wal"))


def test_project_file_change_paths_does_not_resolve_directory_links(tmp_path):
    root = tmp_path / "project"
    linked_path = root / "node_modules" / "linked-package" / "index.js"

    assert project_file_change_paths(root, {(Change.modified, str(linked_path))}) == [
        "node_modules/linked-package/index.js",
    ]


def test_project_file_watcher_coalesces_bursty_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(project_file_watcher_module, "_WATCH_QUIET_SECONDS", 0.01)
    monkeypatch.setattr(project_file_watcher_module, "_WATCH_MAX_BATCH_SECONDS", 0.05)

    async def source():
        yield {(Change.added, str(tmp_path / "first.txt"))}
        await asyncio.sleep(0.005)
        yield {(Change.modified, str(tmp_path / "second.txt"))}

    async def consume():
        return [changes async for changes in _coalesce_changes(source())]

    assert asyncio.run(consume()) == [{
        (Change.added, str(tmp_path / "first.txt")),
        (Change.modified, str(tmp_path / "second.txt")),
    }]


def test_deepseek_new_session_defaults_to_tool_thinking_return():
    from app.api.routes.project.conversations import _settings_with_model_defaults

    assert _settings_with_model_defaults("deepseek", "deepseek-v4-flash", None) == {
        "return_thinking_content": True,
    }
    assert _settings_with_model_defaults("custom", "my-deepseek-model", None) == {
        "return_thinking_content": True,
    }
    assert _settings_with_model_defaults(
        "deepseek",
        "deepseek-v4-flash",
        {"return_thinking_content": False},
    ) == {
        "return_thinking_content": False,
    }
    assert _settings_with_model_defaults("volcengine", "doubao", None) is None


def test_provider_config_response_reports_real_secret_presence():
    config = _provider_config()

    response = ProviderConfigResponse.from_domain(
        config,
        api_key_presence_by_id={"key-1": False},
        prompt_cache_retention_seconds=300,
    )

    assert response.api_keys[0].has_api_key is False
    assert response.prompt_cache_retention_seconds == 300


def test_runtime_resolver_rejects_missing_database_ciphertext():
    config = _provider_config()
    resolver = ProviderConfigRuntimeResolver(
        _FakeApiKeyScheduler(),
    )

    with pytest.raises(BadRequestError, match="API Key 密文不可用"):
        resolver.resolve_runtime_credentials(
            _provider_entry(
                provider_id="deepseek",
                protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE,
            ),
            config,
        )


def test_runtime_resolver_uses_sqlite_encrypted_secret(monkeypatch):
    monkeypatch.setattr(
        config_runtime_module,
        "resolve_api_key_secret",
        lambda api_key: "sk-runtime" if api_key.api_key_ciphertext == "ciphertext" else None,
    )
    config = _provider_config(
        api_key_ciphertext="ciphertext",
    )
    resolver = ProviderConfigRuntimeResolver(
        _FakeApiKeyScheduler(),
    )

    _runtime_config, selected_api_key = resolver.resolve_runtime_credentials(
        _provider_entry(
            provider_id="deepseek",
            protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE,
        ),
        config,
    )

    assert selected_api_key.api_key == "sk-runtime"


def test_runtime_resolver_allows_provider_without_api_key_config():
    config = _provider_config_without_api_keys()
    resolver = ProviderConfigRuntimeResolver(
        _FakeApiKeyScheduler(),
    )

    runtime_config, selected_api_key = resolver.resolve_runtime_credentials(
        _provider_entry(
            provider_id="deepseek",
            protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE,
        ),
        config,
    )

    assert runtime_config.provider_id == "deepseek"
    assert selected_api_key.key_id == ""
    assert selected_api_key.api_key == ""
    assert selected_api_key.api_key_hint is None


def test_gemini_probe_sends_key_in_header_and_does_not_return_secret_url():
    captured = {}

    async def post_json(url, headers, body):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        return {}

    result = asyncio.run(
        ProviderModelProbeClient().probe_model(
            _provider_entry(
                provider_id="gemini",
                protocol_family=ProviderProtocolFamily.GEMINI_GENERATE_CONTENT,
                auth_scheme=AuthScheme.X_GOOG_API_KEY,
            ),
            ProviderRuntimeConfig(
                provider_id="gemini",
                display_name="Gemini",
                api_base_url=(
                    "https://generativelanguage.googleapis.com/"
                    "v1beta/models/{model}:{action}"
                ),
            ),
            "secret-key",
            "gemini-pro",
            post_json,
        )
    )

    assert "secret-key" not in captured["url"]
    assert captured["url"].endswith("/v1beta/models/gemini-pro:generateContent")
    assert captured["headers"]["x-goog-api-key"] == "secret-key"
    assert "secret-key" not in result["checked_url"]


def test_anthropic_auth_uses_configured_header_without_duplication():
    moonshot_headers = build_anthropic_auth_headers(
        AuthScheme.BEARER_TOKEN,
        "secret-key",
    )
    anthropic_headers = build_anthropic_auth_headers(
        AuthScheme.X_API_KEY,
        "secret-key",
    )

    assert moonshot_headers["Authorization"] == "Bearer secret-key"
    assert "x-api-key" not in moonshot_headers
    assert anthropic_headers["x-api-key"] == "secret-key"
    assert "Authorization" not in anthropic_headers


def test_anthropic_generation_provider_keeps_independent_openai_model_discovery():
    calls = []

    class FakeDiscoveryClient:
        def __init__(self, name):
            self.name = name

        async def discover_models(self, *args):
            calls.append((self.name, args))
            return []

    client = ProviderRemoteClient()
    client._openai_client = FakeDiscoveryClient("openai")
    client._anthropic_client = FakeDiscoveryClient("anthropic")

    asyncio.run(
        client.discover_models(
            _provider_entry(
                provider_id="moonshot",
                protocol_family=ProviderProtocolFamily.ANTHROPIC_MESSAGES,
                model_discovery_strategy=ModelDiscoveryStrategy.OPENAI_MODELS,
            ),
            ProviderRuntimeConfig(
                provider_id="moonshot",
                display_name="Moonshot",
                api_base_url="https://api.moonshot.cn/anthropic/v1/messages",
                model_discovery_url="https://api.moonshot.cn/v1/models",
            ),
            "secret-key",
        )
    )

    assert [name for name, _args in calls] == ["openai"]


@pytest.mark.parametrize(
    "api_base_url",
    (
        "http://0.0.0.0:8000",
        "http://[::]:8000",
        "http://224.0.0.1:8000",
        "https://api.example.test",
        "https://api.example.test?token=secret",
        "https://user:pass@api.example.test",
    ),
)
def test_provider_api_url_rejects_unusable_or_secret_parts(api_base_url):
    with pytest.raises(BadRequestError):
        normalize_provider_api_base_url(api_base_url)


@pytest.mark.parametrize(
    ("api_base_url", "expected"),
    (
        ("http://127.0.0.1:8317/v1/", "http://127.0.0.1:8317/v1"),
        ("http://127.0.0.2:8000/v1/models", "http://127.0.0.2:8000/v1/models"),
        ("http://localhost:8000/v1", "http://localhost:8000/v1"),
        ("http://[::1]:8000/v1", "http://[::1]:8000/v1"),
    ),
)
def test_provider_api_base_url_allows_loopback_addresses(api_base_url, expected):
    assert normalize_provider_api_base_url(api_base_url) == expected


@pytest.mark.parametrize(
    "api_url",
    (
        "http://192.168.1.10:8000/v1/responses",
        "http://169.254.1.10:8000/v1/chat/completions",
        "http://model-server.local:8000/v1/responses",
    ),
)
def test_provider_api_url_allows_private_network_services(api_url):
    assert normalize_provider_api_base_url(api_url) == api_url


def test_provider_api_base_url_normalizes_supported_public_url():
    assert normalize_provider_api_base_url(" HTTPS://API.EXAMPLE.TEST/v1/ ") == (
        "https://api.example.test/v1"
    )


@pytest.mark.parametrize(
    "protocol_family",
    (
        ProviderProtocolFamily.OPENAI_COMPATIBLE,
        ProviderProtocolFamily.OPENAI_RESPONSES,
        ProviderProtocolFamily.ANTHROPIC_MESSAGES,
    ),
)
def test_model_probe_uses_configured_generation_url_without_appending_paths(
    protocol_family,
):
    configured_url = "https://gateway.example/custom/generate"
    captured = {}

    async def post_json(url, _headers, _body):
        captured["url"] = url
        return {}

    asyncio.run(
        ProviderModelProbeClient().probe_model(
            _provider_entry(provider_id="custom", protocol_family=protocol_family),
            ProviderRuntimeConfig(
                provider_id="custom",
                display_name="Custom",
                api_base_url=configured_url,
            ),
            "secret-key",
            "model-a",
            post_json,
        )
    )

    assert captured["url"] == configured_url


def test_model_discovery_uses_independent_configured_url_without_derivation():
    captured = {}

    async def get_json(url, headers):
        del headers
        captured["url"] = url
        return {"data": []}

    asyncio.run(
        OpenAIModelDiscoveryClient().discover_models(
            AuthScheme.BEARER_TOKEN,
            ProviderRuntimeConfig(
                provider_id="custom",
                display_name="Custom",
                api_base_url="https://gateway.example/custom/generate",
                model_discovery_url="https://catalog.example/custom/models-list",
            ),
            "secret-key",
            get_json,
        )
    )

    assert captured["url"] == "https://catalog.example/custom/models-list"


def test_openai_stream_bad_payload_returns_protocol_error_event():
    async def stream_body(_url, _headers, _body):
        yield b"data: {not-json}\n\n"

    async def collect():
        adapter = OpenAICompatibleChatAdapter()
        return [
            event
            async for event in adapter.stream(
                provider_template=_provider_entry(
                    provider_id="deepseek",
                    protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE,
                ),
                runtime_config=ProviderRuntimeConfig(
                    provider_id="deepseek",
                    display_name="DeepSeek",
                    api_base_url="https://example.test",
                ),
                api_key="sk-test",
                request=_chat_request(),
                stream_body=stream_body,
            )
        ]

    events = asyncio.run(collect())

    assert len(events) == 1
    assert events[0].kind == ChatStreamEventKind.ERROR
    assert "无法解析" in (events[0].error or "")


def test_openai_stream_accepts_sse_data_without_space_and_final_newline():
    async def stream_body(_url, _headers, _body):
        yield b'data:{"choices":[{"delta":{"content":"he"}}]}\n\n'
        yield b'data:{"choices":[{"delta":{"content":"llo"},"finish_reason":"stop"}]}'

    async def collect():
        adapter = OpenAICompatibleChatAdapter()
        return [
            event
            async for event in adapter.stream(
                provider_template=_provider_entry(
                    provider_id="deepseek",
                    protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE,
                ),
                runtime_config=ProviderRuntimeConfig(
                    provider_id="deepseek",
                    display_name="DeepSeek",
                    api_base_url="https://example.test",
                ),
                api_key="sk-test",
                request=_chat_request(),
                stream_body=stream_body,
            )
        ]

    events = asyncio.run(collect())

    assert [event.kind for event in events] == [
        ChatStreamEventKind.DELTA,
        ChatStreamEventKind.DELTA,
        ChatStreamEventKind.DONE,
    ]
    assert "".join(event.content or "" for event in events) == "hello"
    assert events[-1].finish_reason == "stop"


def test_openai_stream_accepts_multiline_sse_data_event():
    async def stream_body(_url, _headers, _body):
        yield (
            b'data: {"choices":\n'
            b'data: [{"delta":{"content":"hello"},"finish_reason":"stop"}]}\n\n'
        )

    async def collect():
        adapter = OpenAICompatibleChatAdapter()
        return [
            event
            async for event in adapter.stream(
                provider_template=_provider_entry(
                    provider_id="deepseek",
                    protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE,
                ),
                runtime_config=ProviderRuntimeConfig(
                    provider_id="deepseek",
                    display_name="DeepSeek",
                    api_base_url="https://example.test",
                ),
                api_key="sk-test",
                request=_chat_request(),
                stream_body=stream_body,
            )
        ]

    events = asyncio.run(collect())

    assert [event.kind for event in events] == [
        ChatStreamEventKind.DELTA,
        ChatStreamEventKind.DONE,
    ]
    assert events[0].content == "hello"
    assert events[-1].finish_reason == "stop"


def test_openai_stream_emits_tool_call_delta_before_complete_tool_call():
    async def stream_body(_url, _headers, _body):
        yield (
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1",'
            b'"function":{"name":"read_text_file"}}]}}]}\n\n'
        )
        yield (
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
            b'"function":{"arguments":"{\\"file_path\\":\\"C:/work/app.py\\"}"}}]},'
            b'"finish_reason":"tool_calls"}]}\n\n'
        )

    async def collect():
        adapter = OpenAICompatibleChatAdapter()
        return [
            event
            async for event in adapter.stream(
                provider_template=_provider_entry(
                    provider_id="deepseek",
                    protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE,
                ),
                runtime_config=ProviderRuntimeConfig(
                    provider_id="deepseek",
                    display_name="DeepSeek",
                    api_base_url="https://example.test",
                ),
                api_key="sk-test",
                request=_chat_request(),
                stream_body=stream_body,
            )
        ]

    events = asyncio.run(collect())
    kinds = [event.kind for event in events]

    assert kinds[:3] == [
        ChatStreamEventKind.TOOL_CALL_DELTA,
        ChatStreamEventKind.TOOL_CALL_DELTA,
        ChatStreamEventKind.TOOL_CALL,
    ]
    assert events[0].tool_call is not None
    assert events[0].tool_call.name == "read_text_file"
    assert events[0].tool_call.arguments == ""
    assert events[1].tool_call is not None
    assert events[1].tool_call.name == "read_text_file"
    assert events[1].tool_call.arguments == '{"file_path":"C:/work/app.py"}'
    assert events[2].tool_call is not None
    assert events[2].tool_call.name == "read_text_file"
    assert events[2].tool_call.arguments == '{"file_path":"C:/work/app.py"}'


def test_provider_cloud_cache_tracks_only_current_binding(tmp_path):
    repository = ProviderCloudModelRepository(ProviderFileStore(tmp_path / "providers"))

    repository.replace_provider_cache(_cloud_cache("https://a.example", "model-a"))
    repository.replace_provider_cache(_cloud_cache("https://b.example", "model-b"))

    cache_a = repository.get_cache(
        provider_id="openai-compatible",
        protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE.value,
        api_base_url="https://a.example",
    )
    cache_b = repository.get_cache(
        provider_id="openai-compatible",
        protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE.value,
        api_base_url="https://b.example",
    )

    assert cache_a is None
    assert [model.model_id for model in cache_b.models] == ["model-b"]


def test_duplicate_api_key_id_creates_distinct_key_records(monkeypatch, tmp_path):
    monkeypatch.setattr(
        config_writer_module,
        "encrypt_secret",
        lambda value: f"encrypted:{value}",
    )
    config_repository = _provider_config_repository(tmp_path)
    writer = ProviderConfigWriter(config_repository, _FakeCloudModelRepository())
    provider_template = _provider_entry(
        provider_id="deepseek",
        protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE,
    )

    writer.save_config(
        provider_template=provider_template,
        api_base_url=None,
        enabled=True,
        api_keys=(ProviderApiKeyConfigInput("primary", "sk-old", 1),),
    )
    saved = writer.save_config(
        provider_template=provider_template,
        api_base_url=None,
        enabled=True,
        api_keys=(
            ProviderApiKeyConfigInput("primary", None, 1),
            ProviderApiKeyConfigInput("primary", "sk-new", 1),
        ),
    )

    assert len(saved.api_keys) == 2
    assert len({api_key.key_id for api_key in saved.api_keys}) == 2


def test_provider_config_writer_persists_encrypted_file_secret(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        config_writer_module,
        "encrypt_secret",
        lambda value: f"encrypted:{value}",
    )
    config_repository = _provider_config_repository(tmp_path)
    writer = ProviderConfigWriter(config_repository, _FakeCloudModelRepository())
    provider_template = _provider_entry(
        provider_id="deepseek",
        protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE,
    )

    saved = writer.save_config(
        provider_template=provider_template,
        api_base_url=None,
        enabled=True,
        api_keys=(ProviderApiKeyConfigInput("primary", "sk-test", 1),),
    )

    assert saved.api_keys[0].api_key_ciphertext == "encrypted:sk-test"
    assert config_repository.get_config("deepseek").api_keys[0].api_key_ciphertext == "encrypted:sk-test"


def test_provider_config_writer_keeps_model_url_empty_when_not_configured(tmp_path):
    config_repository = _provider_config_repository(tmp_path)
    writer = ProviderConfigWriter(config_repository, _FakeCloudModelRepository())
    provider_template = _provider_entry(
        provider_id="openai",
        protocol_family=ProviderProtocolFamily.OPENAI_RESPONSES,
    )

    saved = writer.save_config(
        provider_template=provider_template,
        api_base_url="http://127.0.0.1:8317/v1/responses",
        model_discovery_url=None,
        enabled=False,
        api_keys=(),
    )

    assert saved.model_discovery_url is None


def test_provider_config_writer_updates_only_the_requested_protocol_url(tmp_path):
    config_repository = _provider_config_repository(tmp_path)
    writer = ProviderConfigWriter(config_repository, _FakeCloudModelRepository())
    provider_template = _provider_entry(
        provider_id="deepseek",
        protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE,
    )

    writer.save_config(
        provider_template=provider_template,
        protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE,
        api_base_url="https://proxy.example/v1/chat/completions",
        enabled=False,
        api_keys=(),
    )
    saved = writer.save_config(
        provider_template=provider_template,
        protocol_family=ProviderProtocolFamily.OPENAI_RESPONSES,
        api_base_url="https://proxy.example/v1/custom-responses",
        enabled=False,
        api_keys=(),
    )

    assert saved.api_base_url == "https://proxy.example/v1/chat/completions"
    assert saved.generation_urls == {
        "anthropic_messages": "https://api.deepseek.com/anthropic/v1/messages",
        "openai_compatible": "https://proxy.example/v1/chat/completions",
        "openai_responses": "https://proxy.example/v1/custom-responses",
    }


def test_provider_config_writer_never_derives_model_url_from_generation_url(
    tmp_path,
):
    config_repository = _provider_config_repository(tmp_path)
    writer = ProviderConfigWriter(config_repository, _FakeCloudModelRepository())
    provider_template = _provider_entry(
        provider_id="openai",
        protocol_family=ProviderProtocolFamily.OPENAI_RESPONSES,
    )

    first = writer.save_config(
        provider_template=provider_template,
        api_base_url="https://first.example/v1/responses",
        model_discovery_url=None,
        enabled=False,
        api_keys=(),
    )
    followed = writer.save_config(
        provider_template=provider_template,
        api_base_url="https://second.example/v1/responses",
        model_discovery_url=first.model_discovery_url,
        enabled=False,
        api_keys=(),
    )
    customized = writer.save_config(
        provider_template=provider_template,
        api_base_url="https://third.example/v1/responses",
        model_discovery_url="https://catalog.example/custom-models",
        enabled=False,
        api_keys=(),
    )
    preserved = writer.save_config(
        provider_template=provider_template,
        api_base_url="https://fourth.example/v1/responses",
        model_discovery_url=customized.model_discovery_url,
        enabled=False,
        api_keys=(),
    )

    assert followed.model_discovery_url is None
    assert preserved.model_discovery_url == "https://catalog.example/custom-models"


def test_secret_codec_uses_windows_dpapi(monkeypatch):
    monkeypatch.setattr(secret_codec_module.os, "name", "nt")
    monkeypatch.setattr(
        secret_codec_module,
        "_windows_dpapi_protect",
        lambda value: b"protected:" + value,
    )
    monkeypatch.setattr(
        secret_codec_module,
        "_windows_dpapi_unprotect",
        lambda value: value.removeprefix(b"protected:"),
    )

    ciphertext = secret_codec_module.encrypt_secret("sk-windows")

    assert ciphertext is not None
    assert ciphertext.startswith("win-dpapi-user-v1:")
    assert "sk-windows" not in ciphertext
    assert secret_codec_module.decrypt_secret(ciphertext) == "sk-windows"


def test_secret_codec_returns_none_when_dpapi_fails(monkeypatch):
    monkeypatch.setattr(secret_codec_module.os, "name", "nt")

    def fail_dpapi(value):
        raise OSError("DPAPI unavailable")

    monkeypatch.setattr(secret_codec_module, "_windows_dpapi_protect", fail_dpapi)

    assert secret_codec_module.encrypt_secret("sk-plain") is None


def test_usage_summary_includes_usage_only_cloud_models():
    service = LlmUsageService(
        _FakeUsageRepository(),
        _FakeProjectRepository(),
        _FakeProviderCatalogRepository(),
        _FakeCustomModelRepository(),
    )

    summary = service.get_provider_model_summary()

    assert isinstance(summary, LlmProviderModelUsageSummary)
    assert len(summary.providers) == 1
    assert summary.providers[0].provider_id == "deepseek"
    assert summary.providers[0].by_models[0].model_id == "deepseek-chat"
    assert summary.providers[0].total_tokens == 30


def test_managed_project_delete_restores_archive_when_database_delete_fails():
    repository = _FailingProjectRepository()
    storage = _RestorableStorage()
    service = ProjectService(repository, storage)

    try:
        service.delete_project(repository.project.project_id)
    except RuntimeError:
        pass

    assert storage.archive_calls == [repository.project.root_path]
    assert storage.restore_calls == [("archived-path", repository.project.root_path)]
    assert repository.deleted_project_ids == [repository.project.project_id]


def test_database_schema_removes_legacy_provider_tables(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)

    with sqlite3.connect(database_path) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "provider_configs" not in table_names
    assert "provider_config_api_keys" not in table_names
    assert "provider_cloud_model_caches" not in table_names
    assert "provider_custom_models" not in table_names
    assert "llm_usage_records" not in table_names
    assert "llm_conversation_session_index" not in table_names


def test_database_schema_migration_adds_usage_feature_key_before_integrity_rebuild(tmp_path):
    database_path = tmp_path / "tiance.db"
    with sqlite3.connect(database_path) as connection:
        _create_schema_migrations(connection, through_version=11)
        connection.executescript(
            """
            CREATE TABLE provider_configs (
                provider_id TEXT PRIMARY KEY,
                api_base_url TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE provider_config_api_keys (
                key_id TEXT PRIMARY KEY,
                provider_id TEXT NOT NULL,
                secret_ref TEXT NOT NULL,
                api_key_hint TEXT,
                poll_weight INTEGER NOT NULL,
                sort_order INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE provider_cloud_model_caches (
                provider_id TEXT NOT NULL,
                protocol_family TEXT NOT NULL,
                api_base_url TEXT NOT NULL,
                discovered_at TEXT NOT NULL,
                PRIMARY KEY (provider_id, protocol_family, api_base_url)
            );
            CREATE TABLE provider_cloud_model_items (
                provider_id TEXT NOT NULL,
                protocol_family TEXT NOT NULL,
                api_base_url TEXT NOT NULL,
                model_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                family_group TEXT NOT NULL,
                capability_tags TEXT NOT NULL,
                sort_order INTEGER NOT NULL,
                PRIMARY KEY (provider_id, protocol_family, api_base_url, model_id)
            );
            CREATE TABLE projects (
                project_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                root_path TEXT NOT NULL,
                is_default INTEGER NOT NULL,
                sort_order INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE llm_conversation_session_index (
                project_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                title TEXT NOT NULL,
                provider_id TEXT,
                model_id TEXT,
                message_count INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                indexed_at TEXT NOT NULL,
                sequence_number INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (project_id, session_id)
            );
            CREATE TABLE llm_usage_records (
                usage_id TEXT PRIMARY KEY,
                project_id TEXT,
                session_id TEXT,
                message_id TEXT,
                provider_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                reasoning_tokens INTEGER NOT NULL DEFAULT 0,
                prompt_cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
                prompt_cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
                cost_amount REAL,
                cost_currency TEXT,
                is_estimated INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )

    run_database_migrations(
        database_path,
        tuple(migration for migration in MIGRATIONS if migration.version <= 17),
    )

    with sqlite3.connect(database_path) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        usage_columns = _table_columns(connection, "llm_usage_records")
        applied_versions = {
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }

    assert "usage_feature_key" in usage_columns
    assert 16 in applied_versions
    assert 17 in applied_versions


def test_database_schema_contract_migration_adds_missing_contract_columns(tmp_path):
    database_path = tmp_path / "tiance.db"
    with sqlite3.connect(database_path) as connection:
        _create_schema_migrations(connection, through_version=15)
        _create_empty_conversation_session_index(connection)
        connection.executescript(
            """
            CREATE TABLE provider_config_api_keys (
                key_id TEXT PRIMARY KEY,
                provider_id TEXT NOT NULL,
                api_key_hint TEXT,
                poll_weight INTEGER NOT NULL,
                sort_order INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE llm_usage_records (
                usage_id TEXT PRIMARY KEY,
                project_id TEXT,
                session_id TEXT,
                message_id TEXT,
                provider_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                reasoning_tokens INTEGER NOT NULL DEFAULT 0,
                prompt_cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
                prompt_cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
                cost_amount REAL,
                cost_currency TEXT,
                is_estimated INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )

    run_database_migrations(
        database_path,
        tuple(migration for migration in MIGRATIONS if migration.version <= 17),
    )

    with sqlite3.connect(database_path) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        usage_columns = _table_columns(connection, "llm_usage_records")
        usage_indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(llm_usage_records)").fetchall()
        }
        applied_versions = {
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }

    assert "usage_feature_key" in usage_columns
    assert "idx_llm_usage_records_session_feature" in usage_indexes
    assert 16 in applied_versions
    assert 17 in applied_versions


def test_database_schema_migration_marks_memory_compression_usage(tmp_path):
    database_path = tmp_path / "tiance.db"
    with sqlite3.connect(database_path) as connection:
        _create_schema_migrations(connection, through_version=16)
        _create_empty_conversation_session_index(connection)
        connection.executescript(
            """
            CREATE TABLE llm_usage_records (
                usage_id TEXT PRIMARY KEY,
                project_id TEXT,
                session_id TEXT,
                message_id TEXT,
                provider_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                usage_feature_key TEXT NOT NULL DEFAULT 'main_chat',
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                reasoning_tokens INTEGER NOT NULL DEFAULT 0,
                prompt_cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
                prompt_cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
                cost_amount REAL,
                cost_currency TEXT,
                is_estimated INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            INSERT INTO llm_usage_records (
                usage_id,
                message_id,
                provider_id,
                model_id,
                usage_feature_key,
                created_at
            ) VALUES (
                'usage_1',
                'system:memory_compression:cmp_1',
                'deepseek',
                'deepseek-v4',
                'main_chat',
                'now'
            );
            """
        )

    run_database_migrations(
        database_path,
        tuple(migration for migration in MIGRATIONS if migration.version <= 17),
    )

    with sqlite3.connect(database_path) as connection:
        usage_feature_key = connection.execute(
            "SELECT usage_feature_key FROM llm_usage_records WHERE usage_id = ?",
            ("usage_1",),
        ).fetchone()[0]

    assert usage_feature_key == "memory_compression"


def _create_schema_migrations(
    connection: sqlite3.Connection,
    *,
    through_version: int,
) -> None:
    connection.execute(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    connection.executemany(
        """
        INSERT INTO schema_migrations (version, name, applied_at)
        VALUES (?, ?, ?)
        """,
        [
            (version, f"migration_{version}", "2026-01-01T00:00:00+00:00")
            for version in range(1, through_version + 1)
        ],
    )


def _create_empty_conversation_session_index(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE llm_conversation_session_index (
            project_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            title TEXT NOT NULL,
            provider_id TEXT,
            model_id TEXT,
            message_count INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            indexed_at TEXT NOT NULL,
            sequence_number INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (project_id, session_id)
        )
        """
    )


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def _provider_config_repository(tmp_path) -> ProviderConfigRepository:
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")
    return ProviderConfigRepository(ProviderFileStore(providers_path))


def _provider_entry(
    *,
    provider_id: str,
    protocol_family: ProviderProtocolFamily,
    auth_scheme: AuthScheme = AuthScheme.BEARER_TOKEN,
    model_discovery_strategy: ModelDiscoveryStrategy | None = None,
) -> ProviderCatalogEntry:
    return ProviderCatalogEntry(
        provider_id=provider_id,
        display_name=provider_id,
        profile_id=provider_id,
        protocol_family=protocol_family,
        generation_auth_schemes={protocol_family: auth_scheme},
        model_discovery_strategy=(
            model_discovery_strategy
            or default_model_discovery_strategy(protocol_family)
        ),
        model_discovery_auth_scheme=AuthScheme.BEARER_TOKEN,
        endpoints=ProviderEndpointTemplate(
            api_base_url="https://example.test/v1/chat/completions",
            text_generation_url_template="https://example.test/v1/chat/completions",
            model_discovery_url=None,
        ),
    )


def _chat_request():
    from app.domain.llm.chat import ChatCompletionRequest, ChatMessage, ChatMessageRole

    return ChatCompletionRequest(
        provider_id="deepseek",
        model_id="deepseek-chat",
        messages=(ChatMessage(role=ChatMessageRole.USER, content="hi"),),
    )


def _cloud_cache(api_base_url: str, model_id: str) -> ProviderCloudModelCache:
    return ProviderCloudModelCache(
        provider_id="openai-compatible",
        protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE.value,
        api_base_url=api_base_url,
        discovered_at="now",
        models=(
            DiscoveredModel(
                model_id=model_id,
                display_name=model_id,
                provider_id="openai-compatible",
            ),
        ),
    )


def _provider_config(
    *,
    api_key_ciphertext: str | None = None,
) -> ProviderConfig:
    return ProviderConfig(
        provider_id="deepseek",
        api_base_url="https://example.test",
        protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE.value,
        generation_urls={
            ProviderProtocolFamily.OPENAI_COMPATIBLE.value: "https://example.test"
        },
        enabled=True,
        api_keys=(
            ProviderApiKeyConfig(
                key_id="key-1",
                provider_id="deepseek",
                api_key_hint="***",
                api_key_ciphertext=api_key_ciphertext,
                poll_weight=1,
                sort_order=0,
                created_at="now",
                updated_at="now",
            ),
        ),
        created_at="now",
        updated_at="now",
    )


def _provider_config_without_api_keys() -> ProviderConfig:
    return ProviderConfig(
        provider_id="deepseek",
        api_base_url="https://example.test",
        protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE.value,
        generation_urls={
            ProviderProtocolFamily.OPENAI_COMPATIBLE.value: "https://example.test"
        },
        enabled=True,
        api_keys=(),
        created_at="now",
        updated_at="now",
    )


class _FakeCloudModelRepository:
    def delete_provider_cache(self, _provider_id: str) -> None:
        return None


class _FakeApiKeyScheduler:
    def select_next(self, _provider_id: str, candidates):
        candidates = tuple(candidates)
        return candidates[0] if candidates else None


class _FakeStreamingHttpClient:
    def __init__(self, response) -> None:
        self._response = response

    def stream(self, *_args, **_kwargs):
        return _FakeStreamContext(self._response)


class _FakeStreamContext:
    def __init__(self, response) -> None:
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *_args):
        return False


class _UnreadErrorStreamResponse:
    is_error = True

    def __init__(self) -> None:
        self.was_read = False
        self._request = httpx.Request("POST", "https://example.test/chat/completions")
        self._response = httpx.Response(
            400,
            request=self._request,
            content=b'{"error":{"message":"bad request"}}',
        )

    async def aread(self):
        self.was_read = True
        return self._response.content

    def raise_for_status(self):
        raise httpx.HTTPStatusError(
            "Client error '400 Bad Request'",
            request=self._request,
            response=self._response,
        )

    async def aiter_bytes(self):
        yield b""


class _FakeUsageRepository:
    def get_model_summaries(self, *, provider_id=None):
        return (
            LlmUsageSummary(
                provider_id="deepseek",
                provider_display_name=None,
                model_id="deepseek-chat",
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
                reasoning_tokens=0,
                prompt_cache_hit_tokens=0,
                prompt_cache_miss_tokens=0,
                cost_amount=None,
                cost_currency=None,
                record_count=1,
            ),
        )


class _FakeProjectRepository:
    def get_project(self, project_id: str):
        return object()


class _FakeProviderCatalogRepository:
    def list_entries(self):
        return (
            _provider_entry(
                provider_id="deepseek",
                protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE,
            ),
        )


class _FakeCustomModelRepository:
    def list_all_models(self):
        return ()

    def get_model(self, provider_id: str, model_id: str):
        return None


class _FailingProjectRepository:
    def __init__(self) -> None:
        self.project = Project(
            project_id="00000000-0000-0000-0000-000000000001",
            name="test",
            root_path="managed-root",
            is_default=False,
            sort_order=0,
            created_at="now",
            updated_at="now",
        )
        self.deleted_project_ids = []

    def get_project(self, project_id: str):
        return self.project if project_id == self.project.project_id else None

    def delete_project(self, project_id: str) -> None:
        self.deleted_project_ids.append(project_id)
        raise RuntimeError("database failed")


class _RestorableStorage:
    def __init__(self) -> None:
        self.archive_calls = []
        self.restore_calls = []

    def is_managed_project_root(self, root_path: str) -> bool:
        return True

    def archive_project_root(self, root_path: str):
        self.archive_calls.append(root_path)
        return "archived-path"

    def restore_archived_project_root(self, archived_path, project_root: str) -> None:
        self.restore_calls.append((archived_path, project_root))
