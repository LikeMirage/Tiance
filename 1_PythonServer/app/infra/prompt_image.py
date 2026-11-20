"""Prepare local image variants shared by model requests and file-reading tools."""

from dataclasses import dataclass
from hashlib import file_digest, sha256
from io import BytesIO
from pathlib import Path
import re
import tempfile

from PIL import Image, ImageOps, ImageSequence
from app.core.atomic_replace import atomic_replace_path


@dataclass(frozen=True, slots=True)
class PromptImage:
    source_size: tuple[int, int]
    size: tuple[int, int]
    mime_type: str
    variant_path: Path | None


def prepare_prompt_image(
    source: Path | BytesIO, digest: str | None = None, *, max_long_edge: int, scale_percent: int = 100,
) -> PromptImage:
    if not 1 <= scale_percent <= 100 or max_long_edge < 1:
        raise ValueError("图片缩放比例或最长边上限无效。")
    with Image.open(source) as image:
        width, height = image.size
        longest = max(width, height)
        source_format = image.format
        if source_format not in {"JPEG", "PNG", "GIF", "WEBP", "BMP"}:
            raise ValueError(f"不支持的图片格式 {source_format}")
        if longest <= max_long_edge and scale_percent == 100:
            return PromptImage(image.size, image.size, Image.MIME[source_format], None)

        ratio = min(scale_percent / 100, min(max_long_edge, longest) / longest)
        if image.getexif().get(274) in (5, 6, 7, 8):
            width, height = height, width
        size = (max(1, round(width * ratio)), max(1, round(height * ratio)))
        output_format = "PNG" if source_format == "BMP" else source_format
        if digest is None:
            if isinstance(source, BytesIO):
                digest = sha256(source.getbuffer()).hexdigest()
            else:
                with source.open("rb") as stream:
                    digest = file_digest(stream, "sha256").hexdigest()
        elif not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("图片缓存需要有效的 SHA-256。")
        cache = Path(tempfile.gettempdir()) / "Tiance" / "prompt-images"
        cache.mkdir(parents=True, exist_ok=True)
        dest = cache / f"v1-{digest}-{size[0]}x{size[1]}.{output_format.lower()}"
        if not dest.is_file():
            with tempfile.NamedTemporaryFile(dir=cache, delete=False) as temp:
                pending = Path(temp.name)
            try:
                _save_variant(image, pending, size, output_format)
                # Concurrent readers must only see complete images.
                atomic_replace_path(pending, dest)
            finally:
                pending.unlink(missing_ok=True)
        return PromptImage(image.size, size, Image.MIME[output_format], dest)


def _save_variant(image: Image.Image, path: Path, size: tuple[int, int], fmt: str) -> None:
    frames = []
    durations = []
    disposals = []
    loop = image.info.get("loop")
    for frame in ImageSequence.Iterator(image):
        oriented = ImageOps.exif_transpose(frame)
        if oriented.mode == "P":
            oriented = oriented.convert("RGBA")
        if fmt == "JPEG":
            oriented = oriented.convert("RGB")
        frames.append(oriented.resize(size, Image.Resampling.LANCZOS))
        durations.append(frame.info.get("duration", 0))
        disposals.append(getattr(frame, "disposal_method", 0))
    options = {}
    if fmt in ("JPEG", "WEBP"):
        options["quality"] = 90
    if len(frames) > 1:
        options.update(save_all=True, append_images=frames[1:], duration=durations)
        if loop is not None:
            options["loop"] = loop
        if fmt == "GIF":
            options["disposal"] = disposals
    frames[0].save(path, format=fmt, **options)
