"""Complete or path-scoped snapshots with cooperative cancellation.

Directory boundaries are checked once before enumeration. DirEntry metadata
rejects links without resolving every ordinary file through all its ancestors.
"""
from concurrent.futures import CancelledError
import os
from pathlib import Path
from threading import Event

from app.domain.file_workspace import ContentFileEntry, ContentFileSnapshot
from app.infra.file_workspace.file_names import is_internal_write_temp_path


def content_snapshot(root_path: str, *, paths: tuple[str, ...] | None = None,
                     cancelled: Event | None = None) -> ContentFileSnapshot:
    root = Path(root_path).resolve()
    discovered: dict[str, tuple[int, ContentFileEntry]] = {}
    unreadable: set[str] = set()

    def check_cancelled():
        if cancelled is not None and cancelled.is_set():
            raise CancelledError("File scan has no remaining readers")

    def ignored(relative: Path):
        return (bool(relative.parts) and relative.parts[0].casefold() == '.tiance'
                or is_internal_write_temp_path(relative))

    def is_link(path):
        return path.is_symlink() or bool(getattr(path, 'is_junction', lambda: False)())

    def add(path: Path, stat):
        relative = path.relative_to(root).as_posix()
        discovered[relative] = (stat.st_mtime_ns, ContentFileEntry(
            name=path.name, path=relative, mtime_ms=stat.st_mtime_ns // 1_000_000))

    def scan(directory: Path):
        check_cancelled()
        try:
            if is_link(directory) or not directory.resolve().is_relative_to(root):
                return
            with os.scandir(directory) as entries:
                for entry in entries:
                    check_cancelled()
                    path = Path(entry.path)
                    if ignored(path.relative_to(root)):
                        continue
                    try:
                        if entry.is_symlink() or bool(getattr(entry, 'is_junction', lambda: False)()):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            scan(path)
                        elif entry.is_file(follow_symlinks=False):
                            add(path, entry.stat(follow_symlinks=False))
                    except OSError:
                        unreadable.add(path.relative_to(root).as_posix())
        except FileNotFoundError:
            pass  # A removed directory is an empty replacement scope.
        except OSError:
            unreadable.add(directory.relative_to(root).as_posix())

    if paths is None:
        scan(root)
    else:
        scopes: list[Path] = []
        for raw in sorted(set(paths), key=lambda value: (len(Path(value).parts), value)):
            check_cancelled()
            relative = Path(raw)
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('File scan paths must be workspace-relative')
            if ignored(relative):
                continue
            path = root / relative
            if any(path.is_relative_to(scope) for scope in scopes):
                continue
            scopes.append(path)
            try:
                # Check ancestors too: a changed path may sit beneath a junction.
                current = root
                blocked = False
                for part in relative.parts:
                    current /= part
                    if is_link(current):
                        blocked = True
                        break
                if blocked or not path.resolve().is_relative_to(root):
                    continue
                if path.is_dir():
                    scan(path)
                elif path.is_file():
                    add(path, path.stat())
            except OSError:
                unreadable.add(relative.as_posix())
    check_cancelled()
    ordered = sorted(discovered.values(), key=lambda item: (-item[0], item[1].path.casefold(), item[1].path))
    check_cancelled()
    return ContentFileSnapshot(items=tuple(item for _, item in ordered),
                               unreadable_paths=tuple(sorted(unreadable)))
