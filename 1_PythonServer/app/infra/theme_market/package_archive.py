from __future__ import annotations

from contextlib import suppress
import json
from pathlib import Path, PurePosixPath
import shutil
from stat import S_IFMT, S_IFLNK
from zipfile import BadZipFile, ZipFile, ZipInfo

from PIL import Image, UnidentifiedImageError

from app.core.errors import BadRequestError
from app.schemas.themes import ThemeDefinition
from app.schemas.themes.theme_market import ThemeMarketThemeEntry


MAX_PACKAGE_FILES = 80
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_SINGLE_FILE_BYTES = 24 * 1024 * 1024
MAX_IMAGE_PIXELS = 50_000_000
ALLOWED_IMAGE_SUFFIXES = frozenset((".avif", ".jpeg", ".jpg", ".png", ".webp"))


class ThemePackageArchive:
    def validate_and_extract(
        self,
        *,
        archive_path: Path,
        staging_root: Path,
        market_entry: ThemeMarketThemeEntry,
    ) -> Path:
        package_root = staging_root / market_entry.id
        try:
            with ZipFile(archive_path) as archive:
                files = [entry for entry in archive.infolist() if not entry.is_dir()]
                self._validate_entries(files, theme_id=market_entry.id)
                for entry in files:
                    relative = PurePosixPath(entry.filename).relative_to(market_entry.id)
                    target = package_root.joinpath(*relative.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
        except (BadZipFile, KeyError, OSError, ValueError) as exc:
            raise BadRequestError("主题压缩包格式无效。") from exc

        self._validate_package(package_root, market_entry=market_entry)
        return package_root

    def _validate_entries(self, entries: list[ZipInfo], *, theme_id: str) -> None:
        if not entries or len(entries) > MAX_PACKAGE_FILES:
            raise BadRequestError("主题压缩包文件数量超出允许范围。")
        total_size = 0
        seen: set[str] = set()
        for entry in entries:
            path = PurePosixPath(entry.filename.replace("\\", "/"))
            if (
                path.is_absolute()
                or ".." in path.parts
                or len(path.parts) < 2
                or path.parts[0] != theme_id
            ):
                raise BadRequestError("主题压缩包包含越界路径。")
            normalized = path.as_posix()
            if normalized in seen:
                raise BadRequestError("主题压缩包包含重复文件。")
            seen.add(normalized)
            if entry.flag_bits & 0x1 or S_IFMT(entry.external_attr >> 16) == S_IFLNK:
                raise BadRequestError("主题压缩包包含不允许的链接或加密文件。")
            if entry.file_size < 0 or entry.file_size > MAX_SINGLE_FILE_BYTES:
                raise BadRequestError("主题压缩包包含过大的文件。")
            total_size += entry.file_size
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise BadRequestError("主题压缩包解压大小超过允许范围。")
            self._validate_package_path(path.relative_to(theme_id))

    @staticmethod
    def _validate_package_path(relative: PurePosixPath) -> None:
        if len(relative.parts) == 1:
            if (
                relative.name not in {"theme.json", "manifest.json"}
                and relative.suffix.lower() not in ALLOWED_IMAGE_SUFFIXES
            ):
                raise BadRequestError("主题压缩包含有不允许的顶层文件。")
            return
        if relative.parts[0] != "assets" or relative.suffix.lower() not in ALLOWED_IMAGE_SUFFIXES:
            raise BadRequestError("主题压缩包含有不允许的资源文件。")

    def _validate_package(
        self,
        package_root: Path,
        *,
        market_entry: ThemeMarketThemeEntry,
    ) -> None:
        theme_file = package_root / "theme.json"
        manifest_file = package_root / "manifest.json"
        if not theme_file.is_file() or not manifest_file.is_file():
            raise BadRequestError("主题包缺少 theme.json 或 manifest.json。")
        try:
            theme = ThemeDefinition.model_validate_json(theme_file.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BadRequestError("主题包配置无效。") from exc
        if theme.id != market_entry.id:
            raise BadRequestError("主题包 ID 与市场索引不一致。")
        self._validate_manifest(manifest, market_entry=market_entry, package_root=package_root)
        self._validate_theme_assets(theme, package_root=package_root)
        for image_file in package_root.rglob("*"):
            if image_file.is_file() and image_file.suffix.lower() in ALLOWED_IMAGE_SUFFIXES:
                self._validate_image(image_file)

    @staticmethod
    def _validate_manifest(
        manifest: object,
        *,
        market_entry: ThemeMarketThemeEntry,
        package_root: Path,
    ) -> None:
        if not isinstance(manifest, dict):
            raise BadRequestError("主题 manifest.json 格式无效。")
        author = manifest.get("author")
        base_colors = manifest.get("baseColors")
        preview = manifest.get("preview")
        compatibility = manifest.get("compatibility")
        if (
            manifest.get("schemaVersion") != 1
            or manifest.get("version") != market_entry.version
            or not isinstance(author, dict)
            or author.get("name") != market_entry.author
            or manifest.get("summary") != market_entry.summary
            or manifest.get("license") != market_entry.license
            or base_colors != market_entry.base_colors
            or not isinstance(preview, str)
            or not isinstance(compatibility, dict)
            or compatibility.get("themeSchemaVersion") != 2
        ):
            raise BadRequestError("主题 manifest.json 与市场索引不一致。")
        preview_path = PurePosixPath(preview.replace("\\", "/"))
        if preview_path.is_absolute() or ".." in preview_path.parts:
            raise BadRequestError("主题预览图路径无效。")
        target = package_root.joinpath(*preview_path.parts)
        if not target.is_file() or target.suffix.lower() not in ALLOWED_IMAGE_SUFFIXES:
            raise BadRequestError("主题包缺少合法预览图。")

    @staticmethod
    def _validate_theme_assets(theme: ThemeDefinition, *, package_root: Path) -> None:
        image = theme.tokens.background.image.strip().replace("\\", "/")
        if not image:
            return
        path = PurePosixPath(image)
        if path.is_absolute() or ".." in path.parts or path.parts[0] != "assets":
            raise BadRequestError("主题背景图路径无效。")
        target = package_root.joinpath(*path.parts)
        if not target.is_file() or target.suffix.lower() not in ALLOWED_IMAGE_SUFFIXES:
            raise BadRequestError("主题包缺少背景图资源。")

    @staticmethod
    def _validate_image(path: Path) -> None:
        try:
            with Image.open(path) as image:
                width, height = image.size
                if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
                    raise BadRequestError("主题图片尺寸超过允许范围。")
                image.verify()
        except BadRequestError:
            raise
        except (OSError, UnidentifiedImageError) as exc:
            raise BadRequestError("主题包包含无效图片。") from exc


def remove_theme_staging_path(path: Path, *, allowed_root: Path) -> None:
    resolved = path.resolve()
    root = allowed_root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("拒绝清理主题下载目录之外的路径。") from exc
    if resolved.exists():
        with suppress(OSError):
            shutil.rmtree(resolved)
