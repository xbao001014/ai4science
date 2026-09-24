"""Display SQLite UTC timestamps in Beijing time."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


BEIJING_TIME = timezone(timedelta(hours=8))


def format_beijing_time(value: str | None) -> str:
    """Format a SQLite CURRENT_TIMESTAMP value without changing stored UTC data."""
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(BEIJING_TIME).strftime("%Y-%m-%d %H:%M:%S")
