"""Model labels shared by discovery, provider defaults and saved models."""

from collections.abc import Iterable

MODEL_CAPABILITY_TAGS = (
    "reasoning",
    "vision",
    "function_calling",
    "embedding",
    "rerank",
    "speech_to_text",
    "tts",
    "image_generation",
    "video_generation",
)


def ordered_capability_tags(tags: Iterable[str]) -> tuple[str, ...]:
    selected = set(tags)
    return tuple(tag for tag in MODEL_CAPABILITY_TAGS if tag in selected)
