from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.infra.secrets import decrypt_secret, encrypt_secret


@dataclass(frozen=True, slots=True)
class GithubCredentials:
    access_token: str
    access_expires_at: datetime | None
    refresh_token: str | None
    refresh_expires_at: datetime | None


class GithubAuthRepository:
    def __init__(self, credentials_path: Path) -> None:
        self._credentials_path = credentials_path

    def read(self) -> GithubCredentials | None:
        try:
            payload = json.loads(self._credentials_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None
        if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
            return None
        access_ciphertext = payload.get("accessTokenCiphertext")
        if not isinstance(access_ciphertext, str) or not access_ciphertext:
            return None
        refresh_ciphertext = payload.get("refreshTokenCiphertext")
        try:
            return GithubCredentials(
                access_token=decrypt_secret(access_ciphertext),
                access_expires_at=_parse_datetime(payload.get("accessExpiresAt")),
                refresh_token=(
                    decrypt_secret(refresh_ciphertext)
                    if isinstance(refresh_ciphertext, str) and refresh_ciphertext
                    else None
                ),
                refresh_expires_at=_parse_datetime(payload.get("refreshExpiresAt")),
            )
        except (RuntimeError, ValueError):
            return None

    def save(self, credentials: GithubCredentials) -> None:
        access_ciphertext = encrypt_secret(credentials.access_token)
        refresh_ciphertext = (
            encrypt_secret(credentials.refresh_token)
            if credentials.refresh_token
            else None
        )
        if not access_ciphertext or (credentials.refresh_token and not refresh_ciphertext):
            raise RuntimeError("GitHub 登录凭据无法安全保存。")
        payload = {
            "schemaVersion": 1,
            "accessTokenCiphertext": access_ciphertext,
            "accessExpiresAt": _format_datetime(credentials.access_expires_at),
            "refreshTokenCiphertext": refresh_ciphertext,
            "refreshExpiresAt": _format_datetime(credentials.refresh_expires_at),
        }
        self._credentials_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._credentials_path.with_name(
            f".{self._credentials_path.name}.{uuid4().hex}.tmp"
        )
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            atomic_replace_path(temporary, self._credentials_path)
        finally:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)

    def delete(self) -> None:
        with suppress(OSError):
            self._credentials_path.unlink(missing_ok=True)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
