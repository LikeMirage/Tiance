from dataclasses import dataclass
from typing import Literal

FileEntryKind = Literal["file", "folder"]


@dataclass(frozen=True, slots=True)
class FileEntryNode:
    """受控文件工作区中的一个文件或文件夹节点。"""

    id: str
    name: str
    path: str
    kind: FileEntryKind
    has_children: bool = False
    mtime_ms: int | None = None
    children: tuple["FileEntryNode", ...] = ()


@dataclass(frozen=True, slots=True)
class FileEntryTree:
    """受控文件工作区列表结果。"""

    items: tuple[FileEntryNode, ...]


@dataclass(frozen=True, slots=True)
class ContentFileEntry:
    """项目内容范围内的普通文件快照。"""

    name: str
    path: str
    mtime_ms: int


@dataclass(frozen=True, slots=True)
class ContentFileSnapshot:
    """完整内容文件列表及扫描期间无法读取的路径。"""

    items: tuple[ContentFileEntry, ...]
    unreadable_paths: tuple[str, ...] = ()
