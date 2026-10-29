"""Independent usage ledger and transactionally maintained, rebuildable totals."""
from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import asdict, fields, replace
from datetime import UTC, datetime
import json
import logging
from math import isclose
from pathlib import Path
import sqlite3
from threading import RLock

from app.domain.llm.usage import LlmUsageRecord
from app.domain.usage_statistics import StatisticsMonth

USAGE_DATABASE_FILE = 'usage.db'
TOKEN_FIELDS = ('prompt_tokens', 'completion_tokens', 'total_tokens', 'reasoning_tokens',
                'prompt_cache_hit_tokens', 'prompt_cache_miss_tokens')
SUM_FIELDS = (*TOKEN_FIELDS, 'cost_amount', 'record_count', 'estimated_record_count')
RECORD_FIELDS = tuple(field.name for field in fields(LlmUsageRecord))
GROUP_FIELDS = ('scope', 'scope_id', 'provider_id', 'model_id', 'usage_feature_key', 'currency_key')
GROUP_WHERE = ' AND '.join(f'{name} = ?' for name in GROUP_FIELDS)
logger = logging.getLogger(__name__)


def timestamp_us(value: str) -> int:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('Usage timestamps must include a timezone.')
    delta = parsed.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def session_key(project_id: str, session_id: str) -> str:
    return json.dumps([project_id, session_id], ensure_ascii=False, separators=(',', ':'))


def _usage_identity(record: LlmUsageRecord) -> str | None:
    # Each model request has one usage identity.
    return f'request:{record.request_id}' if record.request_id else record.message_id


def _groups(record: LlmUsageRecord) -> list[tuple[str, ...]]:
    suffix = (record.provider_id, record.model_id, record.usage_feature_key, json.dumps(record.cost_currency))
    result = [('model', '', *suffix)]
    if record.project_id is not None and record.session_id is not None:
        result.append(('session', session_key(record.project_id, record.session_id), *suffix))
    return result


