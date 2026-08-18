import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from PIL import Image

from app.core.errors import BadRequestError
from app.infra.theme_market import ThemePackageArchive
from app.infra.theme_market.remote_client import (
    normalize_market_source,
    resolve_market_asset_url,
)
from app.repositories.themes import ThemeMarketSettingsRepository
from app.schemas.themes.theme_market import (
    ThemeMarketFilterSettings,
    ThemeMarketThemeEntry,
)


RECOVERY_ROOT = Path(__file__).resolve().parents[1] / "app" / "resources" / "themes"


def test_market_settings_are_created_and_persist_filters(tmp_path) -> None:
    settings_path = tmp_path / "themes" / "market-settings.json"
    repository = ThemeMarketSettingsRepository(settings_path)

    initial = repository.ensure_settings_file()
    saved = repository.save_filters(ThemeMarketFilterSettings(
        authors=["LikeMirage", "LikeMirage"],
        baseColors=["gold"],
        modes=["dark"],
        statuses=["not-installed"],
    ))

    assert settings_path.is_file()
    assert initial.source == "https://likemirage.github.io/Tiance-themes"
    assert saved.filters.base_colors == ["gold"]
    assert json.loads(settings_path.read_text(encoding="utf-8"))["filters"] == {
        "modes": ["dark"],
        "authors": ["LikeMirage", "LikeMirage"],
        "baseColors": ["gold"],
        "statuses": ["not-installed"],
    }


def test_invalid_market_settings_are_repaired(tmp_path) -> None:
    settings_path = tmp_path / "themes" / "market-settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text("not-json", encoding="utf-8")

    settings = ThemeMarketSettingsRepository(settings_path).ensure_settings_file()

    assert settings.source == "https://likemirage.github.io/Tiance-themes"
    assert json.loads(settings_path.read_text(encoding="utf-8"))["schemaVersion"] == 1


def test_market_urls_allow_relative_assets_but_reject_other_origins() -> None:
    source = normalize_market_source(
        "https://example.com/user/themes/index.json"
    )

    assert source == "https://example.com/user/themes"
    assert resolve_market_asset_url(source, "packages/theme-1.0.0.zip") == (
        "https://example.com/user/themes/packages/theme-1.0.0.zip"
    )
    with pytest.raises(BadRequestError):
        resolve_market_asset_url(source, "https://other.example/theme.zip")
    with pytest.raises(BadRequestError):
        resolve_market_asset_url(source, "../../theme.zip")


def test_theme_package_archive_validates_and_extracts_market_metadata(tmp_path) -> None:
    package_root = tmp_path / "source" / "sample-theme"
    package_root.mkdir(parents=True)
    theme = json.loads((RECOVERY_ROOT / "light.json").read_text(encoding="utf-8"))
    theme.update({"id": "sample-theme", "registrationName": "示例主题"})
    (package_root / "theme.json").write_text(
        json.dumps(theme, ensure_ascii=False),
        encoding="utf-8",
    )
    manifest = _manifest()
    (package_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    Image.new("RGB", (2, 2), "white").save(package_root / "preview.png")
    archive_path = tmp_path / "sample.zip"
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        for path in package_root.iterdir():
            archive.write(path, f"sample-theme/{path.name}")

    extracted = ThemePackageArchive().validate_and_extract(
        archive_path=archive_path,
        staging_root=tmp_path / "staging",
        market_entry=_entry(),
    )

    assert json.loads((extracted / "manifest.json").read_text(encoding="utf-8"))[
        "baseColors"
    ] == ["white", "blue"]


def test_theme_package_archive_rejects_path_traversal(tmp_path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("sample-theme/../../outside.txt", "unsafe")

    with pytest.raises(BadRequestError, match="越界路径"):
        ThemePackageArchive().validate_and_extract(
            archive_path=archive_path,
            staging_root=tmp_path / "staging",
            market_entry=_entry(),
        )


def _manifest() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "version": "1.0.0",
        "author": {"name": "LikeMirage"},
        "summary": "示例主题。",
        "license": "CC0-1.0",
        "baseColors": ["white", "blue"],
        "preview": "preview.png",
        "compatibility": {
            "themeSchemaVersion": 2,
            "minTianceVersion": "0.1.0",
        },
    }


def _entry() -> ThemeMarketThemeEntry:
    return ThemeMarketThemeEntry(
        id="sample-theme",
        name="示例主题",
        mode="light",
        version="1.0.0",
        author="LikeMirage",
        summary="示例主题。",
        license="CC0-1.0",
        baseColors=["white", "blue"],
        previewUrl="previews/sample-theme.png",
        packageUrl="packages/sample-theme-1.0.0.zip",
        sha256="0" * 64,
        size=1,
        compatibility={
            "themeSchemaVersion": 2,
            "minTianceVersion": "0.1.0",
        },
    )
