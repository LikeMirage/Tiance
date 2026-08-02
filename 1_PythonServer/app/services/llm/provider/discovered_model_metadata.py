# 发现模型元数据丰富服务
# 从模型 ID 和原始响应中推导 family_group 和 capability_tags

import re
from dataclasses import replace

from app.domain.llm.discovered_model import DiscoveredModel

_PROVIDER_PREFIX_DELIMITERS = {
    "aihubmix",
    "dmxapi",
    "ocoolai",
    "o3",
    "siliconflow",
}

_EMBEDDING_PATTERN = re.compile(
    r"(?:^|[/:_ -])(?:embed(?:ding)?|text-embedding|bge|gte-|jina-embeddings?|voyage(?:-|$))",
    re.IGNORECASE,
)
_RERANK_PATTERN = re.compile(r"(?:rerank|reranker)", re.IGNORECASE)
_REASONING_PATTERN = re.compile(
    r"(?:reason(?:er|ing)?|thinking|deepseek-r1|deepseek-reasoner|qwq|(?:^|[/:_ -])o[134](?:$|[/:_ -])|gpt-5(?:$|[./:_ -]))",
    re.IGNORECASE,
)
_VISION_PATTERN = re.compile(
    r"(?:vision|visual|multimodal|(?:^|[/:_ -])vl(?:$|[/:_ -])|omni|"
    r"image|video|seedance|cogview|llava|moondream|minicpm|internvl|pixtral|"
    r"qwen[\w.-]*vl|glm-[\w.-]*v|deepseek-vl)",
    re.IGNORECASE,
)
_VISION_CHAT_MODEL_PATTERN = re.compile(
    r"(?:gpt-(?:4o|4[.]1|4[.]5|5)(?:$|[/:_ .-])|chatgpt-4o|"
    r"claude-(?:3|haiku-4|sonnet-4|opus-4)|"
    r"gemini-(?:1[.]5|2[.]0|2[.]5|3|flash-latest|pro-latest|flash-lite-latest)|"
    r"grok-(?:vision|4)|llama-4|gemma-?[34]|kimi-k2[.]5)",
    re.IGNORECASE,
)
_VISION_EXCLUDED_PATTERN = re.compile(
    r"(?:gpt-4-(?:32k|\d{4}|turbo-preview)|o[13]-(?:mini|preview))",
    re.IGNORECASE,
)
_DOUBAO_VISION_PATTERN = re.compile(
    r"\bdoubao-(?:seed-1[.-][68]|seed-2[.-]0|seed-code)(?:-[\w-]+)?\b",
    re.IGNORECASE,
)
_WEBSEARCH_PATTERN = re.compile(r"(?:^|[/:_ -])(?:search|sonar|grok)(?:$|[/:_ -])", re.IGNORECASE)
_IMAGE_GENERATION_PATTERN = re.compile(
    r"(?:image[-_ ]?generation|text[-_ ]?to[-_ ]?image|gpt[-_ ]?image|dall[-_ ]?e|"
    r"grok-2-image|imagen|seedream|cogview|flux|stable[-_ ]?diffusion|stabilityai|"
    r"(?:^|[/:_ .-])sd-[\w-]+|sdxl|qwen-image|janus|midjourney|"
    r"(?:^|[/:_ .-])mj-[\w-]+|z-image|longcat-image|hunyuanimage|kandinsky|kolors|"
    r"gemini-[\w.-]+-image(?:$|[/:_ .-]))",
    re.IGNORECASE,
)
_VIDEO_GENERATION_PATTERN = re.compile(
    r"(?:video[-_ ]?generation|text[-_ ]?to[-_ ]?video|image[-_ ]?to[-_ ]?video|"
    r"sora|veo|seedance|(?:^|[/:_ .-])wan(?:$|[/:_ .-])|hailuo|kling|runway|pika)",
    re.IGNORECASE,
)

_CAPABILITY_ORDER = (
    "reasoning",
    "vision",
    "websearch",
    "embedding",
    "rerank",
    "function_calling",
    "image_generation",
    "video_generation",
)


def enrich_discovered_models(models: list[DiscoveredModel]) -> list[DiscoveredModel]:
    """批量丰富发现模型的元数据（族群、功能标签）"""
    return [enrich_discovered_model(model) for model in models]


def enrich_discovered_model(model: DiscoveredModel) -> DiscoveredModel:
    """丰富单个发现模型的元数据：从模型 ID 和原始响应推导族系和功能标签"""
    return replace(
        model,
        family_group=_resolve_family_group(model),
        capability_tags=_derive_capability_tags(model),
    )


def _resolve_family_group(model: DiscoveredModel) -> str:
    """解析模型族系：优先取原始响应的 family 字段，再通过模型 ID 推导"""
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


