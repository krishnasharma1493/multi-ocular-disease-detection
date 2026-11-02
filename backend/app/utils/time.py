from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """SQLite drops the UTC offset; re-attach it before comparing with utcnow()."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
