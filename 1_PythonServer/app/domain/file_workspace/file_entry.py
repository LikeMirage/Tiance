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
