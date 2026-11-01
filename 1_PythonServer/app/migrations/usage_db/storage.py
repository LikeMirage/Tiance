"""Replay old ledgers separately, then merge into the current transactional ledger."""

from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from app.domain.llm.usage import LlmUsageRecord
from app.migrations.runner import backup_database, schema_transaction
from app.migrations.usage_db.legacy_import import import_legacy_usage
from app.repositories.llm.usage_sqlite_store import UsageSqliteStore, RECORD_FIELDS


def upgrade_usage_storage(root: Path, legacy_database: Path | None = None) -> None:
    store = UsageSqliteStore(root)
    store.ensure_ready()
    with store._connect() as db, schema_transaction(db):
        has_meta = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='usage_meta'").fetchone()
        if has_meta and db.execute("SELECT 1 FROM usage_meta WHERE key='migration_complete' AND value='1'").fetchone():
            return
        # Replay deletions against historical rows only, never against post-upgrade usage.
        with TemporaryDirectory(prefix="tiance-usage-upgrade-") as directory:
            with closing(sqlite3.connect(Path(directory) / "replay.db")) as staging:
                staging.row_factory = sqlite3.Row
                store._create_schema(staging)
                staging.execute("CREATE TABLE usage_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
                import_legacy_usage(staging, root, legacy_database, store._upsert, store._delete_model)
                store._verify_totals(staging)
                if staging.execute("SELECT 1 FROM usage_records LIMIT 1").fetchone() or db.execute("SELECT 1 FROM usage_records LIMIT 1").fetchone():
                    backup_database(db, "usage-import", 1)
                for row in staging.execute("SELECT * FROM usage_records ORDER BY ordinal"):
                    exists = db.execute(
                        "SELECT 1 FROM usage_records WHERE usage_id=? OR identity_key=?",
                        (row["usage_id"], row["identity_key"]),
                    ).fetchone()
                    if exists is None:
                        store._upsert(db, LlmUsageRecord(**{key: row[key] for key in RECORD_FIELDS}))
                store._verify_totals(db)
                db.execute("CREATE TABLE IF NOT EXISTS usage_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
                metadata = staging.execute("SELECT value FROM usage_meta WHERE key='legacy_source'").fetchone()[0]
                db.execute("INSERT OR REPLACE INTO usage_meta VALUES ('legacy_source',?)", (metadata,))
                db.execute("INSERT OR REPLACE INTO usage_meta VALUES ('migration_complete','1')")
