from __future__ import annotations

import json
from pathlib import Path
import tempfile


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


def default_config() -> dict:
    return {
        "deepseek": {"api_key": ""},
        "output": {"inline_field_chars": 4000, "inline_text_budget": 12000},
    }


def load_config(path: Path) -> dict:
    if not path.exists():
        return default_config()
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ToolError("CONFIG_INVALID", "config.json 无法读取或不是有效 JSON。", {"config_path": str(path)}) from exc
    if not isinstance(value, dict) or set(value) - {"deepseek", "output"}:
        raise ToolError("CONFIG_INVALID", "config.json 只支持 deepseek 和 output 配置。")
    deepseek, output = value.get("deepseek", {}), value.get("output", {})
    if not isinstance(deepseek, dict) or set(deepseek) - {"api_key"}:
        raise ToolError("CONFIG_INVALID", "deepseek 配置只支持 api_key。")
    key = deepseek.get("api_key", "")
    if not isinstance(key, str):
        raise ToolError("CONFIG_INVALID", "deepseek.api_key 必须是字符串，未配置时留空。")
    defaults = default_config()["output"]
    if not isinstance(output, dict) or set(output) - set(defaults):
        raise ToolError("CONFIG_INVALID", "output 配置只支持 inline_field_chars 和 inline_text_budget。")
    for name, fallback in defaults.items():
        number = output.get(name, fallback)
        if type(number) is not int or number < 0:
            raise ToolError("CONFIG_INVALID", f"output.{name} 必须是非负整数。")
        defaults[name] = number
    return {"deepseek": {"api_key": key.strip()}, "output": defaults}


def configure_key(path: Path, key: str) -> None:
    config = load_config(path)
    config["deepseek"]["api_key"] = key.strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="config.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(config, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temporary.replace(path)
    except OSError as exc:
        raise ToolError("CONFIG_WRITE_FAILED", "无法保存 config.json。", {"config_path": str(path)}) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def config_info(path: Path, config: dict) -> dict:
    return {
        "config_path": str(path.resolve()),
        "config_key_configured": bool(config["deepseek"]["api_key"]),
        "key_priority": ["config.json:deepseek.api_key", "模型集:DeepSeek"],
        "output": config["output"],
        "configuration_steps": [
            "在模型集的 DeepSeek 供应商中配置官方 API Key，或调用 action=configure 并传入 api_key。",
            "config.json 中的 Key 优先；api_key 设为空字符串后，搜索时通过能力桥使用模型集的 Key。",
        ],
    }