"""Safe operational diagnostics; logging cannot change message delivery semantics."""
import asyncio
import logging

logger = logging.getLogger(__name__)
FIELDS = {'user_id', 'chat_id', 'project_id', 'session_id', 'update_id', 'job_id', 'http_status', 'error_type'}


async def record_activity(repository, event, *, level='info', error=None, **details):
    # Never store exception text/URLs, tokens, message bodies or full platform updates.
    safe = {k: v for k, v in details.items() if k in FIELDS and isinstance(v, (str, int))}
    if error is not None:
        safe['error_type'] = getattr(error, 'error_type', None) or type(error).__name__
        status = getattr(error, 'http_status', None) or getattr(getattr(error, 'response', None), 'status_code', None)
        if isinstance(status, int):
            safe['http_status'] = status
    try:
        await asyncio.to_thread(repository.append_activity, event, level, safe)
    except Exception:
        logger.warning('Mobile activity could not be recorded (%s).', event)
