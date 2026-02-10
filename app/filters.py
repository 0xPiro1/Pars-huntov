"""Country / region filter for Superteam Earn listings."""
from __future__ import annotations

GLOBAL_KEYWORDS = {"global", "worldwide", "remote", "online"}


def is_allowed(region: str | None) -> bool:
    """Return True if the listing should trigger a notification.

    Rules:
    - region is None / empty  -> allowed (no geo restriction)
    - region matches a global keyword -> allowed
    - region is a specific country   -> blocked
    """
    if not region:
        return True
    return region.strip().lower() in GLOBAL_KEYWORDS
