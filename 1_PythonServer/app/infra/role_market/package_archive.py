from __future__ import annotations

from contextlib import suppress
import json
from pathlib import Path, PurePosixPath
import shutil
from stat import S_IFLNK, S_IFMT
from zipfile import BadZipFile, ZipFile, ZipInfo

from app.core.errors import BadRequestError
from app.schemas.roles import (
    ROLE_CONFIGURATION_MODELS,
    ROLE_PACKAGE_FILE_NAMES,
    RoleMarketRoleEntry,
    RolePackageManifest,
)


MAX_PACKAGE_FILES = len(ROLE_PACKAGE_FILE_NAMES)
MAX_SINGLE_FILE_BYTES = 512 * 1024
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024


class RolePackageArchive:
    def validate_and_extract(
        self,
        *,
        archive_path: Path,
        staging_root: Path,
        market_entry: RoleMarketRoleEntry,
    ) -> Path:
        package_root = staging_root / market_entry.id
        try:
            with ZipFile(archive_path) as archive:
                entries = [entry for entry in archive.infolist() if not entry.is_dir()]
                self._validate_entries(entries, role_id=market_entry.id)
                for entry in entries:
                    relative = PurePosixPath(entry.filename.replace("\\", "/")).relative_to(
                        market_entry.id
                    )
                    target = package_root / relative.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output, length=64 * 1024)
        except BadRequestError:
            raise
        except (BadZipFile, KeyError, OSError, ValueError) as exc:
            raise BadRequestError("角色压缩包格式无效。") from exc

        self._validate_package(package_root, market_entry=market_entry)
        return package_root

    def _validate_entries(self, entries: list[ZipInfo], *, role_id: str) -> None:
        if len(entries) != MAX_PACKAGE_FILES:
            raise BadRequestError("角色压缩包必须且只能包含九个正式文件。")
        total_size = 0
        seen: set[str] = set()
        actual_names: set[str] = set()
        for entry in entries:
            path = PurePosixPath(entry.filename.replace("\\", "/"))
            if (
                path.is_absolute()
                or ".." in path.parts
                or len(path.parts) != 2
                or path.parts[0] != role_id
            ):
                raise BadRequestError("角色压缩包包含越界路径。")
            normalized = path.as_posix().casefold()
            if normalized in seen:
                raise BadRequestError("角色压缩包包含重复文件。")
            seen.add(normalized)
            if entry.flag_bits & 0x1 or S_IFMT(entry.external_attr >> 16) == S_IFLNK:
                raise BadRequestError("角色压缩包包含不允许的链接或加密文件。")
            if entry.file_size < 0 or entry.file_size > MAX_SINGLE_FILE_BYTES:
                raise BadRequestError("角色压缩包包含过大的文件。")
            total_size += entry.file_size
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise BadRequestError("角色压缩包解压大小超过允许范围。")
            actual_names.add(path.name)
        if actual_names != ROLE_PACKAGE_FILE_NAMES:
            raise BadRequestError("角色压缩包文件不完整或包含未允许文件。")

    def _validate_package(
        self,
        package_root: Path,
        *,
        market_entry: RoleMarketRoleEntry,
    ) -> None:
        try:
            manifest = RolePackageManifest.model_validate_json(
                (package_root / "manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise BadRequestError("角色 manifest.json 格式无效。") from exc
        if (
            manifest.id != market_entry.id
            or manifest.name != market_entry.name
            or manifest.version != market_entry.version
            or manifest.author.name != market_entry.author
            or manifest.summary != market_entry.summary
            or manifest.license != market_entry.license
            or manifest.compatibility != market_entry.compatibility
        ):
            raise BadRequestError("角色 manifest.json 与市场索引不一致。")

        for file_name, model in ROLE_CONFIGURATION_MODELS.items():
            path = package_root / file_name
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                model.model_validate(payload)
            except UnicodeDecodeError as exc:
                raise BadRequestError(f"{file_name} 必须是 UTF-8 JSON。") from exc
            except (OSError, ValueError) as exc:
                raise BadRequestError(f"角色配置 {file_name} 无效。") from exc


def remove_role_staging_path(path: Path, *, allowed_root: Path) -> None:
    resolved = path.resolve()
    root = allowed_root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("拒绝清理角色下载目录之外的路径。") from exc
    if resolved.exists():
        with suppress(OSError):
            shutil.rmtree(resolved)
