from __future__ import annotations

from base64 import b64decode
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from mimetypes import guess_type
from pathlib import Path, PurePath
import re
import warnings
from urllib.parse import unquote_to_bytes, urlsplit

from PIL import Image, UnidentifiedImageError

from app.core.errors import BadRequestError
from app.domain.llm.chat import ChatMessageContentPartType
from app.domain.project.conversation_export import (
    ConversationExportDocument,
    ConversationExportImage,
    PreparedConversationExport,
)
from app.domain.project.project_conversation import ProjectConversationMessage
from app.infra.file_workspace import FileWorkspaceStorage
from app.services.document_conversion.markdown_docx.remote_image import (
    RemoteImageDownloader,
    is_remote_image_url,
    remote_image_display_url,
)
from app.services.document_conversion.markdown_docx.markdown_inline import (
    parse_image_token,
    tokenize_inline,
)

_MAX_IMAGE_COUNT = 100
_MAX_IMAGE_BYTES = 25 * 1024 * 1024
_MAX_TOTAL_IMAGE_BYTES = 100 * 1024 * 1024
_MAX_IMAGE_PIXELS = 40_000_000
_NATIVE_IMAGE_SUFFIXES = {
    "BMP": ".bmp",
    "GIF": ".gif",
    "JPEG": ".jpg",
    "PNG": ".png",
    "TIFF": ".tiff",
}


@dataclass(frozen=True, slots=True)
class _ResolvedAsset:
    asset_name: str
    content: bytes
    mime_type: str


@dataclass(frozen=True, slots=True)
class _ImageSource:
    alt_text: str
    embedded: bool
    key: str
    value: str


class ConversationExportAssetCollector:
    def __init__(self, file_storage: FileWorkspaceStorage) -> None:
        self._file_storage = file_storage

    def prepare(
        self,
        document: ConversationExportDocument,
        *,
        include_images: bool,
    ) -> tuple[PreparedConversationExport, tuple[str, ...]]:
        if not include_images:
            return PreparedConversationExport(document=document, images=()), ()

        downloader = RemoteImageDownloader()
        assets: dict[str, _ResolvedAsset] = {}
        occurrences: list[ConversationExportImage] = []
        warnings_list: list[str] = []
        total_bytes = 0

        for message in document.messages:
            sources = _message_image_sources(message)
            for source_index, source in enumerate(sources, start=1):
                asset = assets.get(source.key)
                if asset is None:
                    if len(assets) >= _MAX_IMAGE_COUNT:
                        warnings_list.append("单次导出最多包含 100 张不同图片，后续图片已跳过。")
                        break
                    try:
                        content, suffix, mime_type = self._load_image(
                            document.project_root,
                            source.value,
                            downloader=downloader,
                        )
                        if total_bytes + len(content) > _MAX_TOTAL_IMAGE_BYTES:
                            raise ValueError("单次导出的图片总量超过 100 MB 限制。")
                        asset_name = _asset_name(
                            len(assets) + 1,
                            source.value,
                            suffix=suffix,
                            fallback=f"image-{source_index}",
                        )
                        asset = _ResolvedAsset(
                            asset_name=asset_name,
                            content=content,
                            mime_type=mime_type,
                        )
                        assets[source.key] = asset
                        total_bytes += len(content)
                    except (BadRequestError, FileNotFoundError, OSError, ValueError) as exc:
                        warnings_list.append(f"图片未导出：{_source_label(source.value)}，原因：{exc}")
                        continue
                occurrences.append(
                    ConversationExportImage(
                        asset_name=asset.asset_name,
                        alt_text=source.alt_text or asset.asset_name,
                        content=asset.content,
                        embedded=source.embedded,
                        message_id=message.message_id,
                        mime_type=asset.mime_type,
                        source=source.value,
                    )
                )

        return (
            PreparedConversationExport(document=document, images=tuple(occurrences)),
            tuple(warnings_list),
        )

    def _load_image(
        self,
        project_root: Path,
        source: str,
        *,
        downloader: RemoteImageDownloader,
    ) -> tuple[bytes, str, str]:
        if is_remote_image_url(source):
            downloaded = downloader.download(source)
            return (
                downloaded.content,
                downloaded.suffix,
                _mime_type_for_suffix(downloaded.suffix),
            )
        if source.lower().startswith("data:image/"):
            content, declared_mime_type = _decode_image_data_url(source)
            return _validate_and_normalize_image(content, declared_mime_type)

        image_path = self._file_storage.resolve_file_path(str(project_root), source)
        if image_path.stat().st_size > _MAX_IMAGE_BYTES:
            raise ValueError("图片超过 25 MB 限制。")
        content = image_path.read_bytes()
        mime_type = guess_type(str(image_path))[0] or "application/octet-stream"
        return _validate_and_normalize_image(content, mime_type)


