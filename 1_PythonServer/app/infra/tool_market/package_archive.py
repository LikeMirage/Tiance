from __future__ import annotations

from contextlib import suppress
import json
from pathlib import Path, PurePosixPath
import shutil
from stat import S_IFLNK, S_IFMT
from zipfile import BadZipFile, ZipFile, ZipInfo

from app.core.errors import BadRequestError
from app.schemas.tools.tool_market import ToolMarketEntry, ToolPackageManifest
from app.services.tools.tool_metadata import load_tool


MAX_PACKAGE_FILES = 2_000
MAX_SINGLE_FILE_BYTES = 32 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
REQUIRED_FILES = {
    "manifest.json",
    ".tool/tool.json",
    ".tool/input.schema.json",
    ".tool/output.schema.json",
    ".tool/examples.json",
}
LOCAL_ONLY_PARTS = {".tiance", "dependencies", "__pycache__", ".git"}


class ToolPackageArchive:
    def validate_and_extract(
        self,
        *,
        archive_path: Path,
        staging_root: Path,
        market_entry: ToolMarketEntry,
    ) -> Path:
        package_root = staging_root / market_entry.id
        try:
            with ZipFile(archive_path) as archive:
                entries = [entry for entry in archive.infolist() if not entry.is_dir()]
                self._validate_entries(entries, tool_id=market_entry.id)
                for entry in entries:
                    path = PurePosixPath(entry.filename.replace("\\", "/"))
                    relative = path.relative_to(market_entry.id)
                    target = package_root.joinpath(*relative.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output, length=64 * 1024)
        except BadRequestError:
            raise
        except (BadZipFile, KeyError, OSError, ValueError) as exc:
            raise BadRequestError("工具压缩包格式无效。") from exc

        self._validate_package(package_root, market_entry=market_entry)
        return package_root

    def _validate_entries(self, entries: list[ZipInfo], *, tool_id: str) -> None:
        if not entries or len(entries) > MAX_PACKAGE_FILES:
            raise BadRequestError("工具压缩包文件数量无效。")
        total_size = 0
        seen: set[str] = set()
        actual_files: set[str] = set()
        for entry in entries:
            path = PurePosixPath(entry.filename.replace("\\", "/"))
            if (
                path.is_absolute()
                or ".." in path.parts
                or len(path.parts) < 2
                or path.parts[0] != tool_id
            ):
                raise BadRequestError("工具压缩包包含越界路径。")
            relative = PurePosixPath(*path.parts[1:])
            if any(part.casefold() in LOCAL_ONLY_PARTS for part in relative.parts):
                raise BadRequestError("工具压缩包包含本地工作状态或依赖缓存。")
            if relative.suffix.casefold() == ".pyc":
                raise BadRequestError("工具压缩包不能包含 Python 缓存文件。")
            normalized = relative.as_posix().casefold()
            if normalized in seen:
                raise BadRequestError("工具压缩包包含重复文件。")
            seen.add(normalized)
            if entry.flag_bits & 0x1 or S_IFMT(entry.external_attr >> 16) == S_IFLNK:
                raise BadRequestError("工具压缩包包含不允许的链接或加密文件。")
            if entry.file_size < 0 or entry.file_size > MAX_SINGLE_FILE_BYTES:
                raise BadRequestError("工具压缩包包含过大的文件。")
            total_size += entry.file_size
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise BadRequestError("工具压缩包解压大小超过允许范围。")
            actual_files.add(relative.as_posix())
        if not REQUIRED_FILES.issubset(actual_files):
            raise BadRequestError("工具压缩包缺少 manifest.json 或标准 .tool 文件。")

    def _validate_package(
        self,
        package_root: Path,
        *,
        market_entry: ToolMarketEntry,
    ) -> None:
        try:
            manifest = ToolPackageManifest.model_validate_json(
                (package_root / "manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise BadRequestError("工具 manifest.json 格式无效。") from exc
        if (
            manifest.id != market_entry.id
            or manifest.version != market_entry.version
            or manifest.author.name != market_entry.author
            or manifest.license != market_entry.license
            or manifest.compatibility != market_entry.compatibility
        ):
            raise BadRequestError("工具 manifest.json 与市场索引不一致。")

        try:
            loaded = load_tool(package_root)
        except (OSError, ValueError, BadRequestError) as exc:
            raise BadRequestError("工具包中的运行定义无效。") from exc
        runtime = loaded.manifest.get("runtime")
        runtime_type = runtime.get("type") if isinstance(runtime, dict) else None
        display_name = loaded.manifest.get("display_name")
        description = loaded.manifest.get("description")
        if (
            loaded.name != market_entry.call_name
            or display_name != market_entry.display_name
            or description != market_entry.summary
            or runtime_type != market_entry.runtime
        ):
            raise BadRequestError("工具运行定义与市场索引不一致。")
        if runtime_type == "python":
            entry = runtime.get("entry") if isinstance(runtime, dict) else None
            if not isinstance(entry, str) or not (package_root / entry).is_file():
                raise BadRequestError("Python 工具缺少有效运行入口。")


def remove_tool_market_staging_path(path: Path, *, allowed_root: Path) -> None:
    resolved = path.resolve()
    root = allowed_root.resolve()
    if resolved == root or root not in resolved.parents:
        raise RuntimeError("工具市场临时目录越界。")
    with suppress(OSError):
        if resolved.exists():
            shutil.rmtree(resolved)
