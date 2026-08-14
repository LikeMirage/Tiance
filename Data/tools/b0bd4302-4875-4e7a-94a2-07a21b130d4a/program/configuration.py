from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
from urllib.parse import unquote, urlsplit

from dulwich.config import StackedConfig
from dulwich.repo import Repo


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GitIdentity:
    name: str
    email: str
    source: str

    @property
    def encoded(self) -> bytes:
        return f"{self.name} <{self.email}>".encode("utf-8")

    def public_dict(self) -> dict[str, str]:
        return {"name": self.name, "email": self.email, "source": self.source}


@dataclass(frozen=True, slots=True)
class GitCredential:
    username: str
    password: str
    source: str

    def porcelain_kwargs(self) -> dict[str, str]:
        return {"username": self.username, "password": self.password}


class ToolConfiguration:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError("program/config.json 不是有效的 JSON 配置。") from exc
        if not isinstance(payload, dict):
            raise ConfigurationError("program/config.json 必须是 JSON 对象。")
        return payload

    def save_identity(self, identity: GitIdentity) -> None:
        payload = self.load()
        payload["identity"] = {"name": identity.name, "email": identity.email}
        self._write(payload)

    def identity(self) -> GitIdentity | None:
        value = self.load().get("identity")
        if not isinstance(value, dict):
            return None
        return _identity_from_values(value.get("name"), value.get("email"), "tool_config")

    def credential_for(self, remote_url: str) -> GitCredential | None:
        host = remote_host(remote_url)
        if not host:
            return None
        values = self.load().get("https_credentials")
        if not isinstance(values, list):
            return None
        for value in values:
            if not isinstance(value, dict):
                continue
            configured_host = str(value.get("host") or "").strip().casefold()
            if configured_host != host.casefold():
                continue
            token = str(value.get("token") or "").strip()
            if not token:
                continue
            username = str(value.get("username") or "oauth2").strip() or "oauth2"
            return GitCredential(username=username, password=token, source="tool_config")
        return None

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


def resolve_identity(
    repo: Repo | None,
    tool_config: ToolConfiguration,
    *,
    author_name: object = None,
    author_email: object = None,
) -> tuple[GitIdentity | None, list[dict[str, str]]]:
    explicit_name = str(author_name or "").strip()
    explicit_email = str(author_email or "").strip()
    if bool(explicit_name) != bool(explicit_email):
        raise ConfigurationError("author_name 和 author_email 必须同时提供。")

    candidates: list[GitIdentity] = []
    if explicit_name and explicit_email:
        candidates.append(_required_identity(explicit_name, explicit_email, "operation"))
    if repo is not None:
        candidate = _identity_from_config(repo.get_config(), "repository")
        if candidate is not None:
            candidates.append(candidate)
    candidate = tool_config.identity()
    if candidate is not None:
        candidates.append(candidate)
    candidate = _global_identity()
    if candidate is not None:
        candidates.append(candidate)

    unique: list[GitIdentity] = []
    seen: set[tuple[str, str, str]] = set()
    for candidate in candidates:
        key = (candidate.name, candidate.email, candidate.source)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    selected = unique[0] if unique else None
    return selected, [item.public_dict() for item in unique]


def configure_repository_identity(repo: Repo, identity: GitIdentity) -> None:
    config = repo.get_config()
    config.set((b"user",), b"name", identity.name.encode("utf-8"))
    config.set((b"user",), b"email", identity.email.encode("utf-8"))
    config.write_to_path()


def validate_identity(name: object, email: object, source: str = "operation") -> GitIdentity:
    normalized_name = str(name or "").strip()
    normalized_email = str(email or "").strip()
    if not normalized_name or not normalized_email:
        raise ConfigurationError("Git 作者姓名和邮箱不能为空。")
    return _required_identity(normalized_name, normalized_email, source)


