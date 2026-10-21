import json
from pathlib import Path

import pytest

from app.services.locales.locale_catalog import ensure_locale_catalog, get_active_locale
from app.services.themes.theme_catalog import load_theme_package, ThemeCatalogError


@pytest.mark.parametrize("locale", ["zh-CN", "en-US", "ru-RU"])
def test_bom_locale_keeps_custom_text_and_is_not_backed_up_as_invalid(tmp_path, locale):
    ensure_locale_catalog(tmp_path)
    path = tmp_path / f"{locale}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["messages"]["common"]["actions"]["save"] = "Custom Save"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")
    before = path.read_bytes()
    ensure_locale_catalog(tmp_path)
    assert get_active_locale(locale, tmp_path)["messages"]["common"]["actions"]["save"] == "Custom Save"
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.invalid-*.json"))


@pytest.mark.parametrize("name", ["light", "dark-gold"])
def test_bom_theme_has_same_contract_as_plain_utf8(tmp_path, name):
    content = (Path(__file__).parents[1] / "app/resources/themes" / f"{name}.json").read_text(encoding="utf-8")
    path = tmp_path / "theme.json"
    path.write_text(content, encoding="utf-8")
    plain = load_theme_package(tmp_path)
    path.write_text(content, encoding="utf-8-sig")
    assert load_theme_package(tmp_path) == plain


def test_bom_does_not_hide_invalid_theme_json(tmp_path):
    (tmp_path / "theme.json").write_text('{"broken":', encoding="utf-8-sig")
    with pytest.raises(ThemeCatalogError, match="Invalid theme JSON"):
        load_theme_package(tmp_path)
