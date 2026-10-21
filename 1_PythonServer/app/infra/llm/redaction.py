from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SENSITIVE_NAMES = frozenset({
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "x-goog-api-key",
    "api-key",
    "api_key",
    "apikey",
    "access_token",
    "token",
    "key",
    "cookie",
    "set-cookie",
})


def redact_url(url: str) -> str:
    """Sanitize a diagnostic URL without changing the actual upstream request."""
    parts = urlsplit(url)
    query = urlencode([
        (key, "[REDACTED]" if key.lower() in SENSITIVE_NAMES else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ])
    # Diagnostic URLs do not need embedded user names or passwords.
    netloc = parts.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))
