from __future__ import annotations

from json import loads
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOLS_ROOT = PROJECT_ROOT / "Data" / "tools"


def resolve_formal_tool_root(tool_name: str) -> Path:
    matches: list[Path] = []
    for manifest_path in TOOLS_ROOT.glob("*/.tool/tool.json"):
        payload = loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("name") == tool_name:
            matches.append(manifest_path.parents[1])

    if len(matches) != 1:
        raise RuntimeError(
            f"工具调用名称 {tool_name!r} 应唯一对应一个正式工具项目，实际找到 {len(matches)} 个。"
        )
    return matches[0]
