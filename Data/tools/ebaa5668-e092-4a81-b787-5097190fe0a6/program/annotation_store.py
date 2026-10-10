"""Project-local annotations over retained GUI frames; no application internals."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator
from PIL import Image, ImageColor, ImageDraw, ImageFont


class AnnotationError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code, self.details = code, details or {}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AnnotationError("ANNOTATION_DATA_UNAVAILABLE", f"无法读取数据：{path.name}") from exc
    if not isinstance(value, dict):
        raise AnnotationError("ANNOTATION_DATA_INVALID", "数据必须是对象。")
    return value


def package_version() -> str:
    return str(read_json(Path(__file__).resolve().parents[1] / "manifest.json")["version"])


@lru_cache(maxsize=1)
def validator() -> Draft202012Validator:
    schema = read_json(Path(__file__).resolve().parents[1] / ".tool/input.schema.json")
    return Draft202012Validator(schema)


def validate(payload: dict) -> None:
    errors = list(validator().iter_errors(payload))
    if errors:
        raise AnnotationError("INVALID_ARGUMENT", errors[0].message)


def color(value: str) -> str:
    try:
        red, green, blue = ImageColor.getrgb(value)
    except (ValueError, TypeError) as exc:
        raise AnnotationError("INVALID_ARGUMENT", "颜色须为有效颜色名或#RRGGBB。") from exc
    return f"#{red:02X}{green:02X}{blue:02X}"


@lru_cache(maxsize=64)
def font(size: int):
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(str(fonts / name), size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def render(rect: dict, items: list[dict]) -> Image.Image:
    """Both previews and the native layer use physical screen pixels."""
    width, height = rect["width"], rect["height"]
    if width <= 0 or height <= 0 or width * height > 64_000_000:
        raise AnnotationError("DISPLAY_TOO_LARGE", "标注画布尺寸无效或超过6400万像素。")
    image = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(image)
    left, top = rect["left"], rect["top"]
    for item in items:
        ink = item["color"]
        size = item["size_px"]
        geometry = item["geometry"]
        if item["type"] == "grid":
            for box in geometry["rects"]:
                x, y = box["left"] - left, box["top"] - top
                draw.rectangle((x, y, x + box["width"] - 1, y + box["height"] - 1), outline=ink, width=size)
        elif item["type"] == "arrow":
            tail, head = geometry["tail"], geometry["head"]
            tx, ty, hx, hy = tail["x"] - left, tail["y"] - top, head["x"] - left, head["y"] - top
            length = math.hypot(hx - tx, hy - ty)
            if length == 0:
                continue
            ux, uy = (hx - tx) / length, (hy - ty) / length
            head_length = min(size * 4, length * 0.6)
            half_width = min(size * 2, head_length / 2)
            bx, by = hx - ux * head_length, hy - uy * head_length
            draw.line((tx, ty, bx, by), fill=ink, width=size)
            draw.polygon([(hx, hy), (bx - uy * half_width, by + ux * half_width),
                          (bx + uy * half_width, by - ux * half_width)], fill=ink)
        else:
            position = geometry["position"]
            face = font(size)
            ascent, descent = face.getmetrics()
            line_height = ascent + descent + max(2, size // 5)
            for index, line in enumerate(item["text"].replace("\r\n", "\n").replace("\r", "\n").split("\n")):
                draw.text((position["x"] - left, position["y"] - top + index * line_height), line,
                          font=face, fill=ink, anchor="lt")
    return image


class AnnotationStore:
    def __init__(self, workspace: Path, project_id: str):
        self.root = (workspace / ".Tiance/gui-temp").resolve()
        self.project_id = project_id

    def folder(self, gui_id: str) -> Path:
        if not re.fullmatch(r"gui_[a-f0-9]{32}", gui_id):
            raise AnnotationError("GUI_SESSION_INVALID", "GUI会话编号无效。")
        folder = (self.root / gui_id).resolve()
        if folder.parent != self.root:
            raise AnnotationError("GUI_SESSION_INVALID", "GUI数据目录越界。")
        return folder

    def gui(self, gui_id: str) -> dict:
        value = read_json(self.folder(gui_id) / "session.json")
        if value.get("gui_session_id") != gui_id or value.get("project_id") != self.project_id:
            raise AnnotationError("GUI_SESSION_OWNER_MISMATCH", "截图不属于当前项目。")
        return value

    def source(self, gui_id: str, frame_id: int, view_id: str) -> tuple[dict, dict]:
        gui = self.gui(gui_id)
        frame = next((f for f in gui.get("frames", []) if f["frame_id"] == frame_id), None)
        if frame is None or view_id not in frame.get("views", {}):
            raise AnnotationError("GUI_VIEW_NOT_FOUND", "保存的Frame或View不存在。")
        return frame, frame["views"][view_id]

    def load(self, gui_id: str) -> dict:
        self.gui(gui_id)
        path = self.folder(gui_id) / "annotations.json"
        if not path.exists():
            return {"schema_version": 1, "project_id": self.project_id, "gui_session_id": gui_id,
                    "display_open": False, "annotations": [], "updated_at": now()}
        state = read_json(path)
        if state.get("schema_version") != 1 or state.get("project_id") != self.project_id or state.get("gui_session_id") != gui_id:
            raise AnnotationError("ANNOTATION_OWNER_MISMATCH", "标注数据归属或版本无效。")
        return state

    def groups(self, gui_id: str | None = None) -> list[dict]:
        if gui_id:
            return [self.load(gui_id)]
        states = []
        for path in sorted(self.root.glob("gui_*/annotations.json")):
            states.append(self.load(path.parent.name))
        return states

    def save(self, state: dict) -> None:
        state["updated_at"] = now()
        if len(json.dumps(state, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 1_500_000:
            raise AnnotationError("ANNOTATION_LIMIT", "该组标注超过1.5MB，请减少文字或标注数量。")
        atomic_json(self.folder(state["gui_session_id"]) / "annotations.json", state)

    @staticmethod
    def cell(view: dict, cell_id: int) -> dict:
        cell = next((cell for cell in view["cells"] if cell["cell_id"] == cell_id), None)
        if cell is None:
            raise AnnotationError("GUI_CELL_NOT_FOUND", f"来源View没有网格{cell_id}。")
        return cell

    def point(self, gui_id: str, frame_id: int, view_id: str, point: dict) -> dict:
        _, view = self.source(gui_id, frame_id, point.get("view_id", view_id))
        rect = self.cell(view, point["cell_id"])["rect_absolute"]
        return {"x": rect["left"] + round(point["x"] * (rect["width"] - 1)),
                "y": rect["top"] + round((1 - point["y"]) * (rect["height"] - 1))}

    def make(self, gui_id: str, frame_id: int, view_id: str, specification: dict, annotation_id: str | None = None) -> dict:
        frame, view = self.source(gui_id, frame_id, view_id)
        kind = specification["type"]
        rect = frame["capture_rect"]
        scale = min(rect["width"], rect["height"])
        requested_size = specification.get("size", "auto")
        size = (max(14, min(36, round(scale / 45))) if kind == "text" else max(2, min(8, round(scale / 300)))) if requested_size == "auto" else round(requested_size)
        spec = {**deepcopy(specification), "color": color(specification.get("color", "red")), "size": requested_size}
        if kind == "grid":
            cells = [self.cell(view, cell_id) for cell_id in spec["cell_ids"]]
            rows = [cell["row"] for cell in cells]
            columns = [cell["column"] for cell in cells]
            complete_rectangle = len(cells) == (max(rows) - min(rows) + 1) * (max(columns) - min(columns) + 1)
            boxes = [cell["rect_absolute"] for cell in cells]
            if complete_rectangle:
                x, y = min(b["left"] for b in boxes), min(b["top"] for b in boxes)
                boxes = [{"left": x, "top": y, "width": max(b["left"] + b["width"] for b in boxes) - x,
                          "height": max(b["top"] + b["height"] for b in boxes) - y}]
            geometry = {"rects": boxes}
        elif kind == "arrow":
            geometry = {key: self.point(gui_id, frame_id, view_id, spec[key]) for key in ("tail", "head")}
            if geometry["tail"] == geometry["head"]:
                raise AnnotationError("INVALID_ARGUMENT", "箭头头部和尾部不能重合。")
        else:
            geometry = {"position": self.point(gui_id, frame_id, view_id, spec["position"])}
        return {"annotation_id": annotation_id or "ann_" + uuid4().hex, **spec, "size_px": size,
                "frame_id": frame_id, "view_id": view_id, "geometry": geometry}

    def preview(self, state: dict) -> Path | None:
        if "last_frame_id" not in state:
            return None
        frame, view = self.source(state["gui_session_id"], state["last_frame_id"], "root")
        folder = self.folder(state["gui_session_id"])
        raw_path = (folder / view["raw_image"]).resolve()
        if not raw_path.is_relative_to(folder):
            raise AnnotationError("GUI_IMAGE_PATH_INVALID", "来源图片越界。")
        with Image.open(raw_path) as source:
            base = source.convert("RGBA")
        if base.size != (frame["capture_rect"]["width"], frame["capture_rect"]["height"]):
            raise AnnotationError("GUI_IMAGE_INVALID", "来源图片与坐标映射尺寸不符。")
        base.alpha_composite(render(frame["capture_rect"], state["annotations"]))
        path = folder / "annotation_previews" / (uuid4().hex + ".png")
        path.parent.mkdir(exist_ok=True)
        base.convert("RGB").save(path)
        return path

    def apply(self, payload: dict) -> dict:
        validate(payload)
        action, gui_id = payload["action"], payload.get("gui_session_id")
        states = self.groups(gui_id)
        changed = []
        if action in {"draw", "update", "delete"}:
            state = deepcopy(states[0])
            items = state["annotations"]
            if action == "draw":
                if len(items) + len(payload["annotations"]) > 500:
                    raise AnnotationError("ANNOTATION_LIMIT", "每个GUI会话最多保留500个标注。")
                frame_id, view_id = payload["frame_id"], payload.get("view_id", "root")
                additions = [self.make(gui_id, frame_id, view_id, spec) for spec in payload["annotations"]]
                items.extend(additions)
                changed = [item["annotation_id"] for item in additions]
                state["display_open"] = True
                state["last_frame_id"] = frame_id
            else:
                requested = [update["annotation_id"] for update in payload["updates"]] if action == "update" else payload["annotation_ids"]
                if len(set(requested)) != len(requested):
                    raise AnnotationError("INVALID_ARGUMENT", "同一次调用不能重复编辑一个标注。")
                by_id = {item["annotation_id"]: item for item in items}
                if any(key not in by_id for key in requested):
                    raise AnnotationError("ANNOTATION_NOT_FOUND", "指定的标注ID不存在，先list查看。")
                if action == "delete":
                    state["annotations"] = [item for item in items if item["annotation_id"] not in requested]
                    if not state["annotations"]:
                        state["display_open"] = False
                else:
                    for patch in payload["updates"]:
                        old = by_id[patch["annotation_id"]]
                        spec = {key: old[key] for key in ("type", "color", "size", "cell_ids", "tail", "head", "position", "text") if key in old}
                        spec.update({key: value for key, value in patch.items() if key not in {"annotation_id", "frame_id", "view_id"}})
                        # Validate against its original shape, so irrelevant fields are rejected.
                        validate({"action": "draw", "gui_session_id": gui_id, "frame_id": 0, "annotations": [spec]})
                        replacement = self.make(gui_id, patch.get("frame_id", old["frame_id"]), patch.get("view_id", old["view_id"]), spec, old["annotation_id"])
                        items[items.index(old)] = replacement
                        state["last_frame_id"] = replacement["frame_id"]
                changed = requested
            self.save(state)
            states = [state]
        elif action in {"close", "show"}:
            for state in states:
                state["display_open"] = action == "show" and bool(state["annotations"])
                self.save(state)
        response = {"ok": True, "summary": {"draw": "标注已添加。", "update": "标注已修改。", "delete": "标注已删除。",
                    "list": "已读取标注。", "close": "标注显示已关闭，数据保留。", "show": "标注已显示。"}[action],
                    "data": {"groups": states, "annotation_ids": changed}, "warnings": []}
        if action in {"draw", "update", "delete", "show"} and len(states) == 1:
            try:
                path = self.preview(states[0])
                if path:
                    response["image_path"] = str(path)
                    response["data"]["preview_frame_id"] = states[0]["last_frame_id"]
                    response["data"]["preview_basis"] = "saved_frame"
            except (OSError, ValueError, AnnotationError) as exc:
                response["warnings"].append(f"标注数据已保存，效果图生成失败：{exc}")
        return response
