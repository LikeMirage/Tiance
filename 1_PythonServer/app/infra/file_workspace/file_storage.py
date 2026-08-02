# 受控文件工作区存储
# 在指定根目录内执行目录列表、文件创建、文件删除等操作
# 所有方法均接收 workspace_root 参数，自身不持有路径状态

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.core.errors import BadRequestError, ConflictError
from app.domain.file_workspace import FileEntryKind, FileEntryNode, FileEntryTree
from app.infra.file_workspace.file_names import is_internal_write_temp_path

_IGNORED_RECURSIVE_SEARCH_DIR_NAMES = {
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    ".venv",
    "venv",
    ".trash",
}


@dataclass(slots=True)
class ExternalOpenResult:
    app_name: str
    used_default_app: bool


class FileWorkspaceStorage:
    """受控文件工作区存储：无状态，每次操作接收 workspace_root"""

    def list_tree(
        self,
        workspace_root: str,
        *,
        query: str | None = None,
        parent_path: str | None = None,
    ) -> tuple[FileEntryNode, ...]:
        """列出目录内容；query 非空时递归搜索，否则只返回 parent_path 下一层"""
        return self.list_tree_result(
            workspace_root,
            query=query,
            parent_path=parent_path,
        ).items

    def list_tree_result(
        self,
        workspace_root: str,
        *,
        query: str | None = None,
        parent_path: str | None = None,
    ) -> FileEntryTree:
        """列出目录内容；query 非空时递归搜索，否则只返回 parent_path 下一层。"""
        root = Path(workspace_root).resolve()
        if not root.is_dir():
            return FileEntryTree(items=())

        normalized_query = query.strip() if query else ""
        if normalized_query:
            return FileEntryTree(
                items=self._search_tree(root, root, normalized_query.lower()),
            )

        scope = _resolve_within_root(root, parent_path) if parent_path else root
        if not scope.is_dir():
            return FileEntryTree(items=())
        return FileEntryTree(items=self._list_one_level(scope, root))

    def create_entry(
        self,
        workspace_root: str,
        *,
        parent_path: str | None,
        kind: FileEntryKind,
        name: str | None,
    ) -> FileEntryNode:
        """在指定目录下创建文件或文件夹"""
        root = Path(workspace_root).resolve()
        parent = _resolve_within_root(root, parent_path) if parent_path else root
        if not parent.is_dir():
            parent.mkdir(parents=True, exist_ok=True)

        normalized_name = _validate_entry_name(name) if name else _default_entry_name(kind)
        target = _resolve_within_root(root, str(parent / normalized_name))

        if kind == "folder":
            target.mkdir(parents=True, exist_ok=False)
        else:
            target.touch(exist_ok=False)

        return _build_file_node(target, root)

    def rename_entry(
        self,
        workspace_root: str,
        *,
        target_path: str,
        name: str,
    ) -> FileEntryNode:
        """重命名工作区内的文件或文件夹"""
        root = Path(workspace_root).resolve()
        current_path = _resolve_within_root(root, target_path)
        if not current_path.exists():
            raise FileNotFoundError("文件或文件夹不存在。")
        next_name = _validate_entry_name(name)
        next_path = (current_path.parent / next_name).resolve()
        if next_path != root and root not in next_path.parents:
            raise BadRequestError("路径超出工作区目录范围。")
        if next_path.exists():
            raise BadRequestError("同名文件已存在。")
        current_path.rename(next_path)
        return _build_file_node(next_path, root)

    def delete_entry(self, workspace_root: str, target_path: str) -> None:
        """删除工作区内的文件或目录"""
        root = Path(workspace_root).resolve()
        target = _resolve_within_root(root, target_path)
        if not target.exists():
            return
        try:
            if target.is_dir():
                _remove_directory_tree(target)
            else:
                _remove_file(target)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ConflictError(
                "文件或文件夹无法删除，可能正被其他程序占用或当前没有删除权限。",
                details={"reason": "entry_in_use_or_access_denied"},
            ) from exc

    def move_entry(
        self,
        workspace_root: str,
        *,
        target_path: str,
        target_parent_path: str | None,
    ) -> FileEntryNode:
        """移动工作区内的文件或目录到目标目录"""
        root = Path(workspace_root).resolve()
        target = _resolve_existing_entry(root, target_path)
        target_parent = _resolve_directory(root, target_parent_path)
        _ensure_valid_move(target, target_parent)

        next_path = target_parent / target.name
        if next_path.exists():
            raise BadRequestError("目标目录中已存在同名条目。")

        shutil.move(str(target), str(next_path))
        return _build_file_node(next_path.resolve(), root)

    def copy_entry(
        self,
        workspace_root: str,
        *,
        target_path: str,
        target_parent_path: str | None,
    ) -> FileEntryNode:
        """复制工作区内的文件或目录到目标目录"""
        root = Path(workspace_root).resolve()
        target = _resolve_existing_entry(root, target_path)
        target_parent = _resolve_directory(root, target_parent_path)

        if target.is_dir() and (target_parent == target or target in target_parent.parents):
            raise BadRequestError("不能复制目录到自身或其子目录。")

        next_path = target_parent / target.name
        if next_path.exists():
            next_path = _resolve_copy_path(target_parent, target.name)

        if target.is_dir():
            shutil.copytree(target, next_path)
        else:
            shutil.copy2(target, next_path)

        return _build_file_node(next_path.resolve(), root)

    def reveal_entry(self, workspace_root: str, target_path: str) -> None:
        """在系统资源管理器中显示工作区内文件或目录"""
        root = Path(workspace_root).resolve()
        target = root if not target_path.strip() else _resolve_existing_entry(root, target_path)

        if sys.platform == "win32":
            if target.is_file():
                subprocess.Popen(["explorer", "/select,", str(target)])
            else:
                os.startfile(str(target))  # type: ignore[attr-defined]
            return

        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, str(target if target.is_dir() else target.parent)])

    def open_entry_external(self, workspace_root: str, target_path: str) -> ExternalOpenResult:
        """使用本机 Office/WPS 或系统默认程序打开工作区内文件。"""
        root = Path(workspace_root).resolve()
        target = _resolve_existing_entry(root, target_path)
        if not target.is_file():
            raise BadRequestError("仅支持打开文件。")

        if sys.platform == "win32":
            app = _find_windows_office_app(target.suffix.lower())
            if app is not None:
                try:
                    subprocess.Popen(
                        [str(app.executable_path), str(target)],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except OSError as exc:
                    raise BadRequestError(f"无法用 {app.label} 打开文件。") from exc
                return ExternalOpenResult(app_name=app.label, used_default_app=False)

            try:
                os.startfile(str(target))  # type: ignore[attr-defined]
            except OSError as exc:
                raise BadRequestError("无法用系统默认程序打开文件。") from exc
            return ExternalOpenResult(app_name="系统默认程序", used_default_app=True)

        opener = "open" if sys.platform == "darwin" else "xdg-open"
        try:
            subprocess.Popen(
                [opener, str(target)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise BadRequestError("无法用系统默认程序打开文件。") from exc
        return ExternalOpenResult(app_name="系统默认程序", used_default_app=True)

    def read_text_file(self, workspace_root: str, target_path: str) -> tuple[str, int]:
        """读取文本文件内容及修改时间（毫秒）"""
        root = Path(workspace_root).resolve()
        file_path = _resolve_within_root(root, target_path)
        if not file_path.is_file():
            raise FileNotFoundError("文件不存在。")
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise BadRequestError("无法读取非文本文件。")
        mtime_ms = int(file_path.stat().st_mtime * 1000)
        return content, mtime_ms

    def resolve_file_path(self, workspace_root: str, target_path: str) -> Path:
        """解析工作区内文件路径，用于受控只读资源访问。"""
        root = Path(workspace_root).resolve()
        file_path = _resolve_within_root(root, target_path)
        if not file_path.is_file():
            raise FileNotFoundError("文件不存在。")
        return file_path

    def write_text_file(
        self,
        workspace_root: str,
        target_path: str,
        content: str,
        expected_mtime_ms: int | None = None,
    ) -> FileEntryNode:
        """写入文本文件内容（同目录临时文件替换，避免读到半写入内容）。"""
        root = Path(workspace_root).resolve()
        file_path = _resolve_within_root(root, target_path)
        if expected_mtime_ms is not None:
            if not file_path.is_file():
                raise ConflictError("文件已被外部删除，请重新打开后再保存。")
            current_mtime_ms = int(file_path.stat().st_mtime * 1000)
            if current_mtime_ms != expected_mtime_ms:
                raise ConflictError("文件已在外部发生变化，请重新加载后再保存。")
        if not file_path.parent.is_dir():
            file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = file_path.with_name(f".{file_path.name}.{uuid4().hex}.tmp")
        try:
            tmp_path.write_text(content, encoding="utf-8")
            atomic_replace_path(tmp_path, file_path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
        return _build_file_node(file_path, root, include_mtime=True)

    def write_binary_file(
        self,
        workspace_root: str,
        target_path: str,
        content: bytes,
    ) -> FileEntryNode:
        """写入二进制文件（同目录临时文件替换，避免读到半写入内容）。"""
        root = Path(workspace_root).resolve()
        file_path = _resolve_within_root(root, target_path)
        if not file_path.parent.is_dir():
            file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = file_path.with_name(f".{file_path.name}.{uuid4().hex}.tmp")
        try:
            tmp_path.write_bytes(content)
            atomic_replace_path(tmp_path, file_path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
        return _build_file_node(file_path, root, include_mtime=True)

    def entry_exists(self, workspace_root: str, target_path: str) -> bool:
        """检查工作区内条目是否存在。"""
        root = Path(workspace_root).resolve()
        return _resolve_within_root(root, target_path).exists()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _list_one_level(
        self,
        scope: Path,
        root: Path,
    ) -> tuple[FileEntryNode, ...]:
        nodes: list[FileEntryNode] = []
        try:
            entries = sorted(scope.iterdir(), key=_sort_key)
        except OSError:
            return ()
        for entry in entries:
            if is_internal_write_temp_path(entry):
                continue
            nodes.append(_build_file_node(entry, root))
        return tuple(nodes)

    def _search_tree(
        self,
        scope: Path,
        root: Path,
        query: str,
    ) -> tuple[FileEntryNode, ...]:
        results: list[FileEntryNode] = []
        try:
            entries = sorted(scope.iterdir(), key=_sort_key)
        except OSError:
            return ()
        for entry in entries:
            if is_internal_write_temp_path(entry):
                continue
            if entry.is_dir():
                if entry.name in _IGNORED_RECURSIVE_SEARCH_DIR_NAMES:
                    continue
                children = self._search_tree(entry, root, query)
                if children:
                    node = _build_file_node(entry, root)
                    results.append(
                        FileEntryNode(
                            id=node.id,
                            name=node.name,
                            path=node.path,
                            kind=node.kind,
                            has_children=True,
                            children=children,
                        )
                    )
                elif query in entry.name.lower():
                    results.append(_build_file_node(entry, root))
            elif query in entry.name.lower():
                results.append(_build_file_node(entry, root))
        return tuple(results)


# ------------------------------------------------------------------
# 模块级辅助函数
# ------------------------------------------------------------------

def _resolve_within_root(root: Path, relative: str) -> Path:
    """解析相对路径并确保落在 root 内"""
    resolved = (root / relative).resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError("Path is outside the workspace directory.")
    return resolved


def _resolve_directory(root: Path, relative: str | None) -> Path:
    directory = _resolve_within_root(root, relative or "")
    if not directory.is_dir():
        raise FileNotFoundError("目标目录不存在。")
    return directory


def _resolve_existing_entry(root: Path, relative: str) -> Path:
    target = _resolve_within_root(root, relative)
    if target == root or not target.exists():
        raise FileNotFoundError("文件或文件夹不存在。")
    return target


def _build_file_node(entry: Path, root: Path, *, include_mtime: bool = False) -> FileEntryNode:
    relative = entry.relative_to(root).as_posix()
    mtime_ms = int(entry.stat().st_mtime * 1000) if include_mtime and entry.is_file() else None
    return FileEntryNode(
        id=relative,
        name=entry.name,
        path=relative,
        kind="folder" if entry.is_dir() else "file",
        has_children=entry.is_dir() and _directory_has_children(entry),
        mtime_ms=mtime_ms,
    )


def _directory_has_children(directory: Path) -> bool:
    try:
        return any(not is_internal_write_temp_path(entry) for entry in directory.iterdir())
    except OSError:
        return False


@dataclass(frozen=True, slots=True)
class _WindowsExternalApp:
    label: str
    executable_path: Path


def _find_windows_office_app(extension: str) -> _WindowsExternalApp | None:
    candidates = {
        ".doc": (
            ("Microsoft Word", ("WINWORD.EXE",)),
            ("WPS Writer", ("wps.exe",)),
        ),
        ".docx": (
            ("Microsoft Word", ("WINWORD.EXE",)),
            ("WPS Writer", ("wps.exe",)),
        ),
        ".xls": (
            ("Microsoft Excel", ("EXCEL.EXE",)),
            ("WPS Spreadsheets", ("et.exe",)),
        ),
        ".xlsx": (
            ("Microsoft Excel", ("EXCEL.EXE",)),
            ("WPS Spreadsheets", ("et.exe",)),
        ),
        ".ppt": (
            ("Microsoft PowerPoint", ("POWERPNT.EXE",)),
            ("WPS Presentation", ("wpp.exe",)),
        ),
        ".pptx": (
            ("Microsoft PowerPoint", ("POWERPNT.EXE",)),
            ("WPS Presentation", ("wpp.exe",)),
        ),
    }.get(extension.lower(), ())

    for label, executable_names in candidates:
        executable_path = _find_windows_executable(executable_names)
        if executable_path is not None:
            return _WindowsExternalApp(label=label, executable_path=executable_path)
    return None


def _find_windows_executable(executable_names: tuple[str, ...]) -> Path | None:
    for executable_name in executable_names:
        registry_path = _find_windows_app_path_from_registry(executable_name)
        if registry_path is not None:
            return registry_path
        path_value = shutil.which(executable_name)
        if path_value:
            return Path(path_value)
    return None


def _find_windows_app_path_from_registry(executable_name: str) -> Path | None:
    if sys.platform != "win32":
        return None

    try:
        import winreg
    except ImportError:
        return None

    subkeys = (
        rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{executable_name}",
        rf"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\{executable_name}",
    )
    roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    access_flags = (winreg.KEY_READ, winreg.KEY_READ | winreg.KEY_WOW64_64KEY, winreg.KEY_READ | winreg.KEY_WOW64_32KEY)

    for root in roots:
        for subkey in subkeys:
            for access_flag in access_flags:
                try:
                    with winreg.OpenKey(root, subkey, 0, access_flag) as key:
                        value, _ = winreg.QueryValueEx(key, "")
                except OSError:
                    continue
                if isinstance(value, str) and value.strip():
                    candidate = Path(value.strip('"')).expanduser()
                    if candidate.is_file():
                        return candidate
    return None


def _sort_key(entry: Path) -> tuple[int, str]:
    is_dir = entry.is_dir()
    return (0 if is_dir else 1, entry.name.lower())


def _validate_entry_name(name: str) -> str:
    """校验文件名：不允许为空、包含路径分隔符、或为 . / .."""
    stripped = name.strip()
    if not stripped:
        raise BadRequestError("文件名称不能为空。")
    if "/" in stripped or "\\" in stripped:
        raise BadRequestError("文件名称不能包含路径分隔符。")
    if stripped in (".", ".."):
        raise BadRequestError("不允许使用 . 或 .. 作为名称。")
    return stripped


def _ensure_valid_move(target: Path, target_parent: Path) -> None:
    if target.parent == target_parent:
        raise BadRequestError("目标目录与当前目录相同。")
    if target.is_dir() and (target_parent == target or target in target_parent.parents):
        raise BadRequestError("不能移动目录到自身或其子目录。")


def _resolve_copy_path(target_parent: Path, name: str) -> Path:
    original = Path(name)
    stem = original.stem
    suffix = original.suffix
    index = 2
    while True:
        candidate = target_parent / f"{stem} 副本 {index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _default_entry_name(kind: FileEntryKind) -> str:
    return "新建文件夹" if kind == "folder" else "新建文件.txt"


def _remove_directory_tree(directory: Path) -> None:
    import shutil
    shutil.rmtree(str(directory))


def _remove_file(file_path: Path) -> None:
    file_path.unlink()


@lru_cache
def get_file_workspace_storage() -> FileWorkspaceStorage:
    return FileWorkspaceStorage()
