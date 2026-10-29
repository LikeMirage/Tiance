from pathlib import Path


def is_direct_workspace_directory(path: Path, workspace_root: Path) -> bool:
    """Automatic discovery accepts real immediate children, never directory links."""
    try:
        return (
            path.parent == workspace_root
            and not path.is_symlink()
            and not path.is_junction()
            and path.is_dir()
            and path.resolve().parent == workspace_root
        )
    except (OSError, RuntimeError):
        return False
