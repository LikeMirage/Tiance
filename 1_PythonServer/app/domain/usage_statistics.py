from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.errors import BadRequestError


@dataclass(frozen=True)
class StatisticsMonth:
    month: str
    zone: ZoneInfo
    dates: tuple[str, ...]
    bounds: tuple[tuple[str, str], ...]

    @classmethod
    def parse(cls, month: str, timezone: str) -> "StatisticsMonth":
        if not re.fullmatch(r"\d{4}-\d{2}", month):
            raise BadRequestError("月份格式应为 YYYY-MM。")
        try:
            year, number = map(int, month.split("-"))
            if not 1 <= year <= 9998:
                raise ValueError
            zone = ZoneInfo(timezone)
            first = datetime(year, number, 1, tzinfo=zone)
            days = monthrange(year, number)[1]
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise BadRequestError("月份或时区无效。") from exc
        boundaries = tuple(first + timedelta(days=index) for index in range(days + 1))
        return cls(
            month, zone,
            tuple(value.date().isoformat() for value in boundaries[:-1]),
            tuple((start.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat())
                  for start, end in zip(boundaries, boundaries[1:])),
        )

    def day_index(self, timestamp: str) -> int | None:
        value = datetime.fromisoformat(timestamp)
        if value.tzinfo is None:
            raise ValueError("Usage timestamps must include a timezone.")
        local = value.astimezone(self.zone)
        if local.strftime("%Y-%m") != self.month:
            return None
        return local.day - 1
