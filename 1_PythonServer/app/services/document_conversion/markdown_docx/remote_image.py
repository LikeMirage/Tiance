from __future__ import annotations

import ipaddress
import socket
import warnings
from dataclasses import dataclass
from io import BytesIO
from urllib.parse import urldefrag, urljoin, urlsplit

import httpx
from PIL import Image, UnidentifiedImageError


MAX_REMOTE_IMAGE_BYTES = 10 * 1024 * 1024
MAX_REMOTE_IMAGE_PIXELS = 40_000_000
MAX_REMOTE_IMAGE_REDIRECTS = 4
MAX_REMOTE_IMAGES_PER_DOCUMENT = 100
MAX_REMOTE_IMAGE_TOTAL_BYTES = 50 * 1024 * 1024
_MAX_NORMALIZED_IMAGE_BYTES = 20 * 1024 * 1024
_WORD_NATIVE_IMAGE_FORMATS = {
    "BMP": ".bmp",
    "GIF": ".gif",
    "JPEG": ".jpg",
    "PNG": ".png",
    "TIFF": ".tiff",
}


class RemoteImageError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DownloadedImage:
    content: bytes
    suffix: str


class RemoteImageDownloader:
    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self._cache: dict[str, DownloadedImage] = {}
        self._total_bytes = 0
        self._transport = transport

    def download(self, url: str) -> DownloadedImage:
        normalized_url = _validate_public_http_url(url)
        cached = self._cache.get(normalized_url)
        if cached is not None:
            return cached
        if len(self._cache) >= MAX_REMOTE_IMAGES_PER_DOCUMENT:
            raise RemoteImageError("单份文档最多下载 100 张网络图片。")

        try:
            with httpx.Client(
                follow_redirects=False,
                timeout=httpx.Timeout(10.0, connect=5.0),
                transport=self._transport,
            ) as client:
                content = _download_with_redirects(client, normalized_url)
        except RemoteImageError:
            raise
        except httpx.HTTPError as exc:
            raise RemoteImageError(f"网络请求失败：{exc}") from exc

        downloaded = _validate_and_normalize_image(content)
        if self._total_bytes + len(downloaded.content) > MAX_REMOTE_IMAGE_TOTAL_BYTES:
            raise RemoteImageError("单份文档的网络图片总量超过 50 MB 限制。")
        self._cache[normalized_url] = downloaded
        self._total_bytes += len(downloaded.content)
        return downloaded


def is_remote_image_url(value: str) -> bool:
    return value.strip().lower().startswith(("http://", "https://"))


def remote_image_display_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        return "网络图片"
    if not host:
        return "网络图片"
    display_host = f"[{host}]" if ":" in host else host
    authority = f"{display_host}:{port}" if port is not None else display_host
    return f"{parsed.scheme.lower()}://{authority}{parsed.path or '/'}"


def _download_with_redirects(client: httpx.Client, url: str) -> bytes:
    current_url = url
    for redirect_index in range(MAX_REMOTE_IMAGE_REDIRECTS + 1):
        current_url = _validate_public_http_url(current_url)
        with client.stream(
            "GET",
            current_url,
            headers={"Accept": "image/*", "User-Agent": "Tiance-Document-Exporter/1.0"},
        ) as response:
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise RemoteImageError("图片地址返回了无目标的重定向。")
                if redirect_index >= MAX_REMOTE_IMAGE_REDIRECTS:
                    raise RemoteImageError("图片地址重定向次数过多。")
                current_url = urljoin(current_url, location)
                continue
            if response.status_code < 200 or response.status_code >= 300:
                raise RemoteImageError(f"图片服务器返回 HTTP {response.status_code}。")

            declared_size = _parse_content_length(response.headers.get("content-length"))
            if declared_size is not None and declared_size > MAX_REMOTE_IMAGE_BYTES:
                raise RemoteImageError("网络图片超过 10 MB 限制。")

            content = bytearray()
            for chunk in response.iter_bytes(chunk_size=64 * 1024):
                content.extend(chunk)
                if len(content) > MAX_REMOTE_IMAGE_BYTES:
                    raise RemoteImageError("网络图片超过 10 MB 限制。")
            if not content:
                raise RemoteImageError("网络图片内容为空。")
            return bytes(content)
    raise RemoteImageError("图片地址重定向次数过多。")


def _validate_public_http_url(url: str) -> str:
    normalized_url, _fragment = urldefrag(url.strip())
    try:
        parsed = urlsplit(normalized_url)
        port = parsed.port
    except ValueError as exc:
        raise RemoteImageError("网络图片地址无效。") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise RemoteImageError("网络图片只支持 HTTP 或 HTTPS 地址。")
    if parsed.username is not None or parsed.password is not None:
        raise RemoteImageError("网络图片地址不能包含账号信息。")

    effective_port = port or (443 if parsed.scheme.lower() == "https" else 80)
    try:
        addresses = socket.getaddrinfo(
            parsed.hostname,
            effective_port,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise RemoteImageError("无法解析网络图片地址。") from exc
    if not addresses:
        raise RemoteImageError("无法解析网络图片地址。")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address[4][0])
        except ValueError as exc:
            raise RemoteImageError("无法验证网络图片地址。") from exc
        if not ip.is_global:
            raise RemoteImageError("禁止访问本机、局域网或保留网络地址。")
    return normalized_url


def _validate_and_normalize_image(content: bytes) -> DownloadedImage:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                image_format = (image.format or "").upper()
                if image.width * image.height > MAX_REMOTE_IMAGE_PIXELS:
                    raise RemoteImageError("网络图片像素尺寸过大。")
                image.verify()
    except RemoteImageError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise RemoteImageError("网络图片像素尺寸过大。") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise RemoteImageError("下载内容不是有效图片。") from exc

    native_suffix = _WORD_NATIVE_IMAGE_FORMATS.get(image_format)
    if native_suffix is not None:
        return DownloadedImage(content=content, suffix=native_suffix)

    try:
        with Image.open(BytesIO(content)) as image:
            image.load()
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            normalized = image.convert("RGBA" if has_alpha else "RGB")
            output = BytesIO()
            normalized.save(output, format="PNG")
            normalized_content = output.getvalue()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise RemoteImageError("该网络图片格式无法转换为 Word 支持的格式。") from exc
    if len(normalized_content) > _MAX_NORMALIZED_IMAGE_BYTES:
        raise RemoteImageError("网络图片转换后超过 20 MB 限制。")
    return DownloadedImage(content=normalized_content, suffix=".png")


def _parse_content_length(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None
