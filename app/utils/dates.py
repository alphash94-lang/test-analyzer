from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    """Return a timezone-aware current timestamp in Asia/Seoul."""

    return datetime.now(tz=SEOUL)


def ensure_kst(value: datetime) -> datetime:
    """Normalize an aware datetime to Asia/Seoul and reject naive values."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime is required")
    return value.astimezone(SEOUL)


def restore_database_kst(value: datetime) -> datetime:
    """Restore SQLite KST wall-clock values; normalize aware DB values."""

    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=SEOUL)
    return value.astimezone(SEOUL)
