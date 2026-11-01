"""Read-only export of legacy provider rows; source tables remain intact."""
from contextlib import closing
from pathlib import Path
import sqlite3
import json
from typing import Any
from app.domain.llm.provider_catalog import ProviderProtocolFamily, default_model_discovery_auth_scheme, default_model_discovery_strategy
from app.repositories.llm.provider_file_store import PROVIDER_SCHEMA_VERSION

def _load_legacy_provider_data(database_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "manifests": {},
        "configs": {},
        "credentials": {},
        "models": {},
        "order": [],
    }
    if not database_path.is_file():
        return result

    with closing(sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if "custom_provider_catalog" in tables:
            for row in connection.execute("SELECT * FROM custom_provider_catalog").fetchall():
                provider_id = str(row["provider_id"])
                protocol_family = ProviderProtocolFamily(str(row["protocol_family"]))
                result["manifests"][provider_id] = {
                    "schemaVersion": PROVIDER_SCHEMA_VERSION,
                    "id": provider_id,
                    "displayName": str(row["display_name"]),
                    "profileId": _legacy_profile_id(str(row["upstream_key"])),
                    "protocolFamily": protocol_family.value,
                    "generationAuthSchemes": {
                        protocol_family.value: str(row["auth_scheme"])
                    },
                    "modelDiscoveryStrategy": default_model_discovery_strategy(
                        protocol_family
                    ).value,
                    "modelDiscoveryAuthScheme": default_model_discovery_auth_scheme(
                        default_model_discovery_strategy(protocol_family)
                    ).value,
                    "apiBaseUrl": str(row["api_base_url"]),
                    "modelDiscoveryUrl": None,
                    "enabled": False,
                    "reasoningReplayMode": "tool_call_rounds",
                    "createdAt": str(row["created_at"]),
                    "updatedAt": str(row["updated_at"]),
                }
        if "provider_configs" in tables:
            for row in connection.execute("SELECT * FROM provider_configs").fetchall():
                result["configs"][str(row["provider_id"])] = {
                    "apiBaseUrl": str(row["api_base_url"]),
                    "enabled": bool(row["enabled"]),
                    "createdAt": str(row["created_at"]),
                    "updatedAt": str(row["updated_at"]),
                }
        if "provider_config_api_keys" in tables:
            for row in connection.execute(
                "SELECT * FROM provider_config_api_keys ORDER BY provider_id, sort_order, created_at"
            ).fetchall():
                provider_id = str(row["provider_id"])
                result["credentials"].setdefault(provider_id, []).append(
                    {
                        "keyId": str(row["key_id"]),
                        "hint": row["api_key_hint"],
                        "ciphertext": row["api_key_ciphertext"],
                        "pollWeight": int(row["poll_weight"]),
                        "sortOrder": int(row["sort_order"]),
                        "createdAt": str(row["created_at"]),
                        "updatedAt": str(row["updated_at"]),
                    }
                )
        if "provider_custom_models" in tables:
            for row in connection.execute(
                "SELECT * FROM provider_custom_models ORDER BY provider_id, created_at, model_id"
            ).fetchall():
                provider_id = str(row["provider_id"])
                result["models"].setdefault(provider_id, []).append(
                    {
                        "modelId": str(row["model_id"]),
                        "displayName": str(row["display_name"]),
                        "familyGroup": str(row["family_group"]),
                        "capabilityTags": _load_json_list(row["capability_tags"]),
                        "note": str(row["note"]),
                        "priceCurrency": str(row["price_currency"]),
                        "inputPricePerMillion": row["input_price_per_million"],
                        "cacheHitPricePerMillion": row["cache_hit_price_per_million"],
                        "outputPricePerMillion": row["output_price_per_million"],
                        "createdAt": str(row["created_at"]),
                        "updatedAt": str(row["updated_at"]),
                    }
                )
        if "provider_catalog_order" in tables:
            result["order"] = [
                str(row["provider_id"])
                for row in connection.execute(
                    "SELECT provider_id FROM provider_catalog_order ORDER BY sort_order"
                ).fetchall()
            ]
    return result


def _generic_manifest(provider_id: str, now: str) -> dict[str, Any]:
    return {
        "schemaVersion": PROVIDER_SCHEMA_VERSION,
        "id": provider_id,
        "displayName": provider_id,
        "profileId": "generic",
        "protocolFamily": "openai_compatible",
        "generationAuthSchemes": {"openai_compatible": "bearer_token"},
        "modelDiscoveryStrategy": "openai_models",
        "modelDiscoveryAuthScheme": "bearer_token",
        "generationUrls": {
            ProviderProtocolFamily.OPENAI_COMPATIBLE.value: (
                "https://example.invalid/v1/chat/completions"
            )
        },
        "modelDiscoveryUrl": None,
        "enabled": False,
        "reasoningReplayMode": "tool_call_rounds",
        "createdAt": now,
        "updatedAt": now,
    }


def _legacy_profile_id(upstream_key: str) -> str:
    if upstream_key == "deepseek":
        return "deepseek"
    if upstream_key == "doubao":
        return "volcengine"
    return "generic"




def _load_json_list(value: object) -> list[str]:
    try:
        loaded = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return [item for item in loaded if isinstance(item, str)] if isinstance(loaded, list) else []
