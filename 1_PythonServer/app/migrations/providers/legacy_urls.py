"""Frozen URL inference used only to upgrade old provider files."""
import re
from urllib.parse import urlsplit,urlunsplit
from app.domain.llm.provider_catalog import ProviderProtocolFamily
_API_VERSION_SEGMENT = re.compile(r"^v\d+(?:beta|alpha)?$", re.IGNORECASE)

def derive_model_discovery_url(
    api_base_url: str,
    protocol_family: ProviderProtocolFamily | str,
) -> str | None:
    """为历史文件迁移生成模型列表地址；正式配置链路不调用。"""

    parsed = urlsplit(api_base_url.strip())
    if not parsed.scheme or not parsed.netloc:
        return None

    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments:
        default_prefix = (
            "v1beta"
            if _protocol_value(protocol_family)
            == ProviderProtocolFamily.GEMINI_GENERATE_CONTENT.value
            else "v1"
        )
        model_segments = [default_prefix, "models"]
    elif _is_gemini_generation_template(segments):
        model_segments = segments[:-1]
    elif len(segments) >= 2 and segments[-2:] == ["chat", "completions"]:
        model_segments = [*segments[:-2], "models"]
    elif segments[-1] in {"responses", "messages"}:
        model_segments = [*segments[:-1], "models"]
    elif segments[-1] == "models":
        model_segments = segments
    elif _API_VERSION_SEGMENT.fullmatch(segments[-1]):
        model_segments = [*segments, "models"]
    else:
        model_segments = [*segments[:-1], "models"]

    model_path = f"/{'/'.join(model_segments)}"
    return urlunsplit((parsed.scheme, parsed.netloc, model_path, "", ""))


def _is_gemini_generation_template(segments: list[str]) -> bool:
    return (
        len(segments) >= 2
        and segments[-2] == "models"
        and "{model}" in segments[-1]
    )


def _protocol_value(protocol_family: ProviderProtocolFamily | str) -> str:
    return (
        protocol_family.value
        if isinstance(protocol_family, ProviderProtocolFamily)
        else str(protocol_family)
    )
