from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlsplit, urlunsplit

from app.core.errors import BadRequestError

_ALLOWED_API_SCHEMES = frozenset(("http", "https"))
_LOCAL_HOSTNAMES = frozenset(("localhost",))
_LOOPBACK_HOSTNAME_SUFFIXES = (".localhost",)


def normalize_provider_api_base_url(value: str | None) -> str:
    raw_url = (value or "").strip()
    if not raw_url:
        raise BadRequestError("Provider API URL is required.")

    parsed = urlsplit(raw_url)
    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_API_SCHEMES:
        raise BadRequestError("Provider API URL must use http or https.")
    if not parsed.netloc or not parsed.hostname:
        raise BadRequestError("Provider API URL must include a host.")
    if parsed.username or parsed.password:
        raise BadRequestError("Provider API URL must not include credentials.")
    if parsed.query or parsed.fragment:
        raise BadRequestError("Provider API URL must not include query or fragment.")
    if not parsed.path.strip("/"):
        raise BadRequestError("Provider API URL must include the complete endpoint path.")

    try:
        parsed.port
    except ValueError as exc:
        raise BadRequestError("Provider API URL port is invalid.") from exc

    _validate_allowed_host(parsed.hostname)

    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


def _validate_allowed_host(hostname: str) -> None:
    normalized_host = hostname.strip().strip("[]").rstrip(".").lower()
    if normalized_host in _LOCAL_HOSTNAMES or normalized_host.endswith(
        _LOOPBACK_HOSTNAME_SUFFIXES
    ):
        return
    try:
        parsed_ip = ip_address(normalized_host)
    except ValueError:
        return

    if parsed_ip.is_loopback:
        return
    if parsed_ip.is_unspecified or parsed_ip.is_multicast or parsed_ip.is_reserved:
        raise BadRequestError("Provider API URL points to an unusable network address.")
