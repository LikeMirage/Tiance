from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.core.config import get_settings


LOCALE_SCHEMA_VERSION = 1
LOCALE_SETTINGS_FILE = "locale-settings.json"
LOCALE_SETTINGS_SCHEMA_VERSION = 1
DEFAULT_LOCALE = "en-US"
CHINESE_LOCALE = "zh-CN"
_LOCALE_ID_PATTERN = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


class LocaleCatalogError(RuntimeError):
    pass


class LocaleNotFoundError(LocaleCatalogError):
    pass


def ensure_locale_catalog(locales_dir: Path | None = None) -> None:
    target_dir = _resolve_locales_dir(locales_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    bundled_locales = _load_bundled_locale_packages()
    reference_messages = _reference_messages(bundled_locales)
    for locale_id, bundled_locale in sorted(bundled_locales.items()):
        _ensure_locale_file(target_dir, locale_id, bundled_locale, reference_messages)

    _ensure_locale_settings(target_dir)


def list_locales(
    preferred_locale: str | None = None,
    locales_dir: Path | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    target_dir = _resolve_locales_dir(locales_dir)
    ensure_locale_catalog(target_dir)
    bundled_locales = _load_bundled_locale_packages()
    reference_messages = _reference_messages(bundled_locales)
    active_locale = resolve_active_locale(preferred_locale, target_dir)

    summaries: list[dict[str, Any]] = []
    for locale_file in sorted(target_dir.glob("*.json"), key=lambda item: item.name.lower()):
        if locale_file.name == LOCALE_SETTINGS_FILE:
            continue
        if not _LOCALE_ID_PATTERN.fullmatch(locale_file.stem):
            continue
        try:
            locale = _load_locale_file(locale_file, reference_messages, expected_locale=locale_file.stem)
        except LocaleCatalogError:
            continue
        summaries.append({
            "locale": locale["locale"],
            "displayName": locale["displayName"],
            "direction": locale["direction"],
        })

    return active_locale, summaries


def get_active_locale(
    preferred_locale: str | None = None,
    locales_dir: Path | None = None,
) -> dict[str, Any]:
    target_dir = _resolve_locales_dir(locales_dir)
    ensure_locale_catalog(target_dir)
    bundled_locales = _load_bundled_locale_packages()
    reference_messages = _reference_messages(bundled_locales)
    active_locale = resolve_active_locale(preferred_locale, target_dir)

    try:
        return _load_locale_file(
            _locale_file_path(target_dir, active_locale),
            reference_messages,
            expected_locale=active_locale,
        )
    except LocaleCatalogError:
        if active_locale == DEFAULT_LOCALE:
            raise
        return _load_locale_file(
            _locale_file_path(target_dir, DEFAULT_LOCALE),
            reference_messages,
            expected_locale=DEFAULT_LOCALE,
        )


def get_locale_settings(locales_dir: Path | None = None) -> dict[str, Any]:
    target_dir = _resolve_locales_dir(locales_dir)
    ensure_locale_catalog(target_dir)
    return _read_locale_settings(target_dir)


def update_locale_settings(
    mode: str,
    active_locale: str,
    locales_dir: Path | None = None,
) -> dict[str, Any]:
    target_dir = _resolve_locales_dir(locales_dir)
    ensure_locale_catalog(target_dir)

    if mode not in {"system", "manual"}:
        raise LocaleCatalogError(f"Invalid locale selection mode: {mode}")

    locale_id = normalize_locale_tag(active_locale)
    bundled_locales = _load_bundled_locale_packages()
    _load_locale_file(
        _locale_file_path(target_dir, locale_id),
        _reference_messages(bundled_locales),
        expected_locale=locale_id,
    )

    settings = {
        "schemaVersion": LOCALE_SETTINGS_SCHEMA_VERSION,
        "mode": mode,
        "activeLocale": locale_id,
        "updatedAt": datetime.now(UTC).isoformat(),
    }
    _write_json_file(target_dir / LOCALE_SETTINGS_FILE, settings)
    return settings


def resolve_active_locale(preferred_locale: str | None, locales_dir: Path | None = None) -> str:
    target_dir = _resolve_locales_dir(locales_dir)
    settings = _read_locale_settings(target_dir)
    if settings.get("mode") == "manual":
        candidate = normalize_locale_tag(str(settings.get("activeLocale") or ""))
    else:
        candidate = normalize_locale_tag(preferred_locale or "")

    if _locale_file_path(target_dir, candidate).is_file():
        return candidate
    return DEFAULT_LOCALE


def normalize_locale_tag(locale: str) -> str:
    normalized = locale.strip().replace("_", "-").lower()
    if not normalized:
        return DEFAULT_LOCALE

    if normalized == "zh" or normalized.startswith("zh-"):
        return CHINESE_LOCALE
    if normalized == "ru" or normalized.startswith("ru-"):
        return "ru-RU"
    if normalized == "en" or normalized.startswith("en-"):
        return DEFAULT_LOCALE

    canonical = _canonical_locale_id(normalized)
    return canonical if _LOCALE_ID_PATTERN.fullmatch(canonical) else DEFAULT_LOCALE


def _ensure_locale_file(
    target_dir: Path,
    locale_id: str,
    bundled_locale: dict[str, Any],
    reference_messages: dict[str, Any],
) -> None:
    target_file = _locale_file_path(target_dir, locale_id)
    if not target_file.exists():
        _write_json_file(target_file, bundled_locale)
        return

    try:
        current = _read_json_file(target_file)
    except LocaleCatalogError:
        _backup_invalid_file(target_file)
        _write_json_file(target_file, bundled_locale)
        return

    repaired, changed, should_backup = _repair_locale_package(
        current,
        bundled_locale,
        reference_messages,
        locale_id,
    )
    if not changed:
        return

    if should_backup:
        _backup_invalid_file(target_file)
    _write_json_file(target_file, repaired)


def _repair_locale_package(
    payload: Any,
    bundled_locale: dict[str, Any],
    reference_messages: dict[str, Any],
    expected_locale: str,
) -> tuple[dict[str, Any], bool, bool]:
    if not isinstance(payload, dict):
        return deepcopy(bundled_locale), True, True

    schema_version = payload.get("schemaVersion")
    locale_id = str(payload.get("locale") or "").strip()
    display_name = payload.get("displayName")
    direction = payload.get("direction")
    messages = payload.get("messages")

    metadata_invalid = (
        schema_version != LOCALE_SCHEMA_VERSION
        or locale_id != expected_locale
        or not isinstance(display_name, str)
        or not display_name.strip()
        or direction not in {"ltr", "rtl"}
    )
    if metadata_invalid or not isinstance(messages, dict):
        return deepcopy(bundled_locale), True, True

    merged_messages, messages_changed = _merge_missing_messages(
        messages,
        bundled_locale["messages"],
        reference_messages,
    )
    if not messages_changed:
        return payload, False, False

    repaired = deepcopy(payload)
    repaired["messages"] = merged_messages
    return repaired, True, False


def _merge_missing_messages(
    current: dict[str, Any],
    bundled: dict[str, Any],
    reference: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    changed = False
    merged = deepcopy(current)

    for key, reference_value in reference.items():
        bundled_value = bundled[key]
        current_value = current.get(key)
        if isinstance(reference_value, str):
            if not isinstance(current_value, str):
                merged[key] = bundled_value
                changed = True
            continue

        if not isinstance(reference_value, dict):
            raise LocaleCatalogError(f"Invalid built-in locale reference at key: {key}")

        if not isinstance(current_value, dict):
            merged[key] = deepcopy(bundled_value)
            changed = True
            continue

        nested, nested_changed = _merge_missing_messages(
            current_value,
            bundled_value,
            reference_value,
        )
        if nested_changed:
            merged[key] = nested
            changed = True

    return merged, changed


def _ensure_locale_settings(target_dir: Path) -> None:
    settings_file = target_dir / LOCALE_SETTINGS_FILE
    if not settings_file.exists():
        _write_json_file(settings_file, _default_locale_settings())
        return

    try:
        payload = _read_json_file(settings_file)
    except LocaleCatalogError:
        _backup_invalid_file(settings_file)
        _write_json_file(settings_file, _default_locale_settings())
        return

    if _is_valid_locale_settings(payload):
        return

    _backup_invalid_file(settings_file)
    _write_json_file(settings_file, _default_locale_settings())


def _read_locale_settings(target_dir: Path) -> dict[str, Any]:
    settings_file = target_dir / LOCALE_SETTINGS_FILE
    try:
        payload = _read_json_file(settings_file)
    except LocaleCatalogError:
        return _default_locale_settings()
    return payload if _is_valid_locale_settings(payload) else _default_locale_settings()


def _is_valid_locale_settings(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("schemaVersion") != LOCALE_SETTINGS_SCHEMA_VERSION:
        return False
    if payload.get("mode") not in {"system", "manual"}:
        return False
    active_locale = str(payload.get("activeLocale") or "").strip()
    return bool(active_locale) and _LOCALE_ID_PATTERN.fullmatch(active_locale) is not None


def _default_locale_settings() -> dict[str, Any]:
    return {
        "schemaVersion": LOCALE_SETTINGS_SCHEMA_VERSION,
        "mode": "system",
        "activeLocale": CHINESE_LOCALE,
        "updatedAt": datetime.now(UTC).isoformat(),
    }


def _load_locale_file(
    locale_file: Path,
    reference_messages: dict[str, Any],
    expected_locale: str | None = None,
) -> dict[str, Any]:
    payload = _read_json_file(locale_file)
    return _validate_locale_package(payload, reference_messages, expected_locale)


def _validate_locale_package(
    payload: Any,
    reference_messages: dict[str, Any],
    expected_locale: str | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LocaleCatalogError("Locale file root must be an object")
    if payload.get("schemaVersion") != LOCALE_SCHEMA_VERSION:
        raise LocaleCatalogError("Invalid locale schema version")

    locale_id = str(payload.get("locale") or "").strip()
    if expected_locale is not None and locale_id != expected_locale:
        raise LocaleCatalogError("Locale id does not match file name")
    if not _LOCALE_ID_PATTERN.fullmatch(locale_id):
        raise LocaleCatalogError("Invalid locale id")

    display_name = payload.get("displayName")
    if not isinstance(display_name, str) or not display_name.strip():
        raise LocaleCatalogError("Locale displayName must be a non-empty string")

    if payload.get("direction") not in {"ltr", "rtl"}:
        raise LocaleCatalogError("Locale direction must be ltr or rtl")

    messages = payload.get("messages")
    if not isinstance(messages, dict):
        raise LocaleCatalogError("Locale messages must be an object")

    _validate_message_shape(messages, reference_messages)
    return payload


def _validate_message_shape(messages: dict[str, Any], reference: dict[str, Any]) -> None:
    for key, reference_value in reference.items():
        if key not in messages:
            raise LocaleCatalogError(f"Missing locale message key: {key}")
        message_value = messages[key]
        if isinstance(reference_value, str):
            if not isinstance(message_value, str):
                raise LocaleCatalogError(f"Locale message must be a string: {key}")
            continue
        if not isinstance(reference_value, dict):
            raise LocaleCatalogError(f"Invalid built-in locale reference at key: {key}")
        if not isinstance(message_value, dict):
            raise LocaleCatalogError(f"Locale message group must be an object: {key}")
        _validate_message_shape(message_value, reference_value)


def _load_bundled_locale_packages() -> dict[str, dict[str, Any]]:
    bundled_dir = _bundled_locale_dir()
    packages: dict[str, dict[str, Any]] = {}
    for locale_file in sorted(bundled_dir.glob("*.json"), key=lambda item: item.name.lower()):
        if not _LOCALE_ID_PATTERN.fullmatch(locale_file.stem):
            continue
        payload = _read_json_file(locale_file)
        if not isinstance(payload, dict):
            raise LocaleCatalogError(f"Invalid bundled locale: {locale_file.name}")
        packages[locale_file.stem] = payload

    for required_locale in {CHINESE_LOCALE, DEFAULT_LOCALE}:
        if required_locale not in packages:
            raise LocaleCatalogError(f"Missing bundled locale: {required_locale}")

    reference_messages = _reference_messages(packages)
    for locale_id, payload in packages.items():
        _validate_locale_package(payload, reference_messages, expected_locale=locale_id)
    return packages


def _reference_messages(packages: dict[str, dict[str, Any]]) -> dict[str, Any]:
    messages = packages[CHINESE_LOCALE].get("messages")
    if not isinstance(messages, dict):
        raise LocaleCatalogError(f"Invalid bundled locale messages: {CHINESE_LOCALE}")
    return messages


def _read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LocaleCatalogError(f"Invalid JSON file: {path.name}") from exc
    except OSError as exc:
        raise LocaleCatalogError(f"Unable to read file: {path.name}") from exc


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        atomic_replace_path(temporary_path, path)
    except OSError as exc:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise LocaleCatalogError(f"Unable to write locale file: {path.name}") from exc


def _backup_invalid_file(path: Path) -> None:
    if not path.exists():
        return
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    backup_path = path.with_name(f"{path.stem}.invalid-{timestamp}{path.suffix}")
    try:
        atomic_replace_path(path, backup_path)
    except OSError as exc:
        raise LocaleCatalogError(f"Unable to back up invalid locale file: {path.name}") from exc


def _locale_file_path(root: Path, locale_id: str) -> Path:
    _validate_locale_id(locale_id)
    return root / f"{locale_id}.json"


def _validate_locale_id(locale_id: str) -> None:
    if not _LOCALE_ID_PATTERN.fullmatch(locale_id):
        raise LocaleNotFoundError(f"Locale not found: {locale_id}")


def _canonical_locale_id(locale: str) -> str:
    parts = locale.split("-")
    return "-".join(
        part.upper() if index > 0 and len(part) == 2 else part
        for index, part in enumerate(parts)
    )


def _resolve_locales_dir(locales_dir: Path | None) -> Path:
    return locales_dir if locales_dir is not None else get_settings().locales_data_path


def _bundled_locale_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "resources" / "locales"
