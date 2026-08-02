from __future__ import annotations

from contextlib import suppress
from pathlib import Path, PurePosixPath
import shutil
from stat import S_IFMT, S_IFLNK
from zipfile import BadZipFile, ZipFile, ZipInfo

from app.core.errors import BadRequestError


MAX_PACKAGE_FILES = 100_000
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_SINGLE_FILE_BYTES = 512 * 1024 * 1024


class ProjectPackageArchive:
    def validate_and_extract(
        self,
        *,
        archive_path: Path,
        staging_root: Path,
        source_path: str | None = None,
    ) -> Path:
        extracted_root = staging_root / "extracted"
        try:
            with ZipFile(archive_path) as archive:
                entries = archive.infolist()
                self._validate_entries(entries)
                for entry in entries:
                    if entry.is_dir():
                        continue
                    path = PurePosixPath(entry.filename.replace("\\", "/"))
                    target = extracted_root.joinpath(*path.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
        except BadRequestError:
            raise
        except (BadZipFile, KeyError, OSError, ValueError) as exc:
            raise BadRequestError("项目压缩包格式无效。") from exc

        repository_root = _single_outer_directory(extracted_root) or extracted_root
        if source_path is not None:
            relative = _safe_relative_path(source_path)
            project_root = repository_root.joinpath(*relative.parts)
            if not project_root.is_dir():
                raise BadRequestError("在线项目索引指定的仓库目录不存在。")
            return project_root
        return _single_outer_directory(extracted_root) or extracted_root

    @staticmethod
    def _validate_entries(entries: list[ZipInfo]) -> None:
        files = [entry for entry in entries if not entry.is_dir()]
        if not files or len(files) > MAX_PACKAGE_FILES:
            raise BadRequestError("项目压缩包文件数量超出允许范围。")
        seen: set[str] = set()
        total_size = 0
        for entry in entries:
            raw_name = entry.filename.replace("\\", "/")
            path = PurePosixPath(raw_name)
            if (
                not path.parts
                or path.is_absolute()
                or ".." in path.parts
                or ":" in path.parts[0]
            ):
                raise BadRequestError("项目压缩包包含越界路径。")
            normalized = path.as_posix().casefold()
            if normalized in seen:
                raise BadRequestError("项目压缩包包含重复文件。")
            seen.add(normalized)
            if entry.flag_bits & 0x1 or S_IFMT(entry.external_attr >> 16) == S_IFLNK:
                raise BadRequestError("项目压缩包包含不允许的链接或加密文件。")
            if entry.file_size < 0 or entry.file_size > MAX_SINGLE_FILE_BYTES:
                raise BadRequestError("项目压缩包包含过大的文件。")
            total_size += entry.file_size
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise BadRequestError("项目压缩包解压大小超过允许范围。")


def remove_project_market_staging_path(path: Path, *, allowed_root: Path) -> None:
    resolved = path.resolve()
    root = allowed_root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("拒绝清理项目市场缓存目录之外的路径。") from exc
    if resolved.exists():
        with suppress(OSError):
            shutil.rmtree(resolved)


def _single_outer_directory(root: Path) -> Path | None:
    if not root.is_dir():
        return None
    children = list(root.iterdir())
    if len(children) == 1 and children[0].is_dir() and not children[0].is_symlink():
        return children[0]
    return None


def _safe_relative_path(raw_path: str) -> PurePosixPath:
    path = PurePosixPath(raw_path.replace("\\", "/").strip("/"))
    if not path.parts or path.is_absolute() or ".." in path.parts:
        raise BadRequestError("在线项目仓库目录无效。")
    return path
