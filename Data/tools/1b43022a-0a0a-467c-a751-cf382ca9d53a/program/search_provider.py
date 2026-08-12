from __future__ import annotations

from typing import Any, Callable

from additional_search_engines import (
    SearchEngineError,
    search_baidu,
    search_duckduckgo,
    search_sogou,
)
from bing_search import BingSearchError, search_bing


SUPPORTED_ENGINES = ("baidu", "bing", "duckduckgo", "sogou")
ENGINE_LABELS = {
    "baidu": "百度",
    "bing": "Bing",
    "duckduckgo": "DuckDuckGo",
    "sogou": "搜狗",
}


class SearchProviderError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def search_web(engine: str, query: str, *, max_results: int) -> list[dict[str, Any]]:
    providers: dict[str, Callable[..., list[dict[str, Any]]]] = {
        "baidu": search_baidu,
        "bing": search_bing,
        "duckduckgo": search_duckduckgo,
        "sogou": search_sogou,
    }
    provider = providers.get(engine)
    if provider is None:
        raise SearchProviderError("INVALID_ENGINE", f"不支持的搜索引擎：{engine}")
    try:
        return provider(query, max_results=max_results)
    except (BingSearchError, SearchEngineError) as exc:
        raise SearchProviderError(exc.code, exc.message) from exc
