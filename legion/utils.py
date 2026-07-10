"""Small shared helpers for the legion cog."""

import re
from datetime import datetime, timedelta

from maki.cogs.legion.constants import PATCH_ETA_MINUTES, PATCH_FREEZE_MINUTES
from maki.cogs.legion.strings import DEFAULT_LEGION_NAME, DEFAULT_PLAYER_NAME

PLAYER_NAME_MAX = 16
LEGION_NAME_MAX = 24

# Keep English letters, digits, spaces, and CJK (unified ideographs +
# extension A). Everything else is stripped.
_ALLOWED = re.compile(r"[^a-zA-Z0-9 一-鿿㐀-䶿]+")


def clean_name(raw: str, max_len: int, default: str) -> str:
    """Sanitize a display name: allowed charset only, collapsed whitespace,
    capped length; falls back to ``default`` if nothing survives."""
    cleaned = _ALLOWED.sub("", raw or "")
    cleaned = " ".join(cleaned.split())[:max_len].strip()
    return cleaned or default


def clean_player_name(raw: str) -> str:
    return clean_name(raw, PLAYER_NAME_MAX, DEFAULT_PLAYER_NAME)


def clean_legion_name(raw: str) -> str:
    return clean_name(raw, LEGION_NAME_MAX, DEFAULT_LEGION_NAME)


# --- patch timeline ----------------------------------------------------------

def next_hour(now: datetime) -> datetime:
    """Start of the next full hour."""
    return (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)


def patch_timeline(now: datetime) -> tuple[datetime, datetime]:
    """``(lock_at, apply_at)`` for an update scheduled right now."""
    lock_at = next_hour(now)
    return lock_at, lock_at + timedelta(minutes=PATCH_ETA_MINUTES)


def patch_phase(lock_at: datetime, apply_at: datetime, now: datetime) -> str:
    """'scheduled' (nothing blocked) | 'locked' (session commands blocked) |
    'frozen' (ALL commands blocked) | 'due' (apply now)."""
    if now >= apply_at:
        return "due"
    if now >= apply_at - timedelta(minutes=PATCH_FREEZE_MINUTES):
        return "frozen"
    if now >= lock_at:
        return "locked"
    return "scheduled"
