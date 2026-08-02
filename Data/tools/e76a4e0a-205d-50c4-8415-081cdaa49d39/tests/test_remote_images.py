from __future__ import annotations

from io import BytesIO
from pathlib import Path

import httpx
import pytest
from docx import Document
from PIL import Image

from converter import Md2DocxConverter
from remote_image import (
    DownloadedImage,
    MAX_REMOTE_IMAGE_BYTES,
    RemoteImageDownloader,
    RemoteImageError,
    remote_image_display_url,
)
from word_formatting import FontSettings


_one_pixel_png_buffer = BytesIO()
Image.new("RGBA", (1, 1), (255, 255, 255, 255)).save(_one_pixel_png_buffer, format="PNG")
ONE_PIXEL_PNG = _one_pixel_png_buffer.getvalue()
PUBLIC_IMAGE_URL = "https://93.184.216.34/image.png"


def test_remote_markdown_image_is_inserted_into_word(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        RemoteImageDownloader,
        "download",
        lambda self, url: DownloadedImage(content=ONE_PIXEL_PNG, suffix=".png"),
    )
    converter = Md2DocxConverter(base_path=tmp_path, fonts=FontSettings())

    document = converter.convert(f"![network image]({PUBLIC_IMAGE_URL})")
    output_path = tmp_path / "network-image.docx"
    document.save(output_path)
    reopened = Document(output_path)

    assert len(document.inline_shapes) == 1
    assert len(reopened.inline_shapes) == 1
    assert converter.warnings == []


def test_remote_image_downloader_follows_redirects_and_caches() -> None:
    requested_urls: list[str] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/image.png":
            return httpx.Response(302, headers={"location": "/final.png"})
        return httpx.Response(200, headers={"content-type": "image/png"}, content=ONE_PIXEL_PNG)

    downloader = RemoteImageDownloader(transport=httpx.MockTransport(handle_request))

    first = downloader.download(PUBLIC_IMAGE_URL)
    second = downloader.download(PUBLIC_IMAGE_URL)

    assert first == DownloadedImage(content=ONE_PIXEL_PNG, suffix=".png")
    assert second is first
    assert requested_urls == [PUBLIC_IMAGE_URL, "https://93.184.216.34/final.png"]


def test_remote_image_downloader_rejects_private_network_addresses() -> None:
    downloader = RemoteImageDownloader(
        transport=httpx.MockTransport(lambda request: pytest.fail("不应发起网络请求"))
    )

    with pytest.raises(RemoteImageError, match="本机、局域网或保留网络地址"):
        downloader.download("http://127.0.0.1/private.png")


def test_remote_image_downloader_rechecks_redirect_targets() -> None:
    requested_urls: list[str] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private.png"})

    downloader = RemoteImageDownloader(transport=httpx.MockTransport(handle_request))

    with pytest.raises(RemoteImageError, match="本机、局域网或保留网络地址"):
        downloader.download(PUBLIC_IMAGE_URL)

    assert requested_urls == [PUBLIC_IMAGE_URL]


def test_remote_image_downloader_enforces_streaming_size_limit() -> None:
    oversized = b"x" * (MAX_REMOTE_IMAGE_BYTES + 1)
    downloader = RemoteImageDownloader(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=oversized)
        )
    )

    with pytest.raises(RemoteImageError, match="超过 10 MB"):
        downloader.download(PUBLIC_IMAGE_URL)


def test_remote_image_failure_keeps_placeholder_and_warning(tmp_path: Path, monkeypatch) -> None:
    def fail_download(self, url: str):
        raise RemoteImageError("模拟下载失败")

    monkeypatch.setattr(RemoteImageDownloader, "download", fail_download)
    converter = Md2DocxConverter(base_path=tmp_path, fonts=FontSettings())

    document = converter.convert(f"![network image]({PUBLIC_IMAGE_URL})")

    assert len(document.inline_shapes) == 0
    assert "[图片跳过: network image]" in "\n".join(
        paragraph.text for paragraph in document.paragraphs
    )
    assert any("网络图片下载失败" in warning for warning in converter.warnings)


def test_remote_image_warning_label_removes_query_credentials() -> None:
    assert remote_image_display_url(
        "https://user:secret@example.com/images/picture.png?token=sensitive#preview"
    ) == "https://example.com/images/picture.png"
