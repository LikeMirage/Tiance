"""Initial model labels: provider defaults, upstream metadata and shared name inference."""

import re
from dataclasses import replace

from app.domain.llm.discovered_model import DiscoveredModel
from app.domain.llm.model_capability_tags import MODEL_CAPABILITY_TAGS, ordered_capability_tags
from app.repositories.llm.provider_adaptation_rules_repository import ProviderAdaptationRulesRepository
from app.services.llm.provider.model_name_capabilities import infer_name_capability_tags

_PROVIDER_PREFIX_DELIMITERS = {
    "aihubmix",
    "dmxapi",
    "ocoolai",
    "o3",
    "siliconflow",
}

def enrich_discovered_models(
    models: list[DiscoveredModel],
    *,
    rules_repository: ProviderAdaptationRulesRepository | None = None,
) -> list[DiscoveredModel]:
    return [enrich_discovered_model(model, rules_repository=rules_repository) for model in models]


def enrich_discovered_model(
    model: DiscoveredModel,
    *,
    rules_repository: ProviderAdaptationRulesRepository | None = None,
) -> DiscoveredModel:
    family_group = _resolve_family_group(model)
    tags = set(infer_name_capability_tags(model.model_id, model.display_name))
    tags.update(model.capability_tags)
    tags.update(_derive_metadata_tags(model.raw_payload or {}))
    if rules_repository is not None:
        rules = rules_repository.resolve(
            provider_id=model.provider_id,
            model_id=model.model_id,
            family_group=family_group,
        )
        if rules is not None:
            tags.update(rules.capability_tags or ())
    return replace(model, family_group=family_group, capability_tags=ordered_capability_tags(tags))


def _resolve_family_group(model: DiscoveredModel) -> str:
    """解析模型族系：优先取原始响应的 family 字段，再通过模型 ID 推导"""
    if model.family_group.strip():
        return model.family_group.strip()
    family_from_payload = _extract_family_group_from_payload(model.raw_payload or {})
    if family_from_payload:
        return family_from_payload
    return _derive_family_group(model.provider_id, model.model_id)


def _extract_family_group_from_payload(raw_payload: dict[str, object]) -> str:
    direct_family = raw_payload.get("family")
    if isinstance(direct_family, str) and direct_family.strip():
        return direct_family.strip().lower()

    details = raw_payload.get("details")
    if isinstance(details, dict):
        nested_family = details.get("family")
        if isinstance(nested_family, str) and nested_family.strip():
            return nested_family.strip().lower()

    return ""


def _derive_family_group(provider_id: str, model_id: str) -> str:
    """从模型 ID 推导族系（按分隔符拆分取前缀）"""
    normalized_model_id = model_id.strip().lower()
    if not normalized_model_id:
        return provider_id.strip().lower()

    first_delimiters = ["/", " ", ":"]
    second_delimiters = ["-", "_"]

    if provider_id.strip().lower() in _PROVIDER_PREFIX_DELIMITERS:
        first_delimiters = ["/", " ", "-", "_", ":"]
        second_delimiters = []

    for delimiter in first_delimiters:
        if delimiter in normalized_model_id:
            return normalized_model_id.split(delimiter)[0]

    for delimiter in second_delimiters:
        if delimiter in normalized_model_id:
            parts = normalized_model_id.split(delimiter)
            return f"{parts[0]}-{parts[1]}" if len(parts) > 1 else parts[0]

    return normalized_model_id


def _derive_metadata_tags(raw: dict[str, object]) -> set[str]:
    features = _extract_string_tokens(raw.get("features"))
    endpoints = _extract_string_tokens(raw.get("endpoints") or raw.get("supported_endpoint_types"))
    inputs = _extract_input_modalities(raw)
    outputs = _extract_output_modalities(raw)
    tags = set(MODEL_CAPABILITY_TAGS) & features
    if "image" in inputs or "vision" in features:
        tags.add("vision")
    if {"embedding", "embeddings"} & (features | endpoints):
        tags.add("embedding")
    if {"rerank", "reranker"} & (features | endpoints):
        tags.discard("embedding")
        tags.add("rerank")
    if "image" in outputs or {"image_generation", "text_to_image", "images"} & (features | endpoints):
        tags.update(("vision", "image_generation"))
    if "video" in outputs or {"video_generation", "text_to_video", "videos"} & (features | endpoints):
        tags.update(("vision", "video_generation"))
    if {"thinking", "reasoning"} & features:
        tags.add("reasoning")
    if {"function_calling", "tools", "structured_outputs"} & features or {"tool_calls", "function_calling"} & endpoints:
        tags.add("function_calling")
    if {"speech_to_text", "transcription", "asr"} & (features | endpoints):
        tags.add("speech_to_text")
    if {"tts", "text_to_speech", "speech"} & (features | endpoints):
        tags.add("tts")
    return tags


def _extract_input_modalities(raw_payload: dict[str, object]) -> set[str]:
    """从原始响应中提取输入模态信息。"""
    modalities = _extract_string_tokens(raw_payload.get("input_modalities"))
    architecture = raw_payload.get("architecture")
    if isinstance(architecture, dict):
        modalities |= _extract_string_tokens(architecture.get("modality"))
        modalities |= _extract_string_tokens(architecture.get("input_modalities"))
    return modalities


def _extract_output_modalities(raw_payload: dict[str, object]) -> set[str]:
    """从原始响应中提取输出模态信息。"""
    modalities = _extract_string_tokens(raw_payload.get("output_modalities"))
    architecture = raw_payload.get("architecture")
    if isinstance(architecture, dict):
        modalities |= _extract_string_tokens(architecture.get("output_modalities"))
    return modalities


def _extract_string_tokens(value: object) -> set[str]:
    """从字符串或列表中提取标记集"""
    if isinstance(value, str):
        return {
            token.strip().lower()
            for token in re.split(r"[,;/|]", value)
            if token.strip()
        }

    if isinstance(value, (list, tuple, set)):
        return {
            str(token).strip().lower()
            for token in value
            if str(token).strip()
        }

    return set()
