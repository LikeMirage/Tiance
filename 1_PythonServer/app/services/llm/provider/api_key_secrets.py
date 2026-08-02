from app.domain.llm.provider_config import ProviderApiKeyConfig
from app.infra.secrets.secret_codec import decrypt_secret
from app.core.errors import BadRequestError


def resolve_api_key_secret(api_key_config: ProviderApiKeyConfig) -> str:
    try:
        return decrypt_secret(api_key_config.api_key_ciphertext)
    except (OSError, RuntimeError, ValueError) as exc:
        raise BadRequestError("API Key 密文不可用，请重新保存供应商配置。") from exc


def has_api_key_secret(api_key_config: ProviderApiKeyConfig) -> bool:
    return bool(api_key_config.api_key_ciphertext)
