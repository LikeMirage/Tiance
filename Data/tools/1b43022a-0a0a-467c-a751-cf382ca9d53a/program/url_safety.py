from __future__ import annotations

from base64 import urlsafe_b64decode
import ipaddress
import socket
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_QUERY_KEYS = frozenset(
    {
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "ref_src",
        "spm",
        "utm_campaign",
        "utm_content",
        "utm_medium",
        "utm_source",
        "utm_term",
    }
)
BING_INTERNAL_HOSTS = frozenset({"bing.com", "www.bing.com", "cn.bing.com"})
PROXY_DNS_NETWORK = ipaddress.ip_network("198.18.0.0/15")


class UnsafeUrlError(ValueError):
    pass


def validate_public_url(url: str, *, resolve_dns: bool = True) -> str:
    text = str(url or "").strip()
    if not text:
        raise UnsafeUrlError("网址不能为空。")
    try:
        parsed = urlsplit(text)
    except ValueError as exc:
        raise UnsafeUrlError("网址格式无效。") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeUrlError("只允许访问 HTTP/HTTPS 网址。")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUrlError("网址不能包含用户名或密码。")
    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname:
        raise UnsafeUrlError("网址缺少有效域名。")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise UnsafeUrlError("不允许访问本机地址。")

    literal_ip = _parse_ip(hostname)
    if literal_ip is not None:
        _require_public_ip(literal_ip, allow_proxy_mapping=False)
    elif resolve_dns:
        _require_public_dns(hostname, parsed.port)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, ""))


def normalize_public_url(url: str, *, resolve_dns: bool = False) -> str:
    validated = validate_public_url(url, resolve_dns=resolve_dns)
    parsed = urlsplit(validated)
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    default_port = (parsed.scheme == "https" and port == 443) or (parsed.scheme == "http" and port == 80)
    host = hostname if default_port or port is None else f"{hostname}:{port}"
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in TRACKING_QUERY_KEYS
        ],
        doseq=True,
    )
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), host, path, query, ""))


def unwrap_bing_redirect(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return text
    hostname = (parsed.hostname or "").lower()
    if hostname not in BING_INTERNAL_HOSTS or parsed.path.casefold() not in {"/ck/a", "/aclick"}:
        return text
    values = parse_qs(parsed.query)
    for key in ("url", "r"):
        candidate = _first(values.get(key))
        if candidate.startswith(("http://", "https://")):
            return candidate
    encoded = _first(values.get("u"))
    if encoded.startswith("a1"):
        encoded = encoded[2:]
    if encoded:
        try:
            padding = "=" * (-len(encoded) % 4)
            decoded = urlsafe_b64decode(encoded + padding).decode("utf-8", errors="strict")
            if decoded.startswith(("http://", "https://")):
                return decoded
        except (ValueError, UnicodeDecodeError):
            pass
    return text


def is_bing_internal_result(url: str) -> bool:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return True
    hostname = (parsed.hostname or "").lower()
    if hostname not in BING_INTERNAL_HOSTS:
        return False
    return parsed.path.casefold().startswith(("/search", "/images", "/videos", "/news", "/maps"))


def _first(values: list[str] | None) -> str:
    return str(values[0]).strip() if values else ""


def _parse_ip(hostname: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(hostname)
    except ValueError:
        return None


def _require_public_dns(hostname: str, port: int | None) -> None:
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(hostname, port or 443, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"域名解析失败：{hostname}") from exc
    if not addresses:
        raise UnsafeUrlError(f"域名没有可用地址：{hostname}")
    for address in addresses:
        parsed = _parse_ip(address)
        if parsed is None:
            raise UnsafeUrlError(f"域名解析结果无效：{hostname}")
        _require_public_ip(parsed, allow_proxy_mapping=True)


def _require_public_ip(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    *,
    allow_proxy_mapping: bool,
) -> None:
    # 部分桌面/代理环境会把公网 DNS 映射到 RFC 2544 测试网段。
    # 仅允许域名解析结果使用该网段；用户直接填写该 IP 时仍然拒绝。
    is_proxy_mapping = (
        allow_proxy_mapping
        and isinstance(address, ipaddress.IPv4Address)
        and address in PROXY_DNS_NETWORK
    )
    if not address.is_global and not is_proxy_mapping:
        raise UnsafeUrlError(f"不允许访问非公网地址：{address}")
