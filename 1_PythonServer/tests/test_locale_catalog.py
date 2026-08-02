import json

from app.services.locales import (
    LocaleCatalogError,
    ensure_locale_catalog,
    get_active_locale,
    get_locale_settings,
    list_locales,
    normalize_locale_tag,
    update_locale_settings,
)


def _collect_message_paths(node, prefix=""):
    if isinstance(node, str):
        return {prefix}

    paths = set()
    for key, value in node.items():
        next_prefix = f"{prefix}.{key}" if prefix else key
        paths.update(_collect_message_paths(value, next_prefix))
    return paths


def test_ensure_locale_catalog_restores_bundled_locales(tmp_path):
    ensure_locale_catalog(tmp_path)

    assert (tmp_path / "zh-CN.json").is_file()
    assert (tmp_path / "en-US.json").is_file()
    assert (tmp_path / "ru-RU.json").is_file()
    assert (tmp_path / "locale-settings.json").is_file()

    active_locale = get_active_locale("ru-RU", tmp_path)
    assert active_locale["locale"] == "ru-RU"
    assert active_locale["messages"]["common"]["actions"]["save"] == "Сохранить"


def test_ensure_locale_catalog_backs_up_and_restores_invalid_base_locale(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "zh-CN.json").write_text("{not valid json", encoding="utf-8")

    ensure_locale_catalog(tmp_path)

    restored = json.loads((tmp_path / "zh-CN.json").read_text(encoding="utf-8"))
    assert restored["locale"] == "zh-CN"
    assert restored["messages"]["common"]["actions"]["save"] == "保存"
    assert list(tmp_path.glob("zh-CN.invalid-*.json"))


def test_ensure_locale_catalog_repairs_missing_message_keys_without_overwriting_user_text(tmp_path):
    ensure_locale_catalog(tmp_path)
    locale_file = tmp_path / "en-US.json"
    payload = json.loads(locale_file.read_text(encoding="utf-8"))
    payload["messages"]["common"]["productName"] = "Custom Tiance"
    del payload["messages"]["common"]["actions"]["save"]
    locale_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    ensure_locale_catalog(tmp_path)

    repaired = json.loads(locale_file.read_text(encoding="utf-8"))
    assert repaired["messages"]["common"]["productName"] == "Custom Tiance"
    assert repaired["messages"]["common"]["actions"]["save"] == "Save"


def test_chinese_locale_variants_are_normalized_to_simplified_chinese(tmp_path):
    ensure_locale_catalog(tmp_path)

    assert normalize_locale_tag("zh-TW") == "zh-CN"
    assert normalize_locale_tag("zh-HK") == "zh-CN"
    assert normalize_locale_tag("zh-MO") == "zh-CN"
    assert get_active_locale("zh-Hant-TW", tmp_path)["locale"] == "zh-CN"


def test_locale_list_uses_complete_valid_locale_files(tmp_path):
    ensure_locale_catalog(tmp_path)
    active_locale, locales = list_locales("ru-RU", tmp_path)

    assert active_locale == "ru-RU"
    assert {item["locale"] for item in locales} == {"zh-CN", "en-US", "ru-RU"}


def test_custom_locale_file_can_be_selected_when_shape_matches_base_locale(tmp_path):
    ensure_locale_catalog(tmp_path)
    base_payload = json.loads((tmp_path / "zh-CN.json").read_text(encoding="utf-8"))
    custom_payload = {
        **base_payload,
        "locale": "fr-FR",
        "displayName": "Français",
    }
    custom_payload["messages"]["common"]["actions"]["save"] = "Enregistrer"
    (tmp_path / "fr-FR.json").write_text(
        json.dumps(custom_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    active_locale = get_active_locale("fr-FR", tmp_path)

    assert active_locale["locale"] == "fr-FR"
    assert active_locale["messages"]["common"]["actions"]["save"] == "Enregistrer"


def test_locale_message_keys_match_base_locale_without_sampling(tmp_path):
    ensure_locale_catalog(tmp_path)
    locale_payloads = {
        locale: json.loads((tmp_path / f"{locale}.json").read_text(encoding="utf-8"))
        for locale in ("zh-CN", "en-US", "ru-RU")
    }
    reference_paths = _collect_message_paths(locale_payloads["zh-CN"]["messages"])

    assert len(reference_paths) > 400
    for locale, payload in locale_payloads.items():
        assert _collect_message_paths(payload["messages"]) == reference_paths, locale


def test_locale_settings_switch_between_manual_and_system_modes(tmp_path):
    ensure_locale_catalog(tmp_path)

    manual = update_locale_settings("manual", "ru-RU", tmp_path)
    assert manual["mode"] == "manual"
    assert manual["activeLocale"] == "ru-RU"
    assert get_active_locale("zh-CN", tmp_path)["locale"] == "ru-RU"

    system = update_locale_settings("system", "ru-RU", tmp_path)
    assert system["mode"] == "system"
    assert get_active_locale("zh-CN", tmp_path)["locale"] == "zh-CN"
    assert get_locale_settings(tmp_path)["activeLocale"] == "ru-RU"


def test_locale_settings_reject_missing_locale_without_overwriting_file(tmp_path):
    ensure_locale_catalog(tmp_path)
    original = get_locale_settings(tmp_path)

    try:
        update_locale_settings("manual", "fr-FR", tmp_path)
    except LocaleCatalogError as exc:
        assert "fr-FR" in str(exc)
    else:
        raise AssertionError("Missing locale must be rejected")

    assert get_locale_settings(tmp_path) == original
