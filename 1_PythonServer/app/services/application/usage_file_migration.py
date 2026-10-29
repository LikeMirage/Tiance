from pathlib import Path

from app.repositories.llm.usage_sqlite_store import UsageSqliteStore


def ensure_usage_sqlite_storage(database_path: Path, usage_data_path: Path) -> None:
    """Import legacy usage before the global database removes its old tables."""
    UsageSqliteStore(usage_data_path).ensure_ready(legacy_database_path=database_path)
