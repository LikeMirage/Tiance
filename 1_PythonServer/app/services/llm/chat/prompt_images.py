from base64 import b64decode, b64encode
from collections.abc import Callable
from dataclasses import replace
from io import BytesIO
from urllib.parse import unquote_to_bytes

import httpx
from PIL import Image

from app.core.errors import BadRequestError
from app.domain.llm.chat import (
    ChatCompletionRequest, ChatImageDelivery, ChatImageRef, ChatImageUrl, ChatMessageContentPart,
    ChatMessageContentPartType as PartType,
)
from app.infra.prompt_image import prepare_prompt_image
from app.infra.public_image_download import download_public_image


def request_image_count(request: ChatCompletionRequest) -> int:
    return sum(
        part.type in (PartType.IMAGE_REF, PartType.IMAGE_URL)
        for message in request.messages for part in message.content_parts
    )


def prepare_request_images(
    request: ChatCompletionRequest, max_long_edge: int, *,
    read_ref: Callable[[ChatImageRef], bytes] | None = None,
) -> ChatCompletionRequest:
    messages = []
    deliveries = []
    for message_index, message in enumerate(request.messages, 1):
        parts = []
        for part_index, part in enumerate(message.content_parts, 1):
            if part.type not in (PartType.IMAGE_REF, PartType.IMAGE_URL):
                parts.append(part)
                continue
            ref = part.image_ref if part.type == PartType.IMAGE_REF else None
            source_url = part.image_url if part.type == PartType.IMAGE_URL else None
            try:
                if ref is not None and read_ref is not None:
                    content, detail = read_ref(ref), ref.detail
                elif source_url is not None:
                    content, detail = read_image_url(source_url.url), source_url.detail
                else:
                    raise BadRequestError("图片引用未解析。")
                image = prepare_prompt_image(
                    BytesIO(content), max_long_edge=max_long_edge, scale_percent=ref.scale_percent if ref else 100,
                )
                prefix = f"data:{image.mime_type};base64,"
                if image.variant_path is None and source_url and source_url.url.startswith(prefix):
                    url = source_url.url
                else:
                    if image.variant_path is not None:
                        content = image.variant_path.read_bytes()
                    url = prefix + b64encode(content).decode("ascii")
            except (ValueError, OSError, SyntaxError, Image.DecompressionBombError, httpx.HTTPError) as exc:
                # An upstream transport error may contain a signed image URL.
                reason = "网络图片下载失败" if isinstance(exc, httpx.HTTPError) else str(exc)
                raise BadRequestError(f"第 {message_index} 条消息的第 {part_index} 项图片准备失败：{reason}") from exc
            delivery = ChatImageDelivery(
                message_index, part_index, ref.attachment_id if ref else None,
                *image.source_size, *image.size, max_long_edge,
            )
            deliveries.append(delivery)
            if image.source_size != image.size:
                parts.append(ChatMessageContentPart(
                    type=PartType.TEXT,
                    text=(f"图片从 {delivery.source_width}×{delivery.source_height} "
                          f"等比缩放至 {delivery.sent_width}×{delivery.sent_height}。"),
                ))
            parts.append(ChatMessageContentPart(type=PartType.IMAGE_URL, image_url=ChatImageUrl(url, detail)))
        messages.append(replace(message, content_parts=tuple(parts)) if parts else message)
    return replace(request, messages=tuple(messages), image_deliveries=tuple(deliveries))


def read_image_url(url: str) -> bytes:
    if url[:5].lower() == "data:":
        header, separator, data = url.partition(",")
        if not separator:
            raise ValueError("图片 data URL 缺少内容。")
        if header.lower().endswith(";base64"):
            return b64decode(data, validate=True)
        return unquote_to_bytes(data)
    with httpx.Client(trust_env=False, timeout=15.0) as client:
        return download_public_image(client, url, max_bytes=64 * 1024 * 1024)
