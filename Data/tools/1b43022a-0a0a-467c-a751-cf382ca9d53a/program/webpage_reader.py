from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit

from http_client import HttpFetchError, fetch_url


MIN_USEFUL_CHARACTERS = 80
MAX_PAGE_BYTES = 10_000_000


@dataclass(frozen=True, slots=True)
class PageReadResult:
    ok: bool
    requested_url: str
    final_url: str
    title: str
    content_type: str
    status_code: int | None
    content: str
    binary_content: bytes | None
    binary_extension: str | None
    byte_count: int
    character_count: int
    truncated: bool
    extraction_method: str | None
    error_code: str | None
    error: str | None
    warnings: tuple[str, ...]


class MainTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.body_parts: list[str] = []
        self.primary_parts: list[str] = []
        self._stack: list[tuple[str, bool, bool, bool]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.casefold()
        values = {key.casefold(): value or "" for key, value in attrs}
        parent_skipped = self._stack[-1][1] if self._stack else False
        parent_primary = self._stack[-1][2] if self._stack else False
        parent_body = self._stack[-1][3] if self._stack else False
        skipped = parent_skipped or normalized_tag in _SKIP_TAGS or _is_hidden(values)
        primary = parent_primary or normalized_tag in {"main", "article"} or values.get("role", "").casefold() == "main"
        body = parent_body or normalized_tag == "body"

        if normalized_tag not in _VOID_TAGS:
            self._stack.append((normalized_tag, skipped, primary, body))
        if skipped:
            return
        if normalized_tag in _BLOCK_TAGS:
            self._append("\n", primary=primary, body=body)
        if normalized_tag in _HEADING_PREFIXES:
            self._append(_HEADING_PREFIXES[normalized_tag], primary=primary, body=body)
        elif normalized_tag == "li":
            self._append("- ", primary=primary, body=body)
        elif normalized_tag in {"td", "th"}:
            self._append(" | ", primary=primary, body=body)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.casefold() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        state = self._stack[-1] if self._stack else ("", False, False, False)
        if not state[1] and normalized_tag in _BLOCK_TAGS:
            self._append("\n", primary=state[2], body=state[3])
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == normalized_tag:
                del self._stack[index:]
                break

    def handle_data(self, data: str) -> None:
        state = self._stack[-1] if self._stack else ("", False, False, False)
        if state[1]:
            return
        text = str(data or "")
        if not text.strip():
            return
        if any(item[0] == "title" for item in self._stack):
            self.title_parts.append(text)
            return
        self._append(text, primary=state[2], body=state[3])

    def title(self) -> str:
        return normalize_inline(" ".join(self.title_parts))

    def extracted_content(self) -> tuple[str, str]:
        primary = normalize_document("".join(self.primary_parts))
        if len(primary) >= MIN_USEFUL_CHARACTERS:
            return primary, "main-content"
        return normalize_document("".join(self.body_parts)), "body-fallback"

    def _append(self, value: str, *, primary: bool, body: bool) -> None:
        if body:
            self.body_parts.append(value)
        if primary:
            self.primary_parts.append(value)


def read_page(url: str, *, timeout_seconds: int = 25) -> PageReadResult:
    try:
        response = fetch_url(
            url,
            timeout_seconds=timeout_seconds,
            max_bytes=MAX_PAGE_BYTES,
            validate_target=True,
        )
        response, client_redirects = _follow_client_redirects(
            response,
            timeout_seconds=timeout_seconds,
        )
    except HttpFetchError as exc:
        return PageReadResult(
            ok=False,
            requested_url=url,
            final_url="",
            title="",
            content_type="",
            status_code=exc.status_code,
            content="",
            binary_content=None,
            binary_extension=None,
            byte_count=0,
            character_count=0,
            truncated=False,
            extraction_method=None,
            error_code=exc.code,
            error=exc.message,
            warnings=(),
        )

    warnings: list[str] = [
        f"网页通过页面跳转转向：{target}" for target in client_redirects
    ]
    if response.truncated:
        warnings.append(f"网页超过 {MAX_PAGE_BYTES} 字节，只保存前 {MAX_PAGE_BYTES} 字节。")
    content_type = response.content_type
    if content_type in {"text/html", "application/xhtml+xml"}:
        html = response.decode_text()
        if _looks_blocked(html):
            return _failed_response(response, "PAGE_BLOCKED", "网页返回了验证码、登录或访问限制页面。", warnings)
        parser = MainTextExtractor()
        try:
            parser.feed(html)
            parser.close()
        except Exception as exc:
            return _failed_response(response, "CONTENT_EXTRACTION_FAILED", f"网页正文解析失败：{exc}", warnings)
        content, method = parser.extracted_content()
        if len(content) < MIN_USEFUL_CHARACTERS:
            return _failed_response(
                response,
                "CONTENT_TOO_SHORT",
                f"网页可以访问，但只提取到 {len(content)} 个正文字符。",
                warnings,
                content=content,
                title=parser.title(),
                method=method,
            )
        return PageReadResult(
            ok=True,
            requested_url=response.requested_url,
            final_url=response.final_url,
            title=parser.title(),
            content_type=content_type,
            status_code=response.status_code,
            content=content,
            binary_content=None,
            binary_extension=None,
            byte_count=len(response.body),
            character_count=len(content),
            truncated=response.truncated,
            extraction_method=method,
            error_code=None,
            error=None,
            warnings=tuple(warnings),
        )
    if content_type.startswith("text/") or content_type in {"application/json", "application/xml"}:
        content = normalize_document(response.decode_text())
        if len(content) < MIN_USEFUL_CHARACTERS:
            return _failed_response(
                response,
                "CONTENT_TOO_SHORT",
                f"资源可以访问，但只读取到 {len(content)} 个文本字符。",
                warnings,
                content=content,
                method="plain-text",
            )
        return PageReadResult(
            ok=True,
            requested_url=response.requested_url,
            final_url=response.final_url,
            title=_title_from_url(response.final_url),
            content_type=content_type,
            status_code=response.status_code,
            content=content,
            binary_content=None,
            binary_extension=None,
            byte_count=len(response.body),
            character_count=len(content),
            truncated=response.truncated,
            extraction_method="plain-text",
            error_code=None,
            error=None,
            warnings=tuple(warnings),
        )
    if content_type == "application/pdf":
        warnings.append("PDF 原文件已保存，但此工具不从 PDF 中提取文字。")
        return PageReadResult(
            ok=True,
            requested_url=response.requested_url,
            final_url=response.final_url,
            title=_title_from_url(response.final_url),
            content_type=content_type,
            status_code=response.status_code,
            content="",
            binary_content=response.body,
            binary_extension=".pdf",
            byte_count=len(response.body),
            character_count=0,
            truncated=response.truncated,
            extraction_method="binary-pdf",
            error_code=None,
            error=None,
            warnings=tuple(warnings),
        )
    return _failed_response(
        response,
        "UNSUPPORTED_CONTENT_TYPE",
        f"暂不支持提取此资源类型：{content_type}",
        warnings,
    )


def normalize_inline(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_document(value: str) -> str:
    normalized = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    previous = ""
    blank = True
    for raw_line in normalized.splitlines():
        line = normalize_inline(raw_line)
        if not line:
            if not blank:
                lines.append("")
            blank = True
            continue
        if line == previous:
            continue
        lines.append(line)
        previous = line
        blank = False
    return "\n".join(lines).strip()


def _failed_response(
    response,
    code: str,
    message: str,
    warnings: list[str],
    *,
    content: str = "",
    title: str = "",
    method: str | None = None,
) -> PageReadResult:
    return PageReadResult(
        ok=False,
        requested_url=response.requested_url,
        final_url=response.final_url,
        title=title,
        content_type=response.content_type,
        status_code=response.status_code,
        content=content,
        binary_content=None,
        binary_extension=None,
        byte_count=len(response.body),
        character_count=len(content),
        truncated=response.truncated,
        extraction_method=method,
        error_code=code,
        error=message,
        warnings=tuple(warnings),
    )


def _title_from_url(url: str) -> str:
    parsed = urlsplit(url)
    name = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return name or parsed.hostname or url


def _follow_client_redirects(response, *, timeout_seconds: int, maximum: int = 3):
    redirects: list[str] = []
    current = response
    for _ in range(maximum):
        if current.content_type not in {"text/html", "application/xhtml+xml"}:
            break
        html = current.decode_text()
        if len(html) > 20_000:
            break
        target = _client_redirect_target(html, current.final_url)
        if not target or target == current.final_url:
            break
        current = fetch_url(
            target,
            timeout_seconds=timeout_seconds,
            max_bytes=MAX_PAGE_BYTES,
            validate_target=True,
        )
        redirects.append(current.final_url)
    return current, redirects


def _client_redirect_target(html: str, base_url: str) -> str:
    patterns = (
        r"window\.location\.replace\(\s*['\"]([^'\"]+)['\"]\s*\)",
        r"(?:window\.)?location\.href\s*=\s*['\"]([^'\"]+)['\"]",
        r"<meta[^>]+http-equiv\s*=\s*['\"]?refresh['\"]?[^>]+content\s*=\s*['\"][^'\"]*url\s*=\s*([^'\";>]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return urljoin(base_url, unescape(match.group(1).strip()))
    return ""


def _looks_blocked(html: str) -> bool:
    lowered = html.casefold()
    signals = (
        "verify you are a human",
        "checking your browser before accessing",
        "enable javascript and cookies to continue",
        "请输入验证码",
        "安全验证",
        "访问过于频繁",
    )
    return any(signal in lowered for signal in signals)


def _is_hidden(attrs: dict[str, str]) -> bool:
    if "hidden" in attrs or attrs.get("aria-hidden", "").casefold() == "true":
        return True
    style = attrs.get("style", "").replace(" ", "").casefold()
    return "display:none" in style or "visibility:hidden" in style


_SKIP_TAGS = frozenset(
    {
        "aside",
        "canvas",
        "dialog",
        "footer",
        "form",
        "iframe",
        "nav",
        "noscript",
        "script",
        "style",
        "svg",
        "template",
    }
)
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "li",
        "main",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
)
_HEADING_PREFIXES = {
    "h1": "# ",
    "h2": "## ",
    "h3": "### ",
    "h4": "#### ",
    "h5": "##### ",
    "h6": "###### ",
}
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
