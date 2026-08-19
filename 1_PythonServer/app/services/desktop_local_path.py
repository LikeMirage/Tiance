from functools import lru_cache
from pathlib import Path

from app.core.errors import BadRequestError
from app.infra.file_explorer import (
    FileExplorerOpenError,
    open_path_with_default_application,
    reveal_path_in_file_explorer,
)


class DesktopLocalPathService:
    """处理用户明确触发的本地路径动作，不参与消息或工具数据结构。"""

    def reveal(self, raw_path: str) -> None:
        target = self._resolve_absolute_path(raw_path)
        try:
            reveal_path_in_file_explorer(target)
        except FileExplorerOpenError as exc:
            raise BadRequestError("无法在资源管理器中定位该路径。") from exc

    def open_default(self, raw_path: str) -> None:
        target = self._resolve_absolute_path(raw_path)
        try:
            open_path_with_default_application(target)
        except FileExplorerOpenError as exc:
            raise BadRequestError("无法使用系统默认应用打开该路径。") from exc

    @staticmethod
    def _resolve_absolute_path(raw_path: str) -> Path:
        path = Path(raw_path.strip()).expanduser()
        if not path.is_absolute():
            raise BadRequestError("本地路径操作只接受绝对路径。")
        try:
            return path.resolve(strict=True)
        except OSError as exc:
            raise BadRequestError("文件或文件夹不存在。") from exc


@lru_cache(maxsize=1)
def get_desktop_local_path_service() -> DesktopLocalPathService:
    return DesktopLocalPathService()
