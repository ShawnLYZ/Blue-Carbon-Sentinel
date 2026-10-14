"""UTC ISO 8601 timestamps with milliseconds and a trailing Z (addendum F2)."""

from __future__ import annotations

from datetime import UTC, datetime


def to_iso(dt: datetime) -> str:
    """Format an aware datetime as ``YYYY-MM-DDTHH:MM:SS.mmmZ`` (truncated to milliseconds)."""
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("naive datetime is not allowed; use a timezone-aware datetime")
    u = dt.astimezone(UTC)
    return f"{u:%Y-%m-%dT%H:%M:%S}.{u.microsecond // 1000:03d}Z"


def from_iso(s: str) -> datetime:
    """Parse an ISO 8601 string into an aware UTC datetime; naive input raises ValueError."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"timestamp has no timezone: {s!r}")
    return dt.astimezone(UTC)
