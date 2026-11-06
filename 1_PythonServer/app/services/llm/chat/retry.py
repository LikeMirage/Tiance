"""Provider-independent timing for ordinary failed-request retries."""
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import asyncio
import math

import httpx


def retry_after_seconds(error: Exception, *, now: datetime | None = None) -> float:
    if not isinstance(error, httpx.HTTPStatusError):
        return 0
    value = error.response.headers.get("Retry-After", "").strip()
    if not value:
        return 0
    try:
        seconds = float(value)
    except ValueError:
        try:
            deadline = parsedate_to_datetime(value)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=UTC)
            seconds = (deadline - (now or datetime.now(UTC))).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return 0
    return max(0, seconds) if math.isfinite(seconds) else 0


async def wait_for_upstream_retry(configured_seconds: int, provider_seconds: float = 0) -> None:
    # No hidden backoff, upper bound or additional attempts. A standard provider
    # minimum may extend the user's interval; cancellation interrupts the sleep.
    delay = max(configured_seconds, provider_seconds)
    if delay > 0:
        await asyncio.sleep(delay)
