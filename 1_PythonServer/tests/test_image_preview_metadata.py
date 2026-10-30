"""Image inspection must not decode a second copy before native rendering."""
from io import BytesIO
import struct

import pytest
from PIL import Image, ImageFile

from app.services.file_preview import policy
from app.services.file_preview.image_metadata import _icon, _webp
from app.services.file_preview.inspection import inspect_file


@pytest.mark.parametrize("extension", ["png", "jpg", "bmp", "gif"])
def test_static_metadata_does_not_decode_pixels(tmp_path, monkeypatch, extension):
    path = tmp_path / f"image.{extension}"
    Image.new("RGB", (20, 16)).save(path)
    def forbid_decode(*_args, **_kwargs):
        pytest.fail("metadata inspection decoded the bitmap")
    monkeypatch.setattr(ImageFile.ImageFile, "load", forbid_decode)
    result = inspect_file(path)
    assert (result["width"], result["height"]) == (20, 16)


@pytest.mark.parametrize("extension,options", [
    ("webp", {}), ("webp", {"lossless": True}),
    ("webp", {"exif": b"Exif\x00\x00"}),  # Extended VP8X container.
    ("ico", {}), ("ico", {"bitmap_format": "bmp"}),
])
def test_webp_and_ico_metadata_skip_pillow_full_file_loading(tmp_path, monkeypatch, extension, options):
    path = tmp_path / f"image.{extension}"
    Image.new("RGB", (32, 32)).save(path, **options)
    def forbid_open(*_args, **_kwargs):
        pytest.fail("WebP/ICO open would load the full resource")
    monkeypatch.setattr(Image, "open", forbid_open)
    monkeypatch.setattr(policy, "MAX_IMAGE_PIXELS", 1)
    monkeypatch.setattr(policy, "MAX_IMAGE_BYTES", 1)
    result = inspect_file(path)
    assert (result["width"], result["height"]) == (32, 32)
    # Readers consume bounded headers, never an unbounded read of the resource.
    class HeadersOnly(BytesIO):
        def read(self, size=-1):
            assert 0 <= size <= 16
            return super().read(size)
    data = path.read_bytes()
    reader = _webp if extension == "webp" else _icon
    assert reader(HeadersOnly(data), len(data)) == (32, 32, 1)


@pytest.mark.parametrize("extension", ["gif", "webp", "png"])
def test_animated_images_keep_frame_and_file_budgets(tmp_path, monkeypatch, extension):
    path = tmp_path / f"animation.{extension}"
    frames = [Image.new("RGB", (2, 2), color) for color in ("red", "green", "blue")]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=100)
    assert inspect_file(path)["mode"] == "inline"
    monkeypatch.setattr(policy, "MAX_IMAGE_PIXELS", 4)
    with pytest.raises(policy.PreviewLimit, match="累计"):
        inspect_file(path)
    monkeypatch.setattr(policy, "MAX_IMAGE_PIXELS", 24_000_000)
    monkeypatch.setattr(policy, "MAX_IMAGE_BYTES", 1)
    with pytest.raises(policy.PreviewLimit, match="动画文件"):
        inspect_file(path)


@pytest.mark.parametrize("extension", ["webp", "ico"])
def test_truncated_container_metadata_fails_explicitly(tmp_path, extension):
    path = tmp_path / f"broken.{extension}"
    Image.new("RGB", (32, 32)).save(path)
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(ValueError, match="长度|范围"):
        inspect_file(path)


def test_webp_rejects_chunk_outside_declared_container():
    data = b"RIFF" + struct.pack("<I", 12) + b"WEBPVP8X" + struct.pack("<I", 10)
    with pytest.raises(ValueError, match="区块超出"):
        _webp(BytesIO(data), len(data))
