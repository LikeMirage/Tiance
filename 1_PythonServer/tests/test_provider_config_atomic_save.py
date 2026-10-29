from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.domain.llm.provider_config import ProviderApiKeyConfig
from app.repositories.llm import provider_file_store as storage_module
from app.repositories.llm.provider_catalog_repository import ProviderCatalogRepository
from app.repositories.llm.provider_config_repository import ProviderConfigRepository
from app.repositories.llm.provider_file_store import ProviderFileStore, ProviderFileStoreError
from app.services.llm.provider.config_writer import ProviderApiKeyConfigInput, ProviderConfigWriter
from app.services.llm.provider.storage_bootstrap import ensure_provider_file_storage


@pytest.fixture
def config_store(tmp_path):
    root = tmp_path / "providers"
    ensure_provider_file_storage(root)
    store = ProviderFileStore(root)
    repository = ProviderConfigRepository(store)
    config = repository.get_config("deepseek")
    key = ProviderApiKeyConfig("key-1", "deepseek", "old-hint", 1, 0, "t0", "t0", "fake-old-ciphertext")
    repository.save_config(replace(config, api_keys=(key,), enabled=True, updated_at="t0"))
    return store, repository, repository.get_config("deepseek")


def _snapshot(store):
    return {
        name: (store.provider_file("deepseek", name).read_bytes(), store.provider_file("deepseek", name).stat().st_mtime_ns)
        for name in ("provider.json", "credentials.json")
    }


@pytest.mark.parametrize("change,expected", [
    ("nothing", set()), ("key", {"credentials.json"}),
    ("weight", {"credentials.json"}), ("address", {"provider.json"}),
    ("enabled", {"provider.json"}), ("linked", {"credentials.json", "provider.json"}),
])
def test_save_writes_only_files_with_real_changes(config_store, monkeypatch, change, expected):
    store, repository, original = config_store
    before = _snapshot(store)
    key = replace(original.api_keys[0], updated_at="t1")
    updates = {"updated_at": "t1", "api_keys": (key,)}
    if change in {"key", "linked"}:
        updates["api_keys"] = (replace(key, api_key_ciphertext="fake-new-ciphertext"),)
    if change == "weight":
        updates["api_keys"] = (replace(key, poll_weight=3),)
    if change == "address":
        updates["api_base_url"] = "https://new.example/v1/chat/completions"
    if change in {"enabled", "linked"}:
        updates["enabled"] = False
    published = []
    real_replace = storage_module.atomic_replace_path

    def track(source, destination):
        published.append(destination.name)
        return real_replace(source, destination)

    monkeypatch.setattr(storage_module, "atomic_replace_path", track)
    repository.save_config(replace(original, **updates))
    assert set(published) == expected
    after = _snapshot(store)
    for name in before.keys() - expected:
        assert after[name] == before[name]  # Includes timestamps and byte-for-byte content.
    saved = repository.get_config("deepseek")
    assert saved.updated_at == ("t1" if "provider.json" in expected else original.updated_at)
    assert saved.api_keys[0].updated_at == ("t1" if "credentials.json" in expected else original.api_keys[0].updated_at)


@pytest.mark.parametrize("failure", ["prepare", "first_publish", "second_publish"])
def test_save_failure_keeps_both_original_files(config_store, monkeypatch, failure):
    store, repository, original = config_store
    before = _snapshot(store)
    new = replace(original, enabled=False, updated_at="t1", api_keys=(replace(original.api_keys[0], api_key_ciphertext="fake-new", updated_at="t1"),))
    real_replace = storage_module.atomic_replace_path
    real_write = storage_module._write_durable_bytes

    def write(path, content):
        if failure == "prepare" and path.name == "provider.json":
            raise OSError("disk full")
        return real_write(path, content)

    def publish(source, target):
        if (failure == "first_publish" and source.name == "credentials.json") or (failure == "second_publish" and source.name == "provider.json"):
            raise PermissionError("simulated file lock")
        return real_replace(source, target)

    monkeypatch.setattr(storage_module, "_write_durable_bytes", write)
    monkeypatch.setattr(storage_module, "atomic_replace_path", publish)
    with pytest.raises(ProviderFileStoreError, match="原有配置已保留"):
        repository.save_config(new)
    assert {name: value[0] for name, value in _snapshot(store).items()} == {name: value[0] for name, value in before.items()}
    assert repository.get_config("deepseek") == original
    assert not list(store.provider_dir("deepseek").glob(".config-save-*"))


def test_linked_first_key_enable_and_last_key_disable(config_store):
    store, repository, original = config_store
    repository.save_config(replace(original, api_keys=(), enabled=False))
    empty = repository.get_config("deepseek")
    repository.save_config(replace(empty, api_keys=original.api_keys, enabled=True, updated_at="t1"))
    enabled = repository.get_config("deepseek")
    assert enabled.enabled and len(enabled.api_keys) == 1
    repository.save_config(replace(enabled, api_keys=(), enabled=False, updated_at="t2"))
    disabled = repository.get_config("deepseek")
    assert not disabled.enabled and not disabled.api_keys


def test_bad_manifest_validation_cannot_write_credentials_first(config_store):
    store, repository, original = config_store
    before = _snapshot(store)
    with pytest.raises(ValueError):
        repository.save_config(replace(original, protocol_family="invalid", api_keys=()))
    assert _snapshot(store) == before


def test_rollback_failure_preserves_backup(config_store, monkeypatch):
    store, repository, original = config_store
    previous_credentials = store.provider_file("deepseek", "credentials.json").read_bytes()
    real_replace = storage_module.atomic_replace_path

    def fail(source, target):
        if source.name == "provider.json" or source.name.endswith(".previous"):
            raise PermissionError("locked")
        return real_replace(source, target)

    monkeypatch.setattr(storage_module, "atomic_replace_path", fail)
    with pytest.raises(ProviderFileStoreError, match="恢复文件保留在"):
        repository.save_config(replace(original, enabled=False, api_keys=()))
    backup, = store.provider_dir("deepseek").glob(".config-save-*/credentials.json.previous")
    assert backup.read_bytes() == previous_credentials


def test_reentering_same_plaintext_key_does_not_reencrypt_or_rewrite(config_store, monkeypatch):
    from app.services.llm.provider import config_writer

    store, repository, original = config_store
    writer = ProviderConfigWriter(repository, Mock())
    template = ProviderCatalogRepository(store).get_entry("deepseek")
    monkeypatch.setattr(config_writer, "decrypt_secret", lambda value: "same-key")
    encrypt = Mock(side_effect=AssertionError("unchanged key must not be reencrypted"))
    monkeypatch.setattr(config_writer, "encrypt_secret", encrypt)
    before = _snapshot(store)
    saved = writer.save_config(
        provider_template=template, api_base_url=original.api_base_url,
        enabled=original.enabled, api_keys=(ProviderApiKeyConfigInput("key-1", "same-key", 1),),
        model_discovery_url=original.model_discovery_url,
    )
    assert saved.api_keys[0] == original.api_keys[0]
    assert _snapshot(store) == before
    encrypt.assert_not_called()
