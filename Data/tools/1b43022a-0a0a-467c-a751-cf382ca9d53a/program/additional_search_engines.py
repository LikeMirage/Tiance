from __future__ import annotations

from html.parser import HTMLParser
import json
import re
from typing import Any
from urllib.parse import parse_qs, urlencode, unquote, urljoin, urlsplit

from http_client import HttpFetchError, fetch_url
from url_safety import UnsafeUrlError, normalize_public_url


class SearchEngineError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._item: dict[str, Any] | None = None
        self._container_depth = 0
        self._depth = 0
        self._title_depth = 0
        self._snippet_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._depth += 1
        values = {key.casefold(): value or "" for key, value in attrs}
        classes = set(values.get("class", "").split())
        if self._item is None and {"result", "results_links_deep"}.intersection(classes):
            self._item = {"title": [], "snippet": [], "url": ""}
            self._container_depth = self._depth
        if self._item is None:
            return
        if tag.casefold() == "a" and "result__a" in classes:
            self._title_depth = self._depth
            self._item["url"] = values.get("href", "").strip()
        elif "result__snippet" in classes:
            self._snippet_depth = self._depth

    def handle_endtag(self, tag: str) -> None:
        if self._item is not None:
            if self._depth == self._title_depth:
                self._title_depth = 0
            if self._depth == self._snippet_depth:
                self._snippet_depth = 0
            if self._depth == self._container_depth:
                self._finish_item()
        self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        if self._item is None:
            return
        text = normalize_text(data)
        if not text:
            return
        if self._title_depth:
            self._item["title"].append(text)
        elif self._snippet_depth:
            self._item["snippet"].append(text)

    def close(self) -> None:
        super().close()
        if self._item is not None:
            self._finish_item()

    def _finish_item(self) -> None:
        item = self._item or {}
        title = normalize_text(" ".join(item.get("title", [])))
        snippet = normalize_text(" ".join(item.get("snippet", [])))
        url = unwrap_duckduckgo_url(str(item.get("url") or ""))
        if title and url:
            self.results.append({"title": title, "url": url, "snippet": snippet})
        self._item = None
        self._container_depth = 0
        self._title_depth = 0
        self._snippet_depth = 0


class SogouParser(HTMLParser):
    SNIPPET_CLASSES = frozenset({"star-wiki", "fz-mid", "attribute-centent", "str_info"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._item: dict[str, Any] | None = None
        self._depth = 0
        self._title_block_depth = 0
        self._title_depth = 0
        self._snippet_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._depth += 1
        values = {key.casefold(): value or "" for key, value in attrs}
        classes = set(values.get("class", "").split())
        if "vr-title" in classes:
            self._finish_item()
            self._item = {"title": [], "snippet": [], "url": ""}
            self._title_block_depth = self._depth
        if tag.casefold() == "a" and self._item is not None and self._title_block_depth:
            self._item["url"] = values.get("href", "").strip()
            self._title_depth = self._depth
            return
        if self._item is not None and classes.intersection(self.SNIPPET_CLASSES):
            self._snippet_depth = self._depth

    def handle_endtag(self, tag: str) -> None:
        if self._depth == self._title_depth:
            self._title_depth = 0
        if self._depth == self._title_block_depth:
            self._title_block_depth = 0
        if self._depth == self._snippet_depth:
            self._snippet_depth = 0
        self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        if self._item is None:
            return
        text = normalize_text(data)
        if not text:
            return
        if self._title_depth:
            self._item["title"].append(text)
        elif self._snippet_depth:
            self._item["snippet"].append(text)

    def close(self) -> None:
        super().close()
        self._finish_item()

    def _finish_item(self) -> None:
        if self._item is not None:
            title = normalize_text(" ".join(self._item.get("title", [])))
            snippet = normalize_text(" ".join(self._item.get("snippet", [])))
            url = urljoin("https://www.sogou.com/", str(self._item.get("url") or ""))
            if title and url:
                self.results.append({"title": title, "url": url, "snippet": snippet})
        self._item = None
        self._title_block_depth = 0
        self._title_depth = 0
        self._snippet_depth = 0


def search_duckduckgo(query: str, *, max_results: int, timeout_seconds: int = 20) -> list[dict[str, Any]]:
    url = f"https://html.duckduckgo.com/html/?{urlencode({'q': query})}"
    html = fetch_search_text(url, "DuckDuckGo", timeout_seconds)
    parser = DuckDuckGoParser()
    parser.feed(html)
    parser.close()
    return finalize_results(parser.results, max_results=max_results)


def search_baidu(query: str, *, max_results: int, timeout_seconds: int = 20) -> list[dict[str, Any]]:
    url = f"https://www.baidu.com/s?{urlencode({'wd': query, 'tn': 'json', 'rn': max_results})}"
    text = fetch_search_text(url, "百度", timeout_seconds)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SearchEngineError("PARSE_FAILED", "百度没有返回可解析的搜索结果。") from exc
    entries = payload.get("feed", {}).get("entry", [])
    results = [
        {
            "title": normalize_text(item.get("title")),
            "url": str(item.get("url") or "").strip(),
            "snippet": normalize_text(item.get("abs")),
        }
        for item in entries
        if isinstance(item, dict)
    ]
    return finalize_results(results, max_results=max_results)


def search_sogou(query: str, *, max_results: int, timeout_seconds: int = 20) -> list[dict[str, Any]]:
    url = f"https://www.sogou.com/web?{urlencode({'query': query})}"
    html = fetch_search_text(url, "搜狗", timeout_seconds, max_bytes=6_000_000)
    parser = SogouParser()
    parser.feed(html)
    parser.close()
    return finalize_results(parser.results, max_results=max_results)


def fetch_search_text(
    url: str,
    engine_name: str,
    timeout_seconds: int,
    *,
    max_bytes: int = 4_000_000,
) -> str:
    try:
        response = fetch_url(url, timeout_seconds=timeout_seconds, max_bytes=max_bytes)
    except HttpFetchError as exc:
        raise SearchEngineError(exc.code, f"{engine_name} 搜索失败：{exc.message}") from exc
    html = response.decode_text()
    if looks_blocked(html):
        raise SearchEngineError("SEARCH_BLOCKED", f"{engine_name} 返回了验证或访问限制页面。")
    return html


def finalize_results(results: list[dict[str, str]], *, max_results: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in results:
        title = normalize_text(item.get("title"))
        raw_url = str(item.get("url") or "").strip()
        if not title or not raw_url:
            continue
        try:
            url = normalize_public_url(raw_url, resolve_dns=False)
        except UnsafeUrlError:
            continue
        if url in seen:
            continue
        seen.add(url)
        output.append(
            {
                "rank": len(output) + 1,
                "title": title,
                "url": url,
                "snippet": normalize_text(item.get("snippet")),
                "source": (urlsplit(url).hostname or "").lower(),
                "result_type": "organic",
            }
        )
        if len(output) >= max_results:
            break
    if not output:
        raise SearchEngineError("NO_RESULTS", "搜索引擎没有返回可识别的自然搜索结果。")
    return output


def unwrap_duckduckgo_url(url: str) -> str:
    text = str(url or "").strip()
    if text.startswith("//"):
        text = "https:" + text
    parsed = urlsplit(text)
    if (parsed.hostname or "").lower().endswith("duckduckgo.com") and parsed.path == "/l/":
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(target).strip()
    return text


def normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def looks_blocked(html: str) -> bool:
    lowered = html.casefold()
    return any(
        signal in lowered
        for signal in (
            "verify you are a human",
            "unusual traffic",
            "请输入验证码",
            "安全验证",
            "访问过于频繁",
        )
    )
