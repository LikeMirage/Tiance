"""One-time, streaming import. The source ledger remains an untouched backup."""
from hashlib import sha256
from contextlib import closing
import json
import logging
import os
from pathlib import Path
import sqlite3

from app.repositories.llm.usage_file_store import USAGE_EVENTS_FILE, _record_from_payload

logger = logging.getLogger(__name__)


def _signature(stat):
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def import_legacy_usage(db, root: Path, legacy_database: Path | None, upsert, delete_model):
    path = root / USAGE_EVENTS_FILE
    if path.is_file() and path.stat().st_size:
        digest, count = sha256(), 0
        with path.open('rb') as source:
            initial = _signature(os.fstat(source.fileno()))
            for line_number, raw in enumerate(source, 1):
                digest.update(raw)
                if not raw.strip():
                    continue
                try:
                    event = json.loads(raw.decode('utf-8'))
                except (ValueError, UnicodeDecodeError) as exc:
                    if raw.endswith(b'\n'):
                        raise ValueError(f'Invalid usage event JSON at line {line_number}.') from exc
                    # Only a torn final line may be excluded. Keep both original
                    # ledger and a separately identified copy of the torn bytes.
                    backup = path.with_name(f'{path.name}.{sha256(raw).hexdigest()}.corrupt-tail')
                    if backup.exists():
                        if backup.read_bytes() != raw:
                            raise ValueError('Usage tail backup differs from the source.')
                    else:
                        with backup.open('xb') as out:
                            out.write(raw)
                            out.flush()
                            os.fsync(out.fileno())
                    logger.warning('Incomplete legacy usage event at line %s preserved in %s; importing complete events only.', line_number, backup)
                    break
                if not isinstance(event, dict) or event.get('version') != 1:
                    raise ValueError(f'Invalid usage event at line {line_number}.')
                if event.get('operation') == 'upsert':
                    upsert(db, _record_from_payload(event.get('record'), line_number=line_number))
                elif event.get('operation') == 'delete_model':
                    provider, model = event.get('provider_id'), event.get('model_id')
                    if not isinstance(provider, str) or not isinstance(model, str):
                        raise ValueError(f'Invalid usage delete event at line {line_number}.')
                    delete_model(db, provider, model)
                else:
                    raise ValueError(f'Unknown usage event operation at line {line_number}.')
                count += 1
            if initial != _signature(os.fstat(source.fileno())) or initial != _signature(path.stat()):
                raise RuntimeError('Usage ledger changed during migration; retry after the old writer stops.')
        metadata = {'path': str(path), 'sha256': digest.hexdigest(), 'events': count, 'bytes': initial[2]}
    elif legacy_database is not None and legacy_database.is_file():
        count = 0
        with closing(sqlite3.connect(legacy_database.resolve().as_uri() + '?mode=ro', uri=True)) as source:
            source.row_factory = sqlite3.Row
            try:
                source.execute('BEGIN')
                if source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='llm_usage_records'").fetchone():
                    for row in source.execute('SELECT * FROM llm_usage_records ORDER BY created_at,usage_id'):
                        payload = dict(row)
                        payload.setdefault('usage_feature_key', 'main_chat')
                        upsert(db, _record_from_payload(payload, line_number=count + 1))
                        count += 1
            finally:
                source.rollback()
        metadata = {'path': str(legacy_database), 'records': count}
    else:
        metadata = {'source': 'new-ledger'}
    db.execute('INSERT INTO usage_meta(key,value) VALUES (?,?)', ('legacy_source', json.dumps(metadata)))
