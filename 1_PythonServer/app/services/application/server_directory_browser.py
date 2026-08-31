import os
from pathlib import Path

from app.core.errors import BadRequestError, NotFoundError


class ServerDirectoryBrowserService:
    def list_directories(self, path: str | None = None) -> dict[str, object]:
        directory = self._resolve_directory(path)
        try:
            children = [
                {
                    "name": entry.name,
                    "path": os.path.abspath(entry.path),
                }
                for entry in os.scandir(directory)
                if self._is_directory(entry)
            ]
        except OSError as error:
            raise BadRequestError(f"无法读取目录：{directory}") from error

        children.sort(key=lambda item: str(item["name"]).casefold())
        parent = directory.parent
        return {
            "path": str(directory),
            "parent_path": None if parent == directory else str(parent),
            "roots": self._roots(),
            "directories": children,
        }

    @staticmethod
    def _resolve_directory(path: str | None) -> Path:
        candidate = Path(path.strip()).expanduser() if path and path.strip() else Path.home()
        if path and path.strip() and not candidate.is_absolute():
            raise BadRequestError("请输入服务器文件夹的绝对路径。")
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise NotFoundError(f"目录不存在：{candidate}") from error
        if not resolved.is_dir():
            raise BadRequestError(f"路径不是文件夹：{resolved}")
        return resolved

    @staticmethod
    def _is_directory(entry: os.DirEntry[str]) -> bool:
        try:
            return entry.is_dir()
        except OSError:
            return False

    @staticmethod
    def _roots() -> list[dict[str, str]]:
        if os.name != "nt":
            return [{"name": "/", "path": "/"}]

        roots: list[dict[str, str]] = []
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            root = Path(f"{letter}:\\")
            if root.exists():
                roots.append({"name": f"{letter}:", "path": str(root)})
        return roots


_server_directory_browser_service = ServerDirectoryBrowserService()


def get_server_directory_browser_service() -> ServerDirectoryBrowserService:
    return _server_directory_browser_service