class UsageSqliteStore:
    def __init__(self, root_path: Path) -> None:
        self.root_path = root_path
        self.database_path = root_path / USAGE_DATABASE_FILE
        self._ready = False
        self._lock = RLock()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.root_path.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.database_path, timeout=30)
        try:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA cache_size = -2048')
            db.execute('PRAGMA temp_store = FILE')
            db.execute('PRAGMA synchronous = FULL')
            db.execute('PRAGMA wal_autocheckpoint = 256')
            db.execute('PRAGMA journal_size_limit = 4194304')
            yield db
        finally:
            db.close()

    def ensure_ready(self) -> None:
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            with self._connect() as db:
                # auto_vacuum must be set before the first schema transaction.
                # One snapshot distinguishes an empty new database from old data;
                # the authoritative version check still happens under the lock.
                empty = db.execute("""SELECT
                    (SELECT user_version FROM pragma_user_version) = 0
                    AND NOT EXISTS (SELECT 1 FROM sqlite_master
                        WHERE type='table' AND name NOT LIKE 'sqlite_%')""").fetchone()[0]
                if empty:
                    db.execute('PRAGMA auto_vacuum = INCREMENTAL')
                # Different store instances can open the same new database.
                # Read its version and tables under the same initialization lock.
                db.execute('BEGIN IMMEDIATE')
                try:
                    version = db.execute('PRAGMA user_version').fetchone()[0]
                    if version not in (0, 1):
                        raise ValueError(f'Unsupported usage database version: {version}')
                    if version == 0:
                        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1").fetchone():
                            raise ValueError('Unsupported usage database without a schema version. No data was converted or removed.')
                        self._create_schema(db)
                        db.execute('PRAGMA user_version = 1')
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
                db.execute('PRAGMA journal_mode = WAL')
            self._ready = True

    @staticmethod
    def _create_schema(db: sqlite3.Connection) -> None:
        numeric = ', '.join(f'{name} INTEGER NOT NULL' for name in TOKEN_FIELDS)
        db.execute(f'''CREATE TABLE IF NOT EXISTS usage_records (
            ordinal INTEGER PRIMARY KEY AUTOINCREMENT, usage_id TEXT NOT NULL UNIQUE,
            identity_key TEXT UNIQUE, request_id TEXT, project_id TEXT, session_id TEXT,
            message_id TEXT, provider_id TEXT NOT NULL, model_id TEXT NOT NULL,
            usage_feature_key TEXT NOT NULL, {numeric}, cost_amount REAL, cost_currency TEXT,
            currency_key TEXT NOT NULL, is_estimated INTEGER NOT NULL,
            created_at TEXT NOT NULL, created_at_us INTEGER NOT NULL)''')
        db.execute('CREATE INDEX IF NOT EXISTS usage_records_session ON usage_records(project_id, session_id, ordinal)')
        db.execute('CREATE INDEX IF NOT EXISTS usage_records_model ON usage_records(provider_id, model_id, usage_feature_key, currency_key)')
        db.execute('CREATE INDEX IF NOT EXISTS usage_records_time ON usage_records(created_at_us, total_tokens)')
        db.execute(f'''CREATE TABLE IF NOT EXISTS usage_totals (
            scope TEXT NOT NULL, scope_id TEXT NOT NULL, provider_id TEXT NOT NULL,
            model_id TEXT NOT NULL, usage_feature_key TEXT NOT NULL, currency_key TEXT NOT NULL,
            cost_currency TEXT, {numeric}, cost_amount REAL NOT NULL,
            record_count INTEGER NOT NULL, estimated_record_count INTEGER NOT NULL,
            latest_created_at TEXT NOT NULL, first_ordinal INTEGER NOT NULL,
            PRIMARY KEY (scope, scope_id, provider_id, model_id, usage_feature_key, currency_key)) WITHOUT ROWID''')
        db.execute('CREATE INDEX IF NOT EXISTS usage_totals_model ON usage_totals(provider_id, model_id)')

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        self.ensure_ready()
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def append_upsert(self, record: LlmUsageRecord) -> None:
        with self.transaction(write=True) as db:
            self._upsert(db, record)

    @classmethod
    def _upsert(cls, db: sqlite3.Connection, incoming: LlmUsageRecord) -> None:
        identity = _usage_identity(incoming)
        existing = db.execute('SELECT * FROM usage_records WHERE identity_key = ?', (identity,)).fetchone() if identity is not None else None
        # Records without request/message identity are keyed by usage ID.
        if existing is None:
            existing = db.execute('SELECT * FROM usage_records WHERE usage_id = ?', (incoming.usage_id,)).fetchone()
        previous = LlmUsageRecord(**{key: existing[key] for key in RECORD_FIELDS}) if existing is not None else None
        record = incoming
        if previous is not None and identity is not None and existing['identity_key'] == identity:
            # Replacement preserves the first observation's ownership and time.
            changed = (*TOKEN_FIELDS, 'provider_id', 'model_id', 'usage_feature_key', 'cost_amount', 'cost_currency', 'is_estimated')
            record = replace(previous, **{key: getattr(incoming, key) for key in changed})
        payload = asdict(record)
        payload.update(identity_key=_usage_identity(record), currency_key=json.dumps(record.cost_currency), created_at_us=timestamp_us(record.created_at))
        if previous is None:
            columns = tuple(payload)
            cursor = db.execute(f"INSERT INTO usage_records ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", tuple(payload.values()))
            ordinal = cursor.lastrowid
        else:
            ordinal = existing['ordinal']
            db.execute(f"UPDATE usage_records SET {','.join(key + '=?' for key in payload)} WHERE ordinal=?", (*payload.values(), ordinal))
            cls._adjust(db, previous, ordinal, -1)
        cls._adjust(db, record, ordinal, 1)
        if previous is not None:
            changed_groups = set(_groups(previous)) - set(_groups(record))
            if previous.created_at != record.created_at:
                changed_groups.update(_groups(previous))
            for group in changed_groups:
                cls._refresh_bounds(db, group)

    @staticmethod
    def _adjust(db: sqlite3.Connection, record: LlmUsageRecord, ordinal: int, sign: int) -> None:
        values = [getattr(record, key) for key in TOKEN_FIELDS] + [record.cost_amount or 0, 1, int(record.is_estimated)]
        for group in _groups(record):
            if sign < 0:
                db.execute(f"UPDATE usage_totals SET {','.join(name + '=' + name + '-?' for name in SUM_FIELDS)} WHERE {GROUP_WHERE}", (*values, *group))
                db.execute(f'DELETE FROM usage_totals WHERE {GROUP_WHERE} AND record_count=0', group)
            else:
                columns = (*GROUP_FIELDS, *SUM_FIELDS, 'cost_currency', 'latest_created_at', 'first_ordinal')
                updates = ','.join(f'{name}={name}+excluded.{name}' for name in SUM_FIELDS)
                db.execute(f"INSERT INTO usage_totals ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
                           f"ON CONFLICT DO UPDATE SET {updates},latest_created_at=MAX(latest_created_at,excluded.latest_created_at),first_ordinal=MIN(first_ordinal,excluded.first_ordinal)",
                           (*group, *values, record.cost_currency, record.created_at, ordinal))

    @staticmethod
    def _refresh_bounds(db: sqlite3.Connection, group: tuple[str, ...]) -> None:
        scope, scope_id, provider, model, feature, currency = group
        where = 'provider_id=? AND model_id=? AND usage_feature_key=? AND currency_key=?'
        args = [provider, model, feature, currency]
        if scope == 'session':
            where += ' AND project_id=? AND session_id=?'
            args.extend(json.loads(scope_id))
        bounds = db.execute(f'SELECT MAX(created_at),MIN(ordinal) FROM usage_records WHERE {where}', args).fetchone()
        if bounds[0] is not None:
            db.execute(f'UPDATE usage_totals SET latest_created_at=?,first_ordinal=? WHERE {GROUP_WHERE}', (*bounds, *group))

    def append_delete_model(self, *, provider_id: str, model_id: str) -> None:
        with self.transaction(write=True) as db:
            self._delete_model(db, provider_id, model_id)
        try:
            self.maintain()
        except sqlite3.OperationalError:
            # Deletion is committed; a busy maintenance pass must not disguise
            # its success. Freed pages are still reusable by future writes.
            logger.warning('Usage storage maintenance deferred.', exc_info=True)

    @staticmethod
    def _delete_model(db: sqlite3.Connection, provider_id: str, model_id: str) -> None:
        args = (provider_id, model_id)
        db.execute('DELETE FROM usage_records WHERE provider_id=? AND model_id=?', args)
        db.execute('DELETE FROM usage_totals WHERE provider_id=? AND model_id=?', args)

    def model_totals(self, provider_id: str | None = None) -> tuple[sqlite3.Row, ...]:
        with self.transaction() as db:
            clause, args = (" AND provider_id=?", (provider_id,)) if provider_id is not None else ('', ())
            return tuple(db.execute("SELECT * FROM usage_totals WHERE scope='model' AND scope_id=''" + clause + ' ORDER BY first_ordinal', args))

    def session_totals(self, project_sessions: dict[str, tuple[str, ...]]) -> dict[str, dict[str, tuple[sqlite3.Row, ...]]]:
        result = {project: {} for project in project_sessions}
        if not any(project_sessions.values()):
            return result
        with self.transaction() as db:
            for project, sessions in project_sessions.items():
                for session in dict.fromkeys(sessions):
                    rows = tuple(db.execute("SELECT * FROM usage_totals WHERE scope='session' AND scope_id=? ORDER BY first_ordinal", (session_key(project, session),)))
                    if rows:
                        result[project][session] = rows
        return result

    def monthly_statistics(self, month: StatisticsMonth) -> dict:
        with self.transaction() as db:
            total = db.execute("SELECT COALESCE(SUM(total_tokens),0) FROM usage_totals WHERE scope='model'").fetchone()[0]
            top = db.execute("SELECT provider_id,model_id,SUM(total_tokens) AS value FROM usage_totals WHERE scope='model' GROUP BY provider_id,model_id HAVING value>0 ORDER BY value DESC,provider_id,model_id LIMIT 3").fetchall()
            daily = [db.execute('SELECT COALESCE(SUM(total_tokens),0) FROM usage_records WHERE created_at_us>=? AND created_at_us<?', (timestamp_us(start), timestamp_us(end))).fetchone()[0] for start, end in month.bounds]
        return {'total': total, 'daily': daily, 'top_models': [dict(row) for row in top]}

    def iter_records(self) -> Iterator[LlmUsageRecord]:
        """Streaming export/verification; ordinary queries never read all details."""
        with self.transaction() as db:
            for row in db.execute('SELECT * FROM usage_records ORDER BY ordinal'):
                values = {key: row[key] for key in RECORD_FIELDS}
                values['is_estimated'] = bool(values['is_estimated'])
                yield LlmUsageRecord(**values)

    @staticmethod
    def _verify_totals(db: sqlite3.Connection) -> None:
        # Verify each group, not just global sums: a misplaced session/model
        # would otherwise pass the check. Stream the grouped cursor so startup
        # never retains the complete usage history in Python memory.
        sums = ','.join(f'SUM({key}) AS {key}' for key in TOKEN_FIELDS)
        for scope, condition in [('model', ''), ('session', 'WHERE project_id IS NOT NULL AND session_id IS NOT NULL')]:
            grouping = 'provider_id,model_id,usage_feature_key,currency_key'
            if scope == 'session':
                grouping = 'project_id,session_id,' + grouping
            count = 0
            for raw in db.execute(f'''SELECT {grouping},{sums},
                COALESCE(SUM(cost_amount),0) AS cost_amount,COUNT(*) AS record_count,
                SUM(is_estimated) AS estimated_record_count,
                MAX(created_at) AS latest_created_at,MIN(ordinal) AS first_ordinal
                FROM usage_records {condition} GROUP BY {grouping}'''):
                scope_id = session_key(raw['project_id'], raw['session_id']) if scope == 'session' else ''
                key = (scope, scope_id, raw['provider_id'], raw['model_id'], raw['usage_feature_key'], raw['currency_key'])
                total = db.execute(f'SELECT * FROM usage_totals WHERE {GROUP_WHERE}', key).fetchone()
                exact_fields = (*TOKEN_FIELDS, 'record_count', 'estimated_record_count', 'latest_created_at', 'first_ordinal')
                if (total is None or any(raw[field] != total[field] for field in exact_fields)
                        or not isclose(raw['cost_amount'], total['cost_amount'], rel_tol=1e-9, abs_tol=1e-9)):
                    raise RuntimeError('Usage validation totals did not match the preserved details.')
                count += 1
            if db.execute('SELECT COUNT(*) FROM usage_totals WHERE scope=?', (scope,)).fetchone()[0] != count:
                raise RuntimeError('Usage validation contains totals without matching details.')
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise RuntimeError('Usage database integrity check failed.')

    def rebuild_totals(self) -> None:
        """Explicit repair from preserved facts; never reprice or replay backups."""
        with self.transaction(write=True) as db:
            db.execute('DELETE FROM usage_totals')
            for row in db.execute('SELECT * FROM usage_records ORDER BY ordinal'):
                record = LlmUsageRecord(**{key: row[key] for key in RECORD_FIELDS})
                self._adjust(db, record, row['ordinal'], 1)
            self._verify_totals(db)

    def maintain(self, *, full: bool = False) -> None:
        """Explicit/after-deletion maintenance, never performed per usage write."""
        self.ensure_ready()
        with self._connect() as db:
            db.execute('PRAGMA wal_checkpoint(PASSIVE)')
            if full:
                db.execute('VACUUM')
            elif db.execute('PRAGMA freelist_count').fetchone()[0] >= 256:
                db.execute('PRAGMA incremental_vacuum(256)').fetchall()
