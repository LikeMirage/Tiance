from __future__ import annotations

from html.parser import HTMLParser
import re
from typing import Any
from urllib.parse import urlencode, urlsplit

from http_client import HttpFetchError, fetch_url
from url_safety import (
    UnsafeUrlError,
    is_bing_internal_result,
    normalize_public_url,
    unwrap_bing_redirect,
)


BING_SEARCH_URL = "https://www.bing.com/search"
BLOCKED_RESULT_CLASSES = frozenset({"b_ad", "b_ans", "b_pag", "b_msg"})
RESULT_CLASSES = frozenset({"b_algo", "b_nwsAns"})


class BingSearchError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class BingResultsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._stack: list[str] = []
        self._item: dict[str, Any] | None = None
        self._container_tag = ""
        self._container_level = 0
        self._capture_title = False
        self._capture_snippet = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag not in _VOID_TAGS:
            self._stack.append(normalized_tag)
        values = {key.casefold(): value or "" for key, value in attrs}
        classes = {item for item in values.get("class", "").split() if item}

        if self._item is None and classes.intersection(RESULT_CLASSES) and not classes.intersection(BLOCKED_RESULT_CLASSES):
            self._item = {
                "title_parts": [],
                "snippet_parts": [],
                "url": "",
                "result_type": "news" if "b_nwsAns" in classes else "organic",
            }
            self._container_tag = normalized_tag
            self._container_level = len(self._stack)

        if self._item is None:
            return
        if normalized_tag == "h2":
            self._capture_title = True
        elif normalized_tag == "a" and self._capture_title and not self._item["url"]:
            self._item["url"] = values.get("href", "").strip()
        elif normalized_tag == "p" and not self._item["snippet_parts"]:
            self._capture_snippet = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.casefold() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        if self._item is not None:
            if normalized_tag == "h2":
                self._capture_title = False
            elif normalized_tag == "p":
                self._capture_snippet = False
            if normalized_tag == self._container_tag and len(self._stack) == self._container_level:
                self._finish_item()
        if normalized_tag in self._stack:
            reverse_index = self._stack[::-1].index(normalized_tag)
            del self._stack[len(self._stack) - reverse_index - 1 :]

    def handle_data(self, data: str) -> None:
        if self._item is None:
            return
        text = normalize_text(data)
        if not text:
            return
        if self._capture_title:
            self._item["title_parts"].append(text)
        elif self._capture_snippet:
            self._item["snippet_parts"].append(text)

    def close(self) -> None:
        super().close()
        if self._item is not None:
            self._finish_item()

    def _finish_item(self) -> None:
        item = self._item or {}
        title = normalize_text(" ".join(item.get("title_parts", [])))
        snippet = normalize_text(" ".join(item.get("snippet_parts", [])))
        url = str(item.get("url") or "").strip()
        if title and url:
            self.results.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "result_type": str(item.get("result_type") or "organic"),
                }
            )
        self._item = None
        self._container_tag = ""
        self._container_level = 0
        self._capture_title = False
        self._capture_snippet = False


def search_bing(query: str, *, max_results: int, timeout_seconds: int = 20) -> list[dict[str, Any]]:
    normalized_query = normalize_text(query)
    if not normalized_query:
        raise BingSearchError("INVALID_QUERY", "搜索内容不能为空。")

    collected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    first = 1
    while len(collected) < max_results:
        page_size = min(50, max_results - len(collected))
        search_url = f"{BING_SEARCH_URL}?{urlencode({'q': normalized_query, 'count': page_size, 'first': first, 'setlang': 'zh-hans'})}"
        try:
            response = fetch_url(
                search_url,
                timeout_seconds=timeout_seconds,
                max_bytes=4_000_000,
                validate_target=True,
            )
        except HttpFetchError as exc:
            raise BingSearchError(exc.code, exc.message) from exc
        html = response.decode_text()
        if _looks_blocked(html):
            raise BingSearchError("SEARCH_BLOCKED", "Bing 返回了验证或访问限制页面。")
        parser = BingResultsParser()
        try:
            parser.feed(html)
            parser.close()
        except Exception as exc:
            raise BingSearchError("PARSE_FAILED", f"Bing 搜索页面解析失败：{exc}") from exc
        page_results = _normalize_results(parser.results, seen_urls)
        if not page_results:
            if not collected:
                raise BingSearchError("NO_RESULTS", "Bing 没有返回可识别的自然搜索结果。")
            break
        for item in page_results:
            item["rank"] = len(collected) + 1
            collected.append(item)
            if len(collected) >= max_results:
                break
        if len(page_results) < page_size:
            break
        first += len(page_results)
    return collected


def _normalize_results(results: list[dict[str, str]], seen_urls: set[str]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in results:
        raw_url = unwrap_bing_redirect(item.get("url", ""))
        if not raw_url or is_bing_internal_result(raw_url):
            continue
        try:
            url = normalize_public_url(raw_url, resolve_dns=False)
        except UnsafeUrlError:
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        hostname = (urlsplit(url).hostname or "").lower()
        normalized.append(
            {
                "title": normalize_text(item.get("title", "")),
                "url": url,
                "snippet": normalize_text(item.get("snippet", "")),
                "source": hostname,
                "result_type": item.get("result_type", "organic"),
            }
        )
    return normalized


def normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _looks_blocked(html: str) -> bool:
    lowered = html.casefold()
    signals = (
        "our systems have detected unusual traffic",
        "verify you are a human",
        "unusual traffic from your computer network",
        "请输入验证码",
        "安全验证",
    )
    return any(signal in lowered for signal in signals)


_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
