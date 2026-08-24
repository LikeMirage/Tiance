from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from typing import Any
from urllib.parse import quote

from tiance_runtime import model_supports_input, run_tool


IMAGE_MIME_TYPES = {
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def success(summary: str, data: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    return {"ok": True, "summary": summary, "data": data, "warnings": warnings or []}


def failure(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"ok": False, "error": f"{code}: {message}", "error_info": {"code": code, "message": message, "details": details or {}}, "warnings": []}


def workspace_root() -> Path:
    raw = os.environ.get("TIANCE_WORKSPACE_ROOT") or os.environ.get("WORKSPACE_ROOT") or os.getcwd()
    return Path(raw).expanduser().resolve(strict=False)


def read_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def read_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def resolve_file(value: Any, root: Path) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ToolError("INVALID_ARGUMENT", "file_path 不能为空。")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve(strict=False)
    if not resolved.exists():
        raise ToolError("FILE_NOT_FOUND", "文件不存在。", {"file_path": str(resolved)})
    if resolved.is_dir():
        raise ToolError("IS_DIRECTORY", "期望读取文件，但路径是目录。", {"file_path": str(resolved)})
    return resolved


def describe_path(file_path: Path, root: Path) -> tuple[str, str, str | None]:
    try:
        relative_path = file_path.relative_to(root).as_posix()
    except ValueError:
        return "local", str(file_path), None
    return "workspace", relative_path, relative_path


def local_resource_uri(file_path: Path) -> str:
    file_uri = file_path.as_uri()
    return f"tiance-local:{file_uri.removeprefix('file:')}"


def looks_binary(data: bytes) -> bool:
    sample = data[:4096]
    if b"\x00" in sample:
        return True
    if not sample:
        return False
    control = sum(1 for byte in sample if byte < 9 or (13 < byte < 32))
    return control / len(sample) > 0.20


def validate_image_signature(content: bytes, mime_type: str) -> None:
    is_valid = (
        (mime_type == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n"))
        or (mime_type == "image/jpeg" and content.startswith(b"\xff\xd8\xff"))
        or (mime_type == "image/gif" and content.startswith((b"GIF87a", b"GIF89a")))
        or (
            mime_type == "image/webp"
            and len(content) >= 12
            and content[:4] == b"RIFF"
            and content[8:12] == b"WEBP"
        )
        or (mime_type == "image/bmp" and content.startswith(b"BM"))
    )
    if not is_valid:
        raise ToolError("IMAGE_CONTENT_MISMATCH", "图片内容和图片类型不匹配。")


def file_sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def image_scale_percent(value: Any) -> int:
    if value is None:
        return 60
    if isinstance(value, bool):
        raise ToolError("INVALID_ARGUMENT", "image_scale_percent 必须是 10 到 100 之间的整数。")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ToolError("INVALID_ARGUMENT", "image_scale_percent 必须是 10 到 100 之间的整数。") from exc
    if parsed < 10 or parsed > 100:
        raise ToolError("INVALID_ARGUMENT", "image_scale_percent 必须是 10 到 100 之间的整数。")
    return parsed


def resized_image(
    file_path: Path,
    source_sha256: str,
    scale_percent: int,
) -> tuple[Path, str, int, int, int, int]:
    try:
        from PIL import Image, ImageOps, ImageSequence
    except ImportError as exc:
        raise ToolError(
            "DEPENDENCY_MISSING",
            "图片缩放依赖 Pillow，请先在工具依赖看板安装 program/requirements.txt 中的依赖。",
        ) from exc

    try:
        with Image.open(file_path) as source:
            source_width, source_height = ImageOps.exif_transpose(source.copy()).size
            if scale_percent == 100:
                return (
                    file_path,
                    IMAGE_MIME_TYPES[file_path.suffix.lower()],
                    source_width,
                    source_height,
                    source_width,
                    source_height,
                )

            target_width = max(1, round(source_width * scale_percent / 100))
            target_height = max(1, round(source_height * scale_percent / 100))
            source_format = (source.format or file_path.suffix.removeprefix(".")).upper()
            output_format = "PNG" if source_format == "BMP" else source_format
            output_suffix = ".png" if output_format == "PNG" else file_path.suffix.lower()
            output_mime_type = IMAGE_MIME_TYPES[output_suffix]
            cache_root = Path(tempfile.gettempdir()) / "Tiance" / "read_file" / "image-cache"
            cache_root.mkdir(parents=True, exist_ok=True)
            output_path = cache_root / f"v1-{source_sha256}-{scale_percent}{output_suffix}"

            if not output_path.exists():
                resampling = Image.Resampling.LANCZOS
                frames = []
                durations = []
                disposals = []
                for frame in ImageSequence.Iterator(source):
                    normalized = ImageOps.exif_transpose(frame.copy())
                    frames.append(normalized.resize((target_width, target_height), resampling))
                    durations.append(frame.info.get("duration", source.info.get("duration", 0)))
                    disposals.append(getattr(frame, "disposal_method", source.info.get("disposal", 0)))

                save_options: dict[str, Any] = {}
                if output_format in {"JPEG", "JPG"}:
                    output_format = "JPEG"
                    frames = [frame.convert("RGB") for frame in frames]
                    save_options.update({"quality": 90, "optimize": True})
                elif output_format == "WEBP":
                    save_options.update({"quality": 90, "method": 4})
                elif output_format == "PNG":
                    save_options.update({"optimize": True})
                elif output_format == "GIF":
                    frames = [frame.convert("P", palette=Image.Palette.ADAPTIVE) for frame in frames]

                if len(frames) > 1:
                    save_options.update(
                        {
                            "save_all": True,
                            "append_images": frames[1:],
                            "duration": durations,
                            "loop": source.info.get("loop", 0),
                        }
                    )
                    if output_format == "GIF":
                        save_options["disposal"] = disposals
                frames[0].save(output_path, format=output_format, **save_options)
            return output_path, output_mime_type, source_width, source_height, target_width, target_height
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError("IMAGE_RESIZE_FAILED", "图片缩放失败。", {"reason": str(exc)}) from exc


def read_image(
    file_path: Path,
    root: Path,
    mime_type: str,
    scale_percent: int,
) -> dict[str, Any]:
    if not model_supports_input("image"):
        raise ToolError(
            "MODEL_INPUT_UNSUPPORTED",
            "当前AI不支持视觉理解，无法直接读取图片。请使用图片解析工具 doubao_vision_parse 解析。",
        )
    source_size_bytes = file_path.stat().st_size
    if source_size_bytes <= 0:
        raise ToolError("EMPTY_IMAGE", "图片内容为空。")
    with file_path.open("rb") as stream:
        signature = stream.read(16)
    validate_image_signature(signature, mime_type)
    path_scope, display_path, relative_path = describe_path(file_path, root)
    source_sha256 = file_sha256(file_path)
    returned_path, returned_mime_type, source_width, source_height, returned_width, returned_height = resized_image(
        file_path,
        source_sha256,
        scale_percent,
    )
    returned_size_bytes = returned_path.stat().st_size
    returned_sha256 = file_sha256(returned_path)
    if returned_path == file_path and relative_path is not None:
        resource_uri = f"tiance-project:///{quote(relative_path, safe='/')}"
    else:
        resource_uri = local_resource_uri(returned_path)
    metadata = {
        "file_type": "image",
        "file_path": str(file_path),
        "path_scope": path_scope,
        "image_scale_percent": scale_percent,
        "source_mime_type": mime_type,
        "source_sha256": source_sha256,
        "source_size_bytes": source_size_bytes,
        "source_width": source_width,
        "source_height": source_height,
        "returned_file_path": str(returned_path),
        "returned_mime_type": returned_mime_type,
        "returned_sha256": returned_sha256,
        "returned_size_bytes": returned_size_bytes,
        "returned_width": returned_width,
        "returned_height": returned_height,
        "optimized": returned_path != file_path,
    }
    if relative_path is not None:
        metadata["relative_path"] = relative_path
    return {
        "ok": True,
        "summary": f"已按 {scale_percent}% 尺寸读取图片 {display_path}。",
        "content": [
            {
                "type": "resource_link",
                "uri": resource_uri,
                "name": returned_path.name,
                "mimeType": returned_mime_type,
                "size": returned_size_bytes,
                "annotations": {
                    "audience": ["assistant"],
                    "priority": 1.0,
                },
            }
        ],
        "structuredContent": metadata,
        "data": metadata,
        "warnings": [],
    }


def decode_text(data: bytes, encoding: str) -> tuple[str, str]:
    enc = (encoding or "auto").strip().lower()
    candidates = ["utf-8-sig", "utf-8", "gb18030"] if enc == "auto" else [enc]
    errors: list[str] = []
    for item in candidates:
        try:
            return data.decode(item), item
        except LookupError as exc:
            raise ToolError("INVALID_ARGUMENT", "encoding 参数无效。", {"encoding": encoding}) from exc
        except UnicodeDecodeError as exc:
            errors.append(f"{item}: {exc}")
    raise ToolError("ENCODING_ERROR", "无法按指定编码读取文件。", {"encoding": encoding, "errors": errors})


def numbered(lines: list[str], start_line: int) -> str:
    width = len(str(start_line + len(lines) - 1))
    return "\n".join(f"{line_no:>{width}} | {line}" for line_no, line in enumerate(lines, start=start_line))


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        root = workspace_root()
        file_path = resolve_file(payload.get("file_path"), root)
        image_mime_type = IMAGE_MIME_TYPES.get(file_path.suffix.lower())
        if image_mime_type is not None:
            return read_image(
                file_path,
                root,
                image_mime_type,
                image_scale_percent(payload.get("image_scale_percent")),
            )
        start_line = read_int(payload.get("start_line"), 1, 1, 10_000_000)
        max_lines = read_int(payload.get("max_lines"), 2000, 1, 20_000)
        max_chars = read_int(payload.get("max_chars"), 50_000, 1000, 1_000_000)
        include_numbers = read_bool(payload.get("include_line_numbers"), False)
        allow_binary = read_bool(payload.get("allow_binary"), False)
        data = file_path.read_bytes()
        if looks_binary(data) and not allow_binary:
            raise ToolError("BINARY_FILE", "文件疑似二进制，默认拒绝按文本读取。", {"file_path": str(file_path), "size_bytes": len(data)})
        text, used_encoding = decode_text(data, str(payload.get("encoding") or "auto"))
        all_lines = text.splitlines()
        begin = min(start_line - 1, len(all_lines))
        selected = all_lines[begin : begin + max_lines]
        content = numbered(selected, start_line) if include_numbers else "\n".join(selected)
        truncated_by_chars = False
        if len(content) > max_chars:
            content = content[:max_chars]
            truncated_by_chars = True
        end_line = start_line + len(selected) - 1 if selected else start_line - 1
        warnings: list[str] = []
        if begin + max_lines < len(all_lines):
            warnings.append("内容按最大行数截断。")
        if truncated_by_chars:
            warnings.append("内容按最大字符数截断。")
        path_scope, display_path, relative_path = describe_path(file_path, root)
        file_data = {
            "file_path": str(file_path),
            "path_scope": path_scope,
            "encoding": used_encoding,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
            "total_lines": len(all_lines),
            "start_line": start_line,
            "end_line": end_line,
            "line_count": len(selected),
            "content": content,
            "truncated": bool(warnings),
        }
        if relative_path is not None:
            file_data["relative_path"] = relative_path
        return success(
            f"读取 {display_path} 第 {start_line}-{end_line} 行。",
            file_data,
            warnings,
        )
    except ToolError as exc:
        return failure(exc.code, exc.message, exc.details)


if __name__ == "__main__":
    run_tool(run)
