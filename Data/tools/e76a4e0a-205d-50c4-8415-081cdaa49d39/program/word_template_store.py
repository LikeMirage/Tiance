from __future__ import annotations

import json
import os
import time
from pathlib import Path
from uuid import uuid4

from word_template_model import WordTemplateProfile, load_template_profile


class WordTemplateStore:
    def __init__(self, templates_dir: Path) -> None:
        self._templates_dir = templates_dir

    def list_templates(self) -> list[dict[str, object]]:
        templates: list[dict[str, object]] = [
            {
                "template_id": "builtin-default",
                "name": "内置默认样式",
                "source_file_name": "",
                "created_at": "",
                "builtin": True,
            }
        ]
        if not self._templates_dir.is_dir():
            return templates

        entries: list[dict[str, object]] = []
        for path in self._templates_dir.glob("*.json"):
            try:
                profile = self._load_path(path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"模板文件损坏：{path.name}，原因：{exc}") from exc
            entries.append(
                {
                    "template_id": profile.template_id,
                    "name": profile.name,
                    "source_file_name": profile.source_file_name,
                    "created_at": profile.created_at,
                    "builtin": False,
                }
            )
        entries.sort(key=lambda item: (str(item["name"]).casefold(), str(item["template_id"])))
        return templates + entries

    def load(self, template_id: str) -> WordTemplateProfile:
        if template_id == "builtin-default":
            raise ValueError("内置默认样式不需要指定 template_id。")
        path = self._template_path(template_id)
        if not path.is_file():
            raise ValueError(f"模板不存在：{template_id}。")
        return self._load_path(path)

    def json_path(self, template_id: str) -> Path:
        return self._template_path(template_id)

    def save(self, payload: dict[str, object]) -> WordTemplateProfile:
        profile = load_template_profile(payload)
        self._ensure_name_available(profile.name)
        self._templates_dir.mkdir(parents=True, exist_ok=True)
        path = self._template_path(profile.template_id)
        if path.exists():
            raise ValueError(f"模板 ID 已存在：{profile.template_id}。")
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        _write_atomically(path, serialized)
        return profile

    def _ensure_name_available(self, name: str) -> None:
        normalized = name.strip().casefold()
        if normalized == "内置默认样式".casefold():
            raise ValueError("模板名称不能与内置默认样式相同。")
        for item in self.list_templates():
            if bool(item["builtin"]):
                continue
            if str(item["name"]).strip().casefold() == normalized:
                raise ValueError(f"模板名称已存在：{name}。")

    def _load_path(self, path: Path) -> WordTemplateProfile:
        payload = json.loads(path.read_text(encoding="utf-8"))
        profile = load_template_profile(payload)
        if path.stem != profile.template_id:
            raise ValueError("模板文件名与 template_id 不一致。")
        return profile

    def _template_path(self, template_id: str) -> Path:
        normalized = template_id.strip().lower()
        if (
            len(normalized) != 32
            or any(character not in "0123456789abcdef" for character in normalized)
        ):
            raise ValueError("template_id 必须是模板列表返回的 32 位标识。")
        return self._templates_dir / f"{normalized}.json"


def _write_atomically(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        _replace_with_short_retry(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _replace_with_short_retry(source: Path, destination: Path) -> None:
    delays = (0.0, 0.03, 0.08, 0.16)
    for attempt, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        try:
            os.replace(source, destination)
            return
        except OSError as exc:
            transient_windows_error = (
                os.name == "nt" and getattr(exc, "winerror", None) in {5, 32, 33}
            )
            if not transient_windows_error or attempt == len(delays) - 1:
                raise