def resolve_credential(
    remote_url: str,
    tool_config: ToolConfiguration,
) -> GitCredential | None:
    embedded = credential_from_url(remote_url)
    if embedded is not None:
        return embedded

    configured = tool_config.credential_for(remote_url)
    if configured is not None:
        return configured

    token = os.environ.get("TIANCE_GIT_TOKEN", "").strip()
    if token and remote_host(remote_url):
        username = os.environ.get("TIANCE_GIT_USERNAME", "oauth2").strip() or "oauth2"
        return GitCredential(username=username, password=token, source="environment")

    return _credential_from_system_helper(remote_url)


def authentication_summary(
    remote_url: str,
    tool_config: ToolConfiguration,
) -> dict[str, Any]:
    scheme = remote_scheme(remote_url)
    if scheme == "ssh":
        executable = shutil.which("ssh")
        return {
            "kind": "ssh",
            "available": executable is not None,
            "source": "system_ssh" if executable else None,
        }
    if scheme in {"file", "local"}:
        return {"kind": "local", "available": True, "source": "local_path"}
    credential = resolve_credential(remote_url, tool_config)
    return {
        "kind": "https",
        "available": credential is not None,
        "source": credential.source if credential else None,
    }


def remote_scheme(remote_url: str) -> str:
    value = remote_url.strip()
    if _looks_like_scp_url(value) or value.startswith("ssh://"):
        return "ssh"
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"}:
        return "https"
    if parsed.scheme == "file":
        return "file"
    return "local"


def remote_host(remote_url: str) -> str | None:
    value = remote_url.strip()
    if _looks_like_scp_url(value):
        return value.split("@", 1)[-1].split(":", 1)[0].strip() or None
    parsed = urlsplit(value)
    return parsed.hostname


def redact_remote_url(remote_url: str) -> str:
    value = remote_url.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return value
    host = parsed.hostname
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return parsed._replace(netloc=host).geturl()


def credential_from_url(remote_url: str) -> GitCredential | None:
    parsed = urlsplit(remote_url.strip())
    if parsed.scheme not in {"http", "https"} or parsed.username is None:
        return None
    username = unquote(parsed.username)
    password = unquote(parsed.password or "")
    if not username or not password:
        return None
    return GitCredential(username=username, password=password, source="remote_url")


def _credential_from_system_helper(remote_url: str) -> GitCredential | None:
    parsed = urlsplit(remote_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    git_executable = shutil.which("git")
    if not git_executable:
        return None
    request = f"protocol={parsed.scheme}\nhost={parsed.hostname}\npath={parsed.path.lstrip('/')}\n\n"
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GCM_INTERACTIVE"] = "Never"
    try:
        completed = subprocess.run(
            [git_executable, "credential", "fill"],
            input=request,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    values: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip()
    username = values.get("username", "")
    password = values.get("password", "")
    if not username or not password:
        return None
    return GitCredential(username=username, password=password, source="system_credential_helper")


def _global_identity() -> GitIdentity | None:
    try:
        return _identity_from_config(StackedConfig.default(), "global_git_config")
    except (OSError, ValueError):
        return None


def _identity_from_config(config: Any, source: str) -> GitIdentity | None:
    try:
        name = config.get((b"user",), b"name").decode("utf-8")
        email = config.get((b"user",), b"email").decode("utf-8")
    except (KeyError, UnicodeDecodeError, AttributeError):
        return None
    return _identity_from_values(name, email, source)


def _identity_from_values(name: object, email: object, source: str) -> GitIdentity | None:
    normalized_name = str(name or "").strip()
    normalized_email = str(email or "").strip()
    if not normalized_name or not normalized_email:
        return None
    return _required_identity(normalized_name, normalized_email, source)


def _required_identity(name: str, email: str, source: str) -> GitIdentity:
    if "\n" in name or "\r" in name or "<" in name or ">" in name:
        raise ConfigurationError("Git 作者姓名包含无效字符。")
    if "\n" in email or "\r" in email or "<" in email or ">" in email or "@" not in email:
        raise ConfigurationError("Git 作者邮箱无效。")
    return GitIdentity(name=name, email=email, source=source)


def _looks_like_scp_url(value: str) -> bool:
    return ":" in value and "@" in value.split(":", 1)[0] and "://" not in value
