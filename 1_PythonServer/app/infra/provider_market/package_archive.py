from __future__ import annotations

from contextlib import suppress
import json
from pathlib import Path, PurePosixPath
import shutil
from stat import S_IFLNK, S_IFMT
from zipfile import BadZipFile, ZipFile, ZipInfo

from app.core.errors import BadRequestError
from app.repositories.llm.provider_adaptation_rules_repository import (
    ProviderAdaptationRulesRepository,
)
from app.repositories.llm.provider_catalog_repository import ProviderCatalogRepository
from app.repositories.llm.provider_custom_model_repository import ProviderCustomModelRepository
from app.repositories.llm.provider_file_store import ProviderFileStore, ProviderFileStoreError
from app.schemas.llm.provider_market import ProviderMarketEntry, ProviderPackageManifest


PROVIDER_PACKAGE_FILE_NAMES = {
    "manifest.json",
    "provider.json",
    "provider-rules.json",
    "model-rules.json",
    "models.json",
}
MAX_PACKAGE_FILES = len(PROVIDER_PACKAGE_FILE_NAMES)
MAX_SINGLE_FILE_BYTES = 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 4 * 1024 * 1024


class ProviderPackageArchive:
    def validate_and_extract(
        self,
        *,
        archive_path: Path,
        staging_root: Path,
        market_entry: ProviderMarketEntry,
    ) -> Path:
        package_root = staging_root / market_entry.id
        try:
            with ZipFile(archive_path) as archive:
                entries = [entry for entry in archive.infolist() if not entry.is_dir()]
                self._validate_entries(entries, provider_id=market_entry.id)
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
            raise BadRequestError("供应商压缩包格式无效。") from exc

        self._validate_package(package_root, market_entry=market_entry)
        return package_root

    def _validate_entries(self, entries: list[ZipInfo], *, provider_id: str) -> None:
        if len(entries) != MAX_PACKAGE_FILES:
            raise BadRequestError("供应商压缩包必须且只能包含五个正式 JSON 文件。")
        total_size = 0
        seen: set[str] = set()
        actual_names: set[str] = set()
        for entry in entries:
            path = PurePosixPath(entry.filename.replace("\\", "/"))
            if (
                path.is_absolute()
                or ".." in path.parts
                or len(path.parts) != 2
                or path.parts[0] != provider_id
            ):
                raise BadRequestError("供应商压缩包包含越界路径。")
            normalized = path.as_posix().casefold()
            if normalized in seen:
                raise BadRequestError("供应商压缩包包含重复文件。")
            seen.add(normalized)
            if entry.flag_bits & 0x1 or S_IFMT(entry.external_attr >> 16) == S_IFLNK:
                raise BadRequestError("供应商压缩包包含不允许的链接或加密文件。")
            if entry.file_size < 0 or entry.file_size > MAX_SINGLE_FILE_BYTES:
                raise BadRequestError("供应商压缩包包含过大的文件。")
            total_size += entry.file_size
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise BadRequestError("供应商压缩包解压大小超过允许范围。")
            actual_names.add(path.name)
        if actual_names != PROVIDER_PACKAGE_FILE_NAMES:
            raise BadRequestError("供应商压缩包文件不完整或包含未允许文件。")

    def _validate_package(
        self,
        package_root: Path,
        *,
        market_entry: ProviderMarketEntry,
    ) -> None:
        try:
            manifest = ProviderPackageManifest.model_validate_json(
                (package_root / "manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise BadRequestError("供应商 manifest.json 格式无效。") from exc
        if (
            manifest.id != market_entry.id
            or manifest.name != market_entry.name
            or manifest.version != market_entry.version
            or manifest.author.name != market_entry.author
            or manifest.summary != market_entry.summary
            or manifest.license != market_entry.license
            or manifest.compatibility != market_entry.compatibility
        ):
            raise BadRequestError("供应商 manifest.json 与市场索引不一致。")
        if len(manifest.managed_model_ids) != len(set(manifest.managed_model_ids)):
            raise BadRequestError("供应商包包含重复的托管模型 ID。")

        try:
            store = ProviderFileStore(package_root.parent)
            catalog = ProviderCatalogRepository(store)
            entry = catalog.get_entry(market_entry.id)
            if entry is None or entry.display_name != market_entry.name:
                raise ProviderFileStoreError("Provider package identity mismatch.")
            if entry.protocol_family.value != market_entry.protocol:
                raise ProviderFileStoreError("Provider package protocol mismatch.")
            models = ProviderCustomModelRepository(store).list_models(market_entry.id)
            model_ids = {model.model_id for model in models}
            if model_ids != set(manifest.managed_model_ids):
                raise ProviderFileStoreError("Provider package managed models mismatch.")
            ProviderAdaptationRulesRepository(store).resolve(
                provider_id=market_entry.id,
                model_id=None,
                expected_profile_id=entry.profile_id,
            )
        except (OSError, ValueError, ProviderFileStoreError) as exc:
            raise BadRequestError("供应商包中的定义或适配规则无效。") from exc

        for file_name in PROVIDER_PACKAGE_FILE_NAMES:
            try:
                payload = json.loads((package_root / file_name).read_text(encoding="utf-8"))
            except UnicodeDecodeError as exc:
                raise BadRequestError(f"{file_name} 必须是 UTF-8 JSON。") from exc
            except (OSError, ValueError) as exc:
                raise BadRequestError(f"供应商配置 {file_name} 无效。") from exc
            if not isinstance(payload, dict):
                raise BadRequestError(f"供应商配置 {file_name} 必须是 JSON 对象。")


def remove_provider_staging_path(path: Path, *, allowed_root: Path) -> None:
    resolved = path.resolve()
    root = allowed_root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("拒绝清理供应商下载目录之外的路径。") from exc
    if resolved.exists():
        with suppress(OSError):
            shutil.rmtree(resolved)
