from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import ssl
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse


MINERU_RESULT_CDN_HOSTS = {"cdn-mineru.openxlab.org.cn"}
FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")
DNS_OVER_HTTPS_HOST = "dns.alidns.com"
DNS_OVER_HTTPS_PATH = "/resolve"


class ResultDownloadError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class ResolvedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, resolved_ip: str, *, port: int, timeout: int) -> None:
        self._resolved_ip = resolved_ip
        super().__init__(host, port=port, timeout=timeout, context=ssl.create_default_context())

    def connect(self) -> None:
        self.sock = self._create_connection(
            (self._resolved_ip, self.port),
            self.timeout,
            self.source_address,
        )
        if self._tunnel_host:
            self._tunnel()
        server_hostname = self._tunnel_host or self.host
        self.sock = self._context.wrap_socket(self.sock, server_hostname=server_hostname)


def hostname_uses_fake_ip(hostname: str, port: int) -> bool:
    try:
        addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except OSError:
        return False
    for address in addresses:
        raw_ip = str(address[4][0]).split("%", 1)[0]
        try:
            if ipaddress.ip_address(raw_ip) in FAKE_IP_NETWORK:
                return True
        except ValueError:
            continue
    return False


def resolve_public_ipv4_over_https(hostname: str, timeout: int) -> list[str]:
    query = urlencode({"name": hostname, "type": "A"})
    connection = http.client.HTTPSConnection(DNS_OVER_HTTPS_HOST, timeout=min(timeout, 30))
    try:
        connection.request(
            "GET",
            f"{DNS_OVER_HTTPS_PATH}?{query}",
            headers={"Accept": "application/dns-json", "User-Agent": "Tiance/1.0"},
        )
        response = connection.getresponse()
        try:
            if response.status != 200:
                raise OSError(f"加密 DNS 查询失败，HTTP {response.status}")
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        finally:
            response.close()
    finally:
        connection.close()

    answers = payload.get("Answer") if isinstance(payload, dict) else None
    resolved: list[str] = []
    if not isinstance(answers, list):
        return resolved
    for answer in answers:
        if not isinstance(answer, dict) or answer.get("type") != 1:
            continue
        raw_ip = str(answer.get("data") or "").strip()
        try:
            address = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue
        if address.version == 4 and address.is_global and raw_ip not in resolved:
            resolved.append(raw_ip)
    return resolved


def download_url_once(url: str, timeout: int, redirect_count: int, connect_ip: str | None = None) -> bytes:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ResultDownloadError("INVALID_DOWNLOAD_URL", "解析结果下载链接无效。", {"url": url})
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if parsed.scheme == "https" and connect_ip:
        connection: http.client.HTTPConnection = ResolvedHTTPSConnection(
            hostname,
            connect_ip,
            port=port,
            timeout=timeout,
        )
    else:
        connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        connection = connection_cls(hostname, port=port, timeout=timeout)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    try:
        connection.request("GET", path, headers={"User-Agent": "Tiance/1.0"})
        response = connection.getresponse()
        try:
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise ResultDownloadError(
                        "DOWNLOAD_REDIRECT_EMPTY",
                        f"下载结果时遇到空重定向，HTTP {response.status}。",
                    )
                return download_result_bytes(urljoin(url, location), timeout, redirect_count + 1)
            if response.status >= 400:
                raise ResultDownloadError(
                    "DOWNLOAD_FAILED",
                    f"下载结果失败，HTTP {response.status}。",
                    {"host": hostname},
                )
            return response.read()
        finally:
            response.close()
    finally:
        connection.close()


def download_via_public_dns(url: str, timeout: int, redirect_count: int) -> bytes:
    hostname = urlparse(url).hostname or ""
    resolved_ips = resolve_public_ipv4_over_https(hostname, timeout)
    if not resolved_ips:
        raise OSError("加密 DNS 未返回可用的公网 IPv4 地址")
    last_error: Exception | None = None
    for resolved_ip in resolved_ips:
        try:
            return download_url_once(url, timeout, redirect_count, connect_ip=resolved_ip)
        except ResultDownloadError:
            raise
        except Exception as exc:
            last_error = exc
    raise OSError(f"使用 {len(resolved_ips)} 个公网地址重试后仍然失败：{last_error}")


def download_result_bytes(url: str, timeout: int, redirect_count: int = 0) -> bytes:
    if redirect_count > 5:
        raise ResultDownloadError("DOWNLOAD_REDIRECT_LOOP", "下载结果时重定向次数过多。")
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ResultDownloadError("INVALID_DOWNLOAD_URL", "解析结果下载链接无效。", {"url": url})
    try:
        return download_url_once(url, timeout, redirect_count)
    except ResultDownloadError:
        raise
    except Exception as primary_error:
        is_official_cdn = hostname.lower().rstrip(".") in MINERU_RESULT_CDN_HOSTS
        port = parsed.port or 443
        if parsed.scheme == "https" and is_official_cdn and hostname_uses_fake_ip(hostname, port):
            try:
                return download_via_public_dns(url, timeout, redirect_count)
            except Exception as fallback_error:
                raise ResultDownloadError(
                    "DOWNLOAD_FAILED",
                    f"下载结果失败：{fallback_error}",
                    {
                        "host": hostname,
                        "fake_ip_detected": True,
                        "primary_error": str(primary_error),
                        "fallback_error": str(fallback_error),
                    },
                ) from fallback_error
        raise ResultDownloadError(
            "DOWNLOAD_FAILED",
            f"下载结果失败：{primary_error}",
            {"host": hostname, "fake_ip_detected": False},
        ) from primary_error
