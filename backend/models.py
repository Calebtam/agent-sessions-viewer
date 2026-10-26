"""Unified session helpers shared by provider-backed API responses."""

from datetime import datetime, timezone


CONTENT_STATUSES = {"full", "partial", "index_only", "error"}


def timestamp_fields(value):
    """Convert a millisecond epoch to API date/ISO fields without guessing."""
    if not isinstance(value, (int, float)):
        return "", None
    try:
        moment = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return "", None
    return moment.strftime("%Y/%m/%d"), moment.isoformat().replace("+00:00", "Z")


def validate_session(item):
    required = ("id", "provider", "title", "content_status", "has_transcript")
    missing = [field for field in required if field not in item]
    if missing:
        raise ValueError(f"missing unified session fields: {', '.join(missing)}")
    if item["content_status"] not in CONTENT_STATUSES:
        raise ValueError(f"invalid content status: {item['content_status']}")
    return item
