from __future__ import annotations

from dataclasses import dataclass
from email.message import Message
import gzip
from io import BytesIO
import re
import zlib
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from url_safety import UnsafeUrlError, validate_public_url


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
)
DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9,*/*;q=0.5",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Accept-Encoding": "gzip, deflate",
    "User-Agent": USER_AGENT,
}
META_CHARSET_PATTERN = re.compile(
    br"<meta[^>]+charset\s*=\s*[\"']?\s*([a-zA-Z0-9._-]+)",
    flags=re.IGNORECASE,
)


class HttpFetchError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class FetchResult:
    requested_url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    content_type: str
    body: bytes
    truncated: bool

    def decode_text(self) -> str:
        charset = _charset_from_headers(self.headers) or _charset_from_meta(self.body) or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


class SafeRedirectHandler(HTTPRedirectHandler):
    max_repeats = 3
    max_redirections = 8

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(newurl, resolve_dns=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_url(
    url: str,
    *,
    timeout_seconds: int = 20,
    max_bytes: int = 5_000_000,
    validate_target: bool = True,
) -> FetchResult:
    try:
        requested_url = validate_public_url(url, resolve_dns=True) if validate_target else url
    except UnsafeUrlError as exc:
        raise HttpFetchError("UNSAFE_URL", str(exc)) from exc
    request = Request(requested_url, headers=DEFAULT_HEADERS, method="GET")
    opener = build_opener(SafeRedirectHandler())
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            final_url = response.geturl()
            if validate_target:
                validate_public_url(final_url, resolve_dns=True)
            body = response.read(max_bytes + 1)
            truncated = len(body) > max_bytes
            if truncated:
                body = body[:max_bytes]
            headers = {key.lower(): value for key, value in response.headers.items()}
            body, decompressed_truncated = _decompress_body(
                body,
                headers.get("content-encoding", ""),
                max_bytes=max_bytes,
            )
            truncated = truncated or decompressed_truncated
            return FetchResult(
                requested_url=requested_url,
                final_url=final_url,
                status_code=int(response.status),
                headers=headers,
                content_type=_content_type(response.headers),
                body=body,
                truncated=truncated,
            )
    except HttpFetchError:
        raise
    except UnsafeUrlError as exc:
        raise HttpFetchError("UNSAFE_REDIRECT", str(exc)) from exc
    except HTTPError as exc:
        raise HttpFetchError(
            "HTTP_ERROR",
            f"HTTP {exc.code}：{exc.reason}",
            status_code=int(exc.code),
        ) from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise HttpFetchError("REQUEST_FAILED", f"网络请求失败：{reason}") from exc
    except TimeoutError as exc:
        raise HttpFetchError("REQUEST_TIMEOUT", "网络请求超时。") from exc
    except OSError as exc:
        raise HttpFetchError("REQUEST_FAILED", f"网络请求失败：{exc}") from exc


def _content_type(headers: Message) -> str:
    return str(headers.get_content_type() or "application/octet-stream").casefold()


def _charset_from_headers(headers: dict[str, str]) -> str | None:
    content_type = headers.get("content-type", "")
    match = re.search(r"charset\s*=\s*[\"']?([^;\s\"']+)", content_type, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def _charset_from_meta(body: bytes) -> str | None:
    match = META_CHARSET_PATTERN.search(body[:8192])
    return match.group(1).decode("ascii", errors="ignore") if match else None


def _decompress_body(body: bytes, content_encoding: str, *, max_bytes: int) -> tuple[bytes, bool]:
    encoding = content_encoding.strip().casefold()
    if not encoding or encoding == "identity":
        return body, False
    try:
        if encoding == "gzip":
            with gzip.GzipFile(fileobj=BytesIO(body)) as stream:
                decoded = stream.read(max_bytes + 1)
        elif encoding == "deflate":
            decoder = zlib.decompressobj()
            decoded = decoder.decompress(body, max_bytes + 1)
        else:
            raise HttpFetchError("UNSUPPORTED_ENCODING", f"网页使用了不支持的压缩格式：{encoding}")
    except (OSError, EOFError, zlib.error) as exc:
        raise HttpFetchError("INVALID_COMPRESSED_RESPONSE", "网页压缩内容无法解码。") from exc
    truncated = len(decoded) > max_bytes
    return decoded[:max_bytes], truncated
