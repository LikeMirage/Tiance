"""Protocol port from xifan2333/jianying-subtitle; see NOTICE and LICENSE."""
from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from datetime import datetime, timezone

APP_VERSION = "6.6.0"
UA_SIGN = "Cronet/TTNetVersion:d4572e53 2024-06-12 QuicVersion:4bf243e0 2023-04-17"


def device_id() -> str:
    digit = datetime.now().year % 10
    suffix = "3278516897751" if digit % 2 else str(uuid.getnode()).zfill(13)
    return f"{390 + digit}{suffix}"


def api_headers(path: str, tdid: str, timestamp: int | None = None) -> dict[str, str]:
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    raw = f"9e2c|{path[-7:]}|4|{APP_VERSION}|{stamp}|{tdid}|11ac"
    return {
        "User-Agent": UA_SIGN, "appvr": APP_VERSION, "device-time": stamp,
        "pf": "4", "sign": hashlib.md5(raw.encode()).hexdigest(),
        "sign-ver": "1", "tdid": tdid, "Content-Type": "application/json",
    }


def vod_headers(access: str, secret: str, token: str, query: str,
                timestamp: str | None = None) -> dict[str, str]:
    stamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    headers = {"x-amz-date": stamp, "x-amz-security-token": token}
    canonical = "\n".join([
        "GET", "/", query,
        "".join(f"{k}:{v}\n" for k, v in headers.items()),
        ";".join(headers), hashlib.sha256(b"").hexdigest(),
    ])
    scope = f"{stamp[:8]}/cn/vod/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", stamp, scope,
                         hashlib.sha256(canonical.encode()).hexdigest()])
    key = ("AWS4" + secret).encode()
    for value in (stamp[:8], "cn", "vod", "aws4_request"):
        key = hmac.new(key, value.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    headers["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access}/{scope}, "
        f"SignedHeaders=x-amz-date;x-amz-security-token, Signature={signature}"
    )
    return headers