def _derive_capability_tags(model: DiscoveredModel) -> tuple[str, ...]:
    """从模型 ID、显示名和原始响应推导能力标签（reasoning/vision/websearch/embedding/rerank/function_calling）"""
    raw_payload = model.raw_payload or {}
    model_id = model.model_id.strip().lower()
    display_name = model.display_name.strip().lower()

    features = _extract_string_tokens(raw_payload.get("features"))
    endpoints = _extract_string_tokens(
        raw_payload.get("endpoints") or raw_payload.get("supported_endpoint_types")
    )
    input_modalities = _extract_input_modalities(raw_payload)
    output_modalities = _extract_output_modalities(raw_payload)
    is_rerank_model = _is_rerank_model(model_id, display_name, features, endpoints)
    is_embedding_model = (
        not is_rerank_model
        and _is_embedding_model(model_id, display_name, features, endpoints)
    )
    is_image_generation_model = _is_image_generation_model(
        model_id,
        display_name,
        features,
        endpoints,
        output_modalities,
    )
    is_video_generation_model = _is_video_generation_model(
        model_id,
        display_name,
        features,
        endpoints,
        output_modalities,
    )
    is_specialized_non_chat_model = (
        is_rerank_model
        or is_embedding_model
        or is_image_generation_model
        or is_video_generation_model
    )

    tags: list[str] = []

    if is_rerank_model:
        tags.append("rerank")

    if is_embedding_model:
        tags.append("embedding")

    if not is_specialized_non_chat_model and _is_reasoning_model(model_id, display_name, features):
        tags.append("reasoning")

    if (
        is_image_generation_model
        or is_video_generation_model
        or _is_vision_model(
            model_id,
            display_name,
            features,
            input_modalities,
        )
    ):
        tags.append("vision")

    if _is_websearch_model(model_id, display_name, features):
        tags.append("websearch")

    if not is_specialized_non_chat_model and _is_function_calling_model(features, endpoints):
        tags.append("function_calling")

    if is_image_generation_model:
        tags.append("image_generation")

    if is_video_generation_model:
        tags.append("video_generation")

    return tuple(
        capability
        for capability in _CAPABILITY_ORDER
        if capability in tags
    )


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


def _is_embedding_model(
    model_id: str,
    display_name: str,
    features: set[str],
    endpoints: set[str],
) -> bool:
    """判断是否为 embedding 模型"""
    if "embedding" in features or "embeddings" in features:
        return True
    if "embeddings" in endpoints or "embedding" in endpoints:
        return True
    return bool(_EMBEDDING_PATTERN.search(model_id) or _EMBEDDING_PATTERN.search(display_name))


def _is_rerank_model(
    model_id: str,
    display_name: str,
    features: set[str],
    endpoints: set[str],
) -> bool:
    """判断是否为 rerank 模型"""
    if "rerank" in features or "reranker" in features:
        return True
    if "rerank" in endpoints or "reranker" in endpoints:
        return True
    return bool(_RERANK_PATTERN.search(model_id) or _RERANK_PATTERN.search(display_name))


def _is_reasoning_model(model_id: str, display_name: str, features: set[str]) -> bool:
    """判断是否为推理模型"""
    if "thinking" in features or "reasoning" in features:
        return True
    return bool(_REASONING_PATTERN.search(model_id) or _REASONING_PATTERN.search(display_name))


def _is_vision_model(
    model_id: str,
    display_name: str,
    features: set[str],
    modalities: set[str],
) -> bool:
    """判断是否为视觉/多模态模型"""
    if "image" in modalities:
        return True
    if "vision" in features:
        return True
    if _VISION_EXCLUDED_PATTERN.search(model_id) or _VISION_EXCLUDED_PATTERN.search(display_name):
        return False
    return bool(
        _VISION_PATTERN.search(model_id)
        or _VISION_PATTERN.search(display_name)
        or _VISION_CHAT_MODEL_PATTERN.search(model_id)
        or _VISION_CHAT_MODEL_PATTERN.search(display_name)
        or _DOUBAO_VISION_PATTERN.search(model_id)
        or _DOUBAO_VISION_PATTERN.search(display_name)
    )


def _is_image_generation_model(
    model_id: str,
    display_name: str,
    features: set[str],
    endpoints: set[str],
    output_modalities: set[str],
) -> bool:
    if "image" in output_modalities:
        return True
    if {"image_generation", "text_to_image", "images"} & features:
        return True
    if {"image_generation", "images"} & endpoints:
        return True
    return bool(
        _IMAGE_GENERATION_PATTERN.search(model_id)
        or _IMAGE_GENERATION_PATTERN.search(display_name)
    )


def _is_video_generation_model(
    model_id: str,
    display_name: str,
    features: set[str],
    endpoints: set[str],
    output_modalities: set[str],
) -> bool:
    if "video" in output_modalities:
        return True
    if {"video_generation", "text_to_video", "videos"} & features:
        return True
    if {"video_generation", "videos"} & endpoints:
        return True
    return bool(
        _VIDEO_GENERATION_PATTERN.search(model_id)
        or _VIDEO_GENERATION_PATTERN.search(display_name)
    )


def _is_websearch_model(model_id: str, display_name: str, features: set[str]) -> bool:
    """判断是否为联网搜索模型"""
    if {"web", "search", "web_search"} & features:
        return True
    return bool(_WEBSEARCH_PATTERN.search(model_id) or _WEBSEARCH_PATTERN.search(display_name))


def _is_function_calling_model(features: set[str], endpoints: set[str]) -> bool:
    """判断是否支持函数调用"""
    if {"function_calling", "tools", "structured_outputs"} & features:
        return True
    return bool({"tool_calls", "function_calling"} & endpoints)