def _message_image_sources(
    message: ProjectConversationMessage,
) -> tuple[_ImageSource, ...]:
    sources = [
        source
        for part in message.content_parts
        if (source := _part_source(part)) is not None
    ]
    sources.extend(_markdown_image_sources(message.content))
    sources.extend(_markdown_image_sources(message.thinking_content))
    return tuple(sources)


def _part_source(part) -> _ImageSource | None:
    if part.type == ChatMessageContentPartType.IMAGE_REF and part.image_ref is not None:
        path = part.image_ref.path.strip()
        if not path:
            return None
        return _ImageSource(
            alt_text=part.image_ref.name or PurePath(path).name,
            embedded=False,
            key=f"ref:{path}",
            value=path,
        )
    if part.type == ChatMessageContentPartType.IMAGE_URL and part.image_url is not None:
        url = part.image_url.url.strip()
        if not url:
            return None
        return _ImageSource(
            alt_text=_url_file_name(url),
            embedded=False,
            key=_source_key(url),
            value=url,
        )
    return None


def _markdown_image_sources(value: str) -> tuple[_ImageSource, ...]:
    sources: list[_ImageSource] = []
    for token in tokenize_inline(value):
        parsed = parse_image_token(token.raw)
        if parsed is None:
            continue
        alt_text, source = parsed
        sources.append(
            _ImageSource(
                alt_text=alt_text,
                embedded=True,
                key=_source_key(source),
                value=source,
            )
        )
    return tuple(sources)


def _source_key(value: str) -> str:
    if value.lower().startswith("data:"):
        return f"data:{sha256(value.encode('utf-8')).hexdigest()}"
    return f"source:{value}"


def _decode_image_data_url(value: str) -> tuple[bytes, str]:
    header, separator, payload = value.partition(",")
    if not separator or not header.lower().startswith("data:image/"):
        raise ValueError("图片 Data URL 无效。")
    mime_type = header[5:].split(";", 1)[0].lower()
    try:
        content = b64decode(payload, validate=True) if ";base64" in header.lower() else unquote_to_bytes(payload)
    except (ValueError, TypeError) as exc:
        raise ValueError("图片 Data URL 无法解码。") from exc
    if len(content) > _MAX_IMAGE_BYTES:
        raise ValueError("图片超过 25 MB 限制。")
    return content, mime_type


def _validate_and_normalize_image(
    content: bytes,
    declared_mime_type: str,
) -> tuple[bytes, str, str]:
    if not content:
        raise ValueError("图片内容为空。")
    if len(content) > _MAX_IMAGE_BYTES:
        raise ValueError("图片超过 25 MB 限制。")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                image_format = (image.format or "").upper()
                if image.width * image.height > _MAX_IMAGE_PIXELS:
                    raise ValueError("图片像素尺寸过大。")
                image.verify()
    except ValueError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("图片像素尺寸过大。") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("内容不是有效图片。") from exc

    suffix = _NATIVE_IMAGE_SUFFIXES.get(image_format)
    if suffix is not None:
        return content, suffix, _mime_type_for_suffix(suffix, declared_mime_type)

    try:
        with Image.open(BytesIO(content)) as image:
            image.load()
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            normalized = image.convert("RGBA" if has_alpha else "RGB")
            output = BytesIO()
            normalized.save(output, format="PNG")
            normalized_content = output.getvalue()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("图片格式无法转换。") from exc
    if len(normalized_content) > _MAX_IMAGE_BYTES:
        raise ValueError("图片转换后超过 25 MB 限制。")
    return normalized_content, ".png", "image/png"


def _asset_name(index: int, source: str, *, suffix: str, fallback: str) -> str:
    candidate = _url_file_name(source) or PurePath(source.replace("\\", "/")).name or fallback
    stem = Path(candidate).stem
    safe_stem = re.sub(r"[^\w\-. ]+", "_", stem, flags=re.UNICODE).strip(" ._")
    safe_stem = safe_stem[:60] or fallback
    return f"image-{index:03d}-{safe_stem}{suffix.lower()}"


def _url_file_name(value: str) -> str:
    if value.lower().startswith("data:"):
        return ""
    try:
        return PurePath(urlsplit(value).path).name
    except ValueError:
        return ""


def _source_label(value: str) -> str:
    if is_remote_image_url(value):
        return remote_image_display_url(value)
    if value.lower().startswith("data:"):
        return "内嵌图片"
    return PurePath(value.replace("\\", "/")).name or "图片"


def _mime_type_for_suffix(suffix: str, fallback: str = "application/octet-stream") -> str:
    return {
        ".bmp": "image/bmp",
        ".gif": "image/gif",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
    }.get(suffix.lower(), fallback)
