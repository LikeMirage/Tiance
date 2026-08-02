from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any

from tiance_runtime import run_tool


TOOL_DIR = Path(__file__).resolve().parent
REQUIREMENTS_PATH = TOOL_DIR / "requirements.txt"
VALID_FORMATS = {"png", "jpg", "jpeg", "ppm", "pam", "pnm"}
VALID_COLORSPACES = {"rgb", "gray", "cmyk"}
VALID_ROTATIONS = {0, 90, 180, 270}
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class RenderOptions:
    image_format: str
    dpi: int | None
    zoom_x: float
    zoom_y: float
    colorspace: str
    alpha: bool
    include_annotations: bool
    use_cropbox: bool
    clip: tuple[float, float, float, float] | None
    extra_rotation: int
    jpg_quality: int
    filename_pattern: str
    overwrite: bool
    backup_existing: bool
    save_manifest: bool
    save_page_text: bool
    continue_on_error: bool
    dry_run: bool
    max_pages: int
    max_pixels: int


def ok(summary: str, data: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    return {"ok": True, "summary": summary, "data": data, "warnings": warnings or []}


def fail(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"ok": False, "error": f"{code}: {message}", "error_info": {"code": code, "message": message, "details": details or {}}, "warnings": []}


def load_fitz() -> Any:
    try:
        import fitz  # type: ignore
    except Exception as exc:
        raise ToolError(
            "DEPENDENCY_MISSING",
            "缺少 PyMuPDF 依赖，无法渲染 PDF。",
            {
                "requirements_path": str(REQUIREMENTS_PATH),
                "required": ["PyMuPDF>=1.26.0,<2.0.0"],
                "message": "请先安装此工具 requirements.txt 中声明的依赖后重试。",
                "original_error": str(exc),
            },
        ) from exc
    return fitz


def workspace_root() -> Path:
    raw = os.environ.get("TIANCE_WORKSPACE_ROOT") or os.environ.get("WORKSPACE_ROOT") or os.getcwd()
    return Path(raw).expanduser().resolve(strict=False)


def read_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def read_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def read_optional_int(value: Any, minimum: int, maximum: int) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(minimum, min(maximum, parsed))


def read_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def read_enum(value: Any, allowed: set[Any], default: Any) -> Any:
    if value in allowed:
        return value
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def resolve_pdf_path(value: Any, root: Path) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ToolError("INVALID_ARGUMENT", "file_path 不能为空。")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ToolError("PATH_OUTSIDE_WORKSPACE", "PDF 路径不在工作区内。", {"file_path": str(resolved), "workspace_root": str(root)}) from exc
    if not resolved.exists():
        raise ToolError("FILE_NOT_FOUND", "PDF 文件不存在。", {"file_path": str(resolved)})
    if resolved.is_dir():
        raise ToolError("IS_DIRECTORY", "file_path 必须指向 PDF 文件。", {"file_path": str(resolved)})
    if resolved.suffix.lower() != ".pdf":
        raise ToolError("INVALID_ARGUMENT", "file_path 必须是 .pdf 文件。", {"file_path": str(resolved)})
    return resolved


def resolve_output_dir(payload: dict[str, Any], root: Path, pdf_path: Path, options: RenderOptions) -> tuple[Path, str | None]:
    output_root_raw = str(payload.get("output_root") or "").strip()
    if output_root_raw:
        output_root = Path(output_root_raw).expanduser()
        if not output_root.is_absolute():
            output_root = root / output_root
    else:
        output_root = pdf_path.parent
    output_root = output_root.resolve(strict=False)
    try:
        output_root.relative_to(root)
    except ValueError as exc:
        raise ToolError("PATH_OUTSIDE_WORKSPACE", "输出目录必须位于工作区内。", {"output_root": str(output_root), "workspace_root": str(root)}) from exc

    folder_name = sanitize_filename(str(payload.get("output_folder_name") or "").strip())
    if not folder_name:
        folder_name = sanitize_filename(f"{pdf_path.stem}_images")
    output_dir = (output_root / folder_name).resolve(strict=False)
    try:
        output_dir.relative_to(root)
    except ValueError as exc:
        raise ToolError("PATH_OUTSIDE_WORKSPACE", "输出目录必须位于工作区内。", {"output_dir": str(output_dir), "workspace_root": str(root)}) from exc

    backup_path = None
    if output_dir.exists():
        if not options.overwrite:
            raise ToolError("OUTPUT_EXISTS", "输出目录已存在，未启用 overwrite。", {"output_dir": str(output_dir)})
        if options.dry_run:
            return output_dir, None
        if options.backup_existing:
            stamp = datetime.now().strftime("%Y%m%d%H%M%S")
            backup_path = str(output_dir.with_name(f"{output_dir.name}.{stamp}.bak"))
            shutil.move(str(output_dir), backup_path)
        else:
            shutil.rmtree(output_dir)
    if not options.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir, backup_path


def read_options(payload: dict[str, Any], warnings: list[str]) -> RenderOptions:
    image_format = read_enum(payload.get("image_format"), VALID_FORMATS, "png")
    if image_format == "jpeg":
        output_format = "jpg"
    else:
        output_format = image_format
    dpi = read_optional_int(payload.get("dpi", 200), 36, 1200)
    if dpi is not None and any(key in payload for key in ("zoom", "zoom_x", "zoom_y")):
        warnings.append("同时提供 dpi 和 zoom 参数时，已优先使用 dpi。")
    zoom = read_float(payload.get("zoom"), 1.0, 0.1, 20.0)
    zoom_x = read_float(payload.get("zoom_x"), zoom, 0.1, 20.0)
    zoom_y = read_float(payload.get("zoom_y"), zoom, 0.1, 20.0)
    colorspace = read_enum(payload.get("colorspace"), VALID_COLORSPACES, "rgb")
    alpha = read_bool(payload.get("alpha"), False)
    if output_format == "jpg" and alpha:
        warnings.append("JPEG 不支持透明背景，已自动关闭 alpha。")
        alpha = False
    return RenderOptions(
        image_format=output_format,
        dpi=dpi,
        zoom_x=zoom_x,
        zoom_y=zoom_y,
        colorspace=colorspace,
        alpha=alpha,
        include_annotations=read_bool(payload.get("include_annotations"), True),
        use_cropbox=read_bool(payload.get("use_cropbox"), True),
        clip=read_clip(payload.get("clip")),
        extra_rotation=int(read_enum(payload.get("extra_rotation"), VALID_ROTATIONS, 0)),
        jpg_quality=read_int(payload.get("jpg_quality"), 95, 1, 100),
        filename_pattern=str(payload.get("filename_pattern") or "{stem}_page_{page:04d}.{ext}").strip() or "{stem}_page_{page:04d}.{ext}",
        overwrite=read_bool(payload.get("overwrite"), False),
        backup_existing=read_bool(payload.get("backup_existing"), True),
        save_manifest=read_bool(payload.get("save_manifest"), True),
        save_page_text=read_bool(payload.get("save_page_text"), False),
        continue_on_error=read_bool(payload.get("continue_on_error"), True),
        dry_run=read_bool(payload.get("dry_run"), False),
        max_pages=read_int(payload.get("max_pages"), 500, 1, 5000),
        max_pixels=read_int(payload.get("max_pixels"), 100_000_000, 1_000_000, 1_000_000_000),
    )


def read_clip(value: Any) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ToolError("INVALID_ARGUMENT", "clip 必须是包含 x0、y0、x1、y1 的对象。")
    try:
        x0 = float(value["x0"])
        y0 = float(value["y0"])
        x1 = float(value["x1"])
        y1 = float(value["y1"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolError("INVALID_ARGUMENT", "clip 必须包含数字 x0、y0、x1、y1。", {"clip": value}) from exc
    if x1 <= x0 or y1 <= y0:
        raise ToolError("INVALID_ARGUMENT", "clip 的 x1/y1 必须大于 x0/y0。", {"clip": value})
    return (x0, y0, x1, y1)


def parse_pages(payload: dict[str, Any], page_count: int, max_pages: int) -> list[int]:
    selected: list[int] = []
    page_ranges = str(payload.get("page_ranges") or "all").strip().lower()
    if page_ranges and page_ranges != "all":
        for part in page_ranges.split(","):
            selected.extend(parse_page_range_part(part.strip(), page_count))
    else:
        selected.extend(range(1, page_count + 1))
    if isinstance(payload.get("pages"), list):
        for item in payload["pages"]:
            try:
                page = int(item)
            except (TypeError, ValueError):
                continue
            if 1 <= page <= page_count:
                selected.append(page)
            else:
                raise ToolError("INVALID_ARGUMENT", "pages 中存在超出范围的页码。", {"page": page, "page_count": page_count})
    deduped: list[int] = []
    seen: set[int] = set()
    for page in selected:
        if page in seen:
            continue
        if not 1 <= page <= page_count:
            raise ToolError("INVALID_ARGUMENT", "页码超出 PDF 页数。", {"page": page, "page_count": page_count})
        deduped.append(page)
        seen.add(page)
    if not deduped:
        raise ToolError("INVALID_ARGUMENT", "没有可渲染的页码。", {"page_count": page_count})
    if len(deduped) > max_pages:
        raise ToolError("TOO_MANY_PAGES", "请求渲染页数超过 max_pages。", {"requested": len(deduped), "max_pages": max_pages})
    return deduped


def parse_page_range_part(part: str, page_count: int) -> list[int]:
    if not part:
        return []
    if part == "last":
        return [page_count]
    if "-" in part:
        start_text, end_text = part.split("-", 1)
        start = parse_page_token(start_text, page_count) if start_text else 1
        end = parse_page_token(end_text, page_count) if end_text else page_count
        if start > end:
            raise ToolError("INVALID_ARGUMENT", "页码范围起点不能大于终点。", {"range": part})
        return list(range(start, end + 1))
    return [parse_page_token(part, page_count)]


def parse_page_token(value: str, page_count: int) -> int:
    text = value.strip().lower()
    if text == "last":
        return page_count
    try:
        page = int(text)
    except ValueError as exc:
        raise ToolError("INVALID_ARGUMENT", "页码范围格式无效。", {"token": value}) from exc
    return page


def colorspace_object(fitz: Any, colorspace: str) -> Any:
    if colorspace == "gray":
        return fitz.csGRAY
    if colorspace == "cmyk":
        return fitz.csCMYK
    return fitz.csRGB


def build_matrix(fitz: Any, page: Any, options: RenderOptions) -> tuple[Any, float, float]:
    if options.dpi is not None:
        zoom_x = options.dpi / 72.0
        zoom_y = options.dpi / 72.0
    else:
        zoom_x = options.zoom_x
        zoom_y = options.zoom_y
    matrix = fitz.Matrix(zoom_x, zoom_y)
    if options.extra_rotation:
        matrix = matrix.prerotate(options.extra_rotation)
    return matrix, zoom_x, zoom_y


def estimate_pixel_size(page: Any, options: RenderOptions, zoom_x: float, zoom_y: float) -> tuple[int, int, int]:
    if options.clip is not None:
        width = options.clip[2] - options.clip[0]
        height = options.clip[3] - options.clip[1]
    elif options.use_cropbox:
        rect = page.rect
        width = float(rect.width)
        height = float(rect.height)
    else:
        rect = page.mediabox
        width = float(rect.width)
        height = float(rect.height)
    if options.extra_rotation in {90, 270}:
        width, height = height, width
    pixel_width = max(1, int(round(width * zoom_x)))
    pixel_height = max(1, int(round(height * zoom_y)))
    return pixel_width, pixel_height, pixel_width * pixel_height


def render_page(
    *,
    fitz: Any,
    doc: Any,
    pdf_path: Path,
    output_dir: Path,
    page_number: int,
    index: int,
    options: RenderOptions,
) -> dict[str, Any]:
    page = doc.load_page(page_number - 1)
    matrix, zoom_x, zoom_y = build_matrix(fitz, page, options)
    estimated_width, estimated_height, estimated_pixels = estimate_pixel_size(page, options, zoom_x, zoom_y)
    if estimated_pixels > options.max_pixels:
        raise ToolError(
            "PAGE_TOO_LARGE",
            "页面渲染像素数超过 max_pixels。",
            {"page": page_number, "estimated_pixels": estimated_pixels, "max_pixels": options.max_pixels},
        )

    ext = "jpg" if options.image_format == "jpeg" else options.image_format
    dry_run_filename = format_filename(
        options.filename_pattern,
        stem=pdf_path.stem,
        page=page_number,
        page_index0=page_number - 1,
        index=index,
        ext=ext,
        width=estimated_width,
        height=estimated_height,
    )
    if options.dry_run:
        image_path = output_dir / dry_run_filename
        return {
            "page": page_number,
            "page_index0": page_number - 1,
            "index": index,
            "output_path": str(image_path),
            "relative_path": image_path.name if image_path.parent == output_dir else image_path.relative_to(output_dir).as_posix(),
            "format": ext,
            "width": estimated_width,
            "height": estimated_height,
            "colorspace": options.colorspace,
            "alpha": options.alpha,
            "dpi": options.dpi,
            "zoom_x": zoom_x,
            "zoom_y": zoom_y,
            "estimated_pixels": estimated_pixels,
            "dry_run": True,
            "size_bytes": None,
            "sha256": None,
        }

    clip_rect = fitz.Rect(*options.clip) if options.clip is not None else None
    original_cropbox = None
    if not options.use_cropbox:
        original_cropbox = page.cropbox
        page.set_cropbox(page.mediabox)
    try:
        pix = page.get_pixmap(
            matrix=matrix,
            colorspace=colorspace_object(fitz, options.colorspace),
            clip=clip_rect,
            alpha=options.alpha,
            annots=options.include_annotations,
        )
    finally:
        if original_cropbox is not None:
            page.set_cropbox(original_cropbox)

    filename = format_filename(
        options.filename_pattern,
        stem=pdf_path.stem,
        page=page_number,
        page_index0=page_number - 1,
        index=index,
        ext=ext,
        width=pix.width,
        height=pix.height,
    )
    image_path = unique_path(output_dir / filename)
    text_path = None
    image_bytes = pix.tobytes(options.image_format, jpg_quality=options.jpg_quality)
    if not options.dry_run:
        image_path.write_bytes(image_bytes)
        if options.save_page_text:
            text_path = image_path.with_suffix(".txt")
            text_path.write_text(page.get_text("text"), encoding="utf-8")

    record = {
        "page": page_number,
        "page_index0": page_number - 1,
        "index": index,
        "output_path": str(image_path),
        "relative_path": image_path.name if image_path.parent == output_dir else image_path.relative_to(output_dir).as_posix(),
        "format": ext,
        "width": pix.width,
        "height": pix.height,
        "colorspace": options.colorspace,
        "alpha": options.alpha,
        "dpi": options.dpi,
        "zoom_x": zoom_x,
        "zoom_y": zoom_y,
        "estimated_pixels": estimated_pixels,
        "dry_run": options.dry_run,
    }
    if options.dry_run:
        record["size_bytes"] = len(image_bytes)
        record["sha256"] = hashlib.sha256(image_bytes).hexdigest()
    else:
        record["size_bytes"] = image_path.stat().st_size
        record["sha256"] = hashlib.sha256(image_path.read_bytes()).hexdigest()
    if text_path is not None:
        record["text_path"] = str(text_path)
    return record


def format_filename(pattern: str, **values: Any) -> str:
    try:
        name = pattern.format(**values)
    except Exception as exc:
        raise ToolError("INVALID_ARGUMENT", "filename_pattern 格式无效。", {"filename_pattern": pattern, "message": str(exc)}) from exc
    path = Path(name)
    filename = sanitize_filename(path.name)
    if "." not in filename:
        filename = f"{filename}.{values['ext']}"
    return filename


def prepare_document(fitz: Any, pdf_path: Path, password: str) -> Any:
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        raise ToolError("PDF_OPEN_FAILED", f"无法打开 PDF：{exc}", {"file_path": str(pdf_path)}) from exc
    if doc.needs_pass:
        if not password:
            doc.close()
            raise ToolError("PDF_PASSWORD_REQUIRED", "PDF 已加密，需要提供 password。", {"file_path": str(pdf_path)})
        if not doc.authenticate(password):
            doc.close()
            raise ToolError("PDF_PASSWORD_INVALID", "PDF 密码无效。", {"file_path": str(pdf_path)})
    return doc


def write_manifest(
    *,
    output_dir: Path,
    pdf_path: Path,
    doc: Any,
    pages: list[int],
    rendered_pages: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    options: RenderOptions,
    backup_path: str | None,
) -> Path:
    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_pdf": str(pdf_path),
        "source_sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        "page_count": doc.page_count,
        "selected_pages": pages,
        "rendered_count": len(rendered_pages),
        "error_count": len(errors),
        "output_dir": str(output_dir),
        "backup_path": backup_path,
        "options": {
            "image_format": options.image_format,
            "dpi": options.dpi,
            "zoom_x": options.zoom_x,
            "zoom_y": options.zoom_y,
            "colorspace": options.colorspace,
            "alpha": options.alpha,
            "include_annotations": options.include_annotations,
            "use_cropbox": options.use_cropbox,
            "clip": options.clip,
            "extra_rotation": options.extra_rotation,
            "jpg_quality": options.jpg_quality,
            "save_page_text": options.save_page_text,
            "dry_run": options.dry_run,
            "max_pixels": options.max_pixels,
        },
        "pages": rendered_pages,
        "errors": errors,
    }
    manifest_path = output_dir / "manifest.json"
    if not options.dry_run:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def sanitize_filename(value: str) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = re.sub(r"_+", "_", text).strip(" ._")
    if not text:
        text = "untitled"
    if text.upper() in WINDOWS_RESERVED_NAMES:
        text = f"{text}_file"
    return text[:180]


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 10000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise ToolError("OUTPUT_EXISTS", "无法生成唯一输出文件名。", {"path": str(path)})


def run(payload: dict[str, Any]) -> dict[str, Any]:
    doc = None
    try:
        warnings: list[str] = []
        fitz = load_fitz()
        root = workspace_root()
        pdf_path = resolve_pdf_path(payload.get("file_path"), root)
        options = read_options(payload, warnings)
        doc = prepare_document(fitz, pdf_path, str(payload.get("password") or ""))
        pages = parse_pages(payload, doc.page_count, options.max_pages)
        output_dir, backup_path = resolve_output_dir(payload, root, pdf_path, options)

        rendered_pages: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for index, page_number in enumerate(pages, start=1):
            try:
                rendered_pages.append(
                    render_page(
                        fitz=fitz,
                        doc=doc,
                        pdf_path=pdf_path,
                        output_dir=output_dir,
                        page_number=page_number,
                        index=index,
                        options=options,
                    )
                )
            except ToolError as exc:
                error_item = {"page": page_number, "code": exc.code, "message": exc.message, "details": exc.details}
                errors.append(error_item)
                if not options.continue_on_error:
                    raise
            except Exception as exc:
                error_item = {"page": page_number, "code": "PAGE_RENDER_FAILED", "message": str(exc) or exc.__class__.__name__}
                errors.append(error_item)
                if not options.continue_on_error:
                    raise ToolError("PAGE_RENDER_FAILED", error_item["message"], {"page": page_number}) from exc

        manifest_path = None
        if options.save_manifest:
            manifest_path = write_manifest(
                output_dir=output_dir,
                pdf_path=pdf_path,
                doc=doc,
                pages=pages,
                rendered_pages=rendered_pages,
                errors=errors,
                options=options,
                backup_path=backup_path,
            )
        if errors and not rendered_pages:
            raise ToolError("ALL_PAGES_FAILED", "所有页面渲染失败。", {"errors": errors})
        summary = f"PDF 转图片完成：选择 {len(pages)} 页，成功 {len(rendered_pages)} 页，失败 {len(errors)} 页。"
        if options.dry_run:
            summary = f"PDF 转图片预演完成：选择 {len(pages)} 页。"
        return ok(
            summary,
            {
                "source_pdf": str(pdf_path),
                "page_count": doc.page_count,
                "selected_pages": pages,
                "output_dir": str(output_dir),
                "backup_path": backup_path,
                "manifest_path": str(manifest_path) if manifest_path else None,
                "rendered_count": len(rendered_pages),
                "error_count": len(errors),
                "pages": rendered_pages,
                "errors": errors,
                "dry_run": options.dry_run,
                "pymupdf_version": getattr(fitz, "VersionBind", None),
            },
            warnings,
        )
    except ToolError as exc:
        return fail(exc.code, exc.message, exc.details)
    except Exception as exc:
        return fail("UNEXPECTED_ERROR", str(exc) or exc.__class__.__name__)
    finally:
        if doc is not None:
            doc.close()


if __name__ == "__main__":
    run_tool(run)
