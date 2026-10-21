from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
from uuid import uuid4

from deepseek_config import ToolError


class ResultStorage:
    def __init__(self, limits: dict):
        self.field_limit = limits["inline_field_chars"]
        self.remaining = limits["inline_text_budget"]
        self.directory: Path | None = None
        self.root = Path(os.environ.get("TIANCE_WORKSPACE_ROOT") or os.getcwd()).resolve()
        self.file_count = 0

    def _directory(self) -> Path:
        if self.directory is None:
            directory = (self.root / "web_searches" / (
                "deepseek_" + datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex
            )).resolve()
            if not directory.is_relative_to(self.root):
                raise ToolError("RESULT_SAVE_FAILED", "搜索结果目录必须位于当前工作区内。")
            directory.mkdir(parents=True, exist_ok=False)
            self.directory = directory
        return self.directory

    def write(self, name: str, text: str) -> dict:
        path = self._directory() / name
        content = text.encode("utf-8")
        path.write_bytes(content)
        return {
            "path": path.relative_to(self.root).as_posix(),
            "size_bytes": len(content), "character_count": len(text),
            "line_count": len(text.splitlines()),
        }

    def render(self, row: dict, index: int) -> dict:
        result = dict(row)
        files = {}
        for field in ("snippet", "summary", "content"):
            text = row.get(field)
            if not isinstance(text, str):
                continue
            if len(text) <= min(self.field_limit, self.remaining):
                self.remaining -= len(text)
            else:
                files[field] = self.write(f"{index:03d}-{field}.txt", text)
                self.file_count += 1
                del result[field]
        if files:
            result["text_files"] = files
        return result


def format_results(action: str, request: dict, response: dict, limits: dict, source: str) -> dict:
    if action == "search":
        rows = response.get("results")
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or any(not isinstance(row.get(key), str)
                                           for key in ("title", "url", "snippet", "summary", "content"))
            for row in rows
        ):
            raise ToolError("DEEPSEEK_INVALID_RESPONSE", "DeepSeek 搜索响应缺少有效的 results 数组或文本字段。")
    else:
        if any(not isinstance(response.get(key), str) for key in ("title", "content")):
            raise ToolError("DEEPSEEK_INVALID_RESPONSE", "DeepSeek 网页响应缺少 title 或 content。")
        if not response["content"]:
            raise ToolError("DEEPSEEK_EMPTY_CONTENT", "DeepSeek 没有返回网页正文。")
        rows = [{**response, "url": request["url"]}]
    store = ResultStorage(limits)
    data = {"action": action, "key_source": source, "request": request}
    try:
        rendered = [store.render(row, i) for i, row in enumerate(rows, 1)]
        if action == "search":
            data.update(result_count=len(rendered), results=rendered)
        else:
            data["page"] = rendered[0]
        data["saved_text_file_count"] = store.file_count
        if store.file_count:
            data["index_file"] = store.write("index.json", json.dumps(data, ensure_ascii=False, indent=2))
    except OSError as exc:
        raise ToolError("RESULT_SAVE_FAILED", "无法完整保存搜索结果。", {
            "directory": str(store.directory) if store.directory else None,
        }) from exc
    return data