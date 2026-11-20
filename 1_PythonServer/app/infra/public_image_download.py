"""Fetch a public image while pinning each connection to a checked address."""
import ipaddress
import socket
from urllib.parse import urldefrag, urljoin, urlsplit

import httpx


MAX_REMOTE_IMAGE_REDIRECTS = 4


class RemoteImageError(ValueError):
    pass


def download_public_image(client: httpx.Client, url: str, *, max_bytes: int) -> bytes:
    current_url = url
    for redirect_index in range(MAX_REMOTE_IMAGE_REDIRECTS + 1):
        url, address = _public_target(current_url)
        client.cookies.clear()
        with client.stream(
            "GET",
            url.copy_with(host=address),
            headers={"Accept": "image/*", "Host": url.netloc.decode("ascii"), "Connection": "close"},
            extensions={"sni_hostname": url.raw_host.decode("ascii")},
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
            if declared_size is not None and declared_size > max_bytes:
                raise RemoteImageError(f"网络图片超过 {max_bytes // (1024 * 1024)} MB 限制。")

            content = bytearray()
            for chunk in response.iter_bytes(chunk_size=64 * 1024):
                content.extend(chunk)
                if len(content) > max_bytes:
                    raise RemoteImageError(f"网络图片超过 {max_bytes // (1024 * 1024)} MB 限制。")
            if not content:
                raise RemoteImageError("网络图片内容为空。")
            return bytes(content)
    raise RemoteImageError("图片地址重定向次数过多。")


def _public_target(url: str) -> tuple[httpx.URL, str]:
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
        if not ip.is_global or ip.is_multicast:
            raise RemoteImageError("禁止访问本机、局域网或保留网络地址。")
    # Connect to the verified IP while preserving the original HTTP Host and TLS name.
    return httpx.URL(normalized_url), addresses[0][4][0]


def _parse_content_length(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None
