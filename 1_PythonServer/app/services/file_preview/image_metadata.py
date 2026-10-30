"""Standalone image metadata. Pixel decoding belongs to the native browser."""
from pathlib import Path
import struct
from typing import BinaryIO

from . import policy


def inspect_standalone_image(path: Path) -> tuple[int, int]:
    from PIL import Image
    file_size = path.stat().st_size
    with path.open('rb') as stream:
        signature = stream.read(12)
        stream.seek(0)
        # These Pillow plugins load the complete file or an icon bitmap even
        # during open(). Read their container headers instead.
        if signature[:4] == b'RIFF' and signature[8:12] == b'WEBP':
            width, height, frames = _webp(stream, file_size)
        elif signature[:4] == b'\x00\x00\x01\x00':
            width, height, frames = _icon(stream, file_size)
        else:
            # One request per disposable process; restore the decoder guard on
            # every exit. No load(), resize() or bitmap copies in this path.
            previous_limit = Image.MAX_IMAGE_PIXELS
            Image.MAX_IMAGE_PIXELS = None
            try:
                with Image.open(stream) as image:
                    width, height = image.size
                    frames = getattr(image, 'n_frames', 1)
            finally:
                Image.MAX_IMAGE_PIXELS = previous_limit
    if width < 1 or height < 1 or frames < 1:
        raise ValueError('图片尺寸或帧数无效。')
    if frames > 1:
        if file_size > policy.MAX_IMAGE_BYTES:
            raise policy.PreviewLimit('动画文件超过 32 MiB，请用默认应用打开。')
        if width * height * frames > policy.MAX_IMAGE_PIXELS * 2:
            raise policy.PreviewLimit('动画累计帧像素超过 4800 万，停止内置解码。')
    return width, height


def _read(stream: BinaryIO, size: int) -> bytes:
    value = stream.read(size)
    if len(value) != size:
        raise ValueError('图片头部或目录不完整。')
    return value


def _webp(stream: BinaryIO, file_size: int) -> tuple[int, int, int]:
    header = _read(stream, 12)
    end = struct.unpack_from('<I', header, 4)[0] + 8
    if end < 12 or end > file_size:
        raise ValueError('WebP 文件长度无效。')
    width = height = frames = 0
    animated = False
    while stream.tell() < end:
        if end - stream.tell() < 8:
            raise ValueError('WebP 区块头不完整。')
        kind, size = struct.unpack('<4sI', _read(stream, 8))
        next_chunk = stream.tell() + size + (size & 1)
        if next_chunk > end:
            raise ValueError('WebP 区块超出文件范围。')
        if kind == b'VP8X' and size >= 10:
            data = _read(stream, 10)
            animated = bool(data[0] & 2)
            width = int.from_bytes(data[4:7], 'little') + 1
            height = int.from_bytes(data[7:10], 'little') + 1
        elif kind == b'VP8 ' and size >= 10 and not width:
            data = _read(stream, 10)
            if data[3:6] != b'\x9d\x01\x2a':
                raise ValueError('WebP 帧头无效。')
            width, height = (value & 0x3fff for value in struct.unpack_from('<HH', data, 6))
        elif kind == b'VP8L' and size >= 5 and not width:
            data = _read(stream, 5)
            if data[0] != 0x2f:
                raise ValueError('WebP 帧头无效。')
            packed = int.from_bytes(data[1:], 'little')
            width, height = (packed & 0x3fff) + 1, ((packed >> 14) & 0x3fff) + 1
        elif kind == b'ANMF':
            if size < 16:
                raise ValueError('WebP 动画帧头不完整。')
            frames += 1
        stream.seek(next_chunk)
    return width, height, frames if animated else 1


def _icon(stream: BinaryIO, file_size: int) -> tuple[int, int, int]:
    _, _, count = struct.unpack('<HHH', _read(stream, 6))
    directory_end = 6 + count * 16
    if not count or directory_end > file_size:
        raise ValueError('ICO 图片目录无效。')
    width = height = 0
    for _ in range(count):
        entry = _read(stream, 16)
        size, offset = struct.unpack_from('<II', entry, 8)
        if not size or offset < directory_end or offset + size > file_size:
            raise ValueError('ICO 图片资源超出文件范围。')
        w, h = entry[0] or 256, entry[1] or 256
        if w * h > width * height:
            width, height = w, h
    return width, height, 1
