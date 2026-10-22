from datetime import UTC, datetime
from functools import lru_cache
import os
from pathlib import Path
import stat
from threading import Lock
from time import monotonic

from app.repositories.project.project_repository import ProjectRepository, get_project_repository
from app.repositories.project.conversation_database import DATABASE_FILE
from app.repositories.project.conversation_storage import WORKSPACE_DIR

CACHE_SECONDS = 300
SCAN_SECONDS = 2
MAX_ENTRIES = 50_000
_DATABASE_FILES = {DATABASE_FILE, f"{DATABASE_FILE}-wal", f"{DATABASE_FILE}-shm", f"{DATABASE_FILE}-journal"}


class WorkspaceStorageService:
    """On-demand metadata-only accounting of registered projects' private data."""

    def __init__(self, projects: ProjectRepository) -> None:
        self._projects = projects
        self._lock = Lock()
        self._cached: dict | None = None
        self._cached_at = float("-inf")

    def get_storage(self) -> dict:
        with self._lock:
            if self._cached is not None and monotonic() - self._cached_at < CACHE_SECONDS:
                return self._cached
            result = self._scan()
            self._cached = result
            self._cached_at = monotonic()
            return result

    def _scan(self) -> dict:
        # Do not use the conversation workspace resolver: it may create/upgrade DBs.
        roots = {os.path.normcase(os.path.abspath(Path(project.root_path) / WORKSPACE_DIR))
                 for project in self._projects.list_projects()}
        pending = list(sorted(roots))
        visited: set[str] = set()
        deadline = monotonic() + SCAN_SECONDS
        total = database = entries_read = 0
        complete = True
        while pending:
            if monotonic() >= deadline or entries_read >= MAX_ENTRIES:
                complete = False
                break
            directory = pending.pop()
            if directory in visited:
                continue
            visited.add(directory)
            try:
                info = os.stat(directory, follow_symlinks=False)
                if _is_link(info) or not stat.S_ISDIR(info.st_mode):
                    complete = False
                    continue
                with os.scandir(directory) as children:
                    for child in children:
                        if monotonic() >= deadline or entries_read >= MAX_ENTRIES:
                            complete = False
                            pending.clear()
                            break
                        entries_read += 1
                        try:
                            info = child.stat(follow_symlinks=False)
                            if _is_link(info):
                                complete = False
                            elif stat.S_ISDIR(info.st_mode):
                                pending.append(os.path.normcase(child.path))
                            elif stat.S_ISREG(info.st_mode):
                                total += info.st_size
                                if directory in roots and child.name in _DATABASE_FILES:
                                    database += info.st_size
                        except FileNotFoundError:
                            # Attachments and SQLite sidecars can disappear mid-scan.
                            continue
                        except OSError:
                            complete = False
            except FileNotFoundError:
                continue
            except OSError:
                complete = False
        return {"total_bytes": total, "database_bytes": database, "other_bytes": total - database,
                "complete": complete, "sampled_at": datetime.now(UTC).isoformat()}


def _is_link(info: os.stat_result) -> bool:
    # Skip symlinks and Windows junctions/reparse points instead of following them.
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


@lru_cache
def get_workspace_storage_service() -> WorkspaceStorageService:
    return WorkspaceStorageService(get_project_repository())
