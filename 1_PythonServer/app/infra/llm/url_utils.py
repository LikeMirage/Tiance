# LLM API URL 工具函数
# 构建模型发现 URL、格式化 API 主机名、追加查询参数等

from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from app.core.errors import BadRequestError
from app.domain.llm.provider_runtime import ProviderRuntimeConfig


def append_query_param(url: str, key: str, value: str) -> str:
    """向 URL 追加查询参数（覆盖已存在的同名参数）"""
    parsed = urlsplit(url)
    query_items = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query_items[key] = value
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query_items),
            parsed.fragment,
        )
    )


def render_generation_url(
    url_template: str,
    *,
    model_id: str,
    action: str,
) -> str:
    """渲染显式生成地址模板；不补版本号、不追加协议路径。"""

    normalized_model_id = model_id.removeprefix("models/")
    return (
        url_template.replace("{model}", quote(normalized_model_id, safe="-._~"))
        .replace("{action}", action)
    )


def require_model_discovery_url(runtime_config: ProviderRuntimeConfig) -> str:
    url = runtime_config.model_discovery_url
    if not url:
        raise BadRequestError("当前供应商未配置模型列表 API 地址。")
    return url
