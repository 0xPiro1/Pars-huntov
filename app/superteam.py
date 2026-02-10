"""Superteam Earn API client."""
from __future__ import annotations

import logging
from typing import Any

import requests

log = logging.getLogger(__name__)

BASE = "https://superteam.fun/api"
LISTING_URL_TPL = "https://superteam.fun/listings/{slug}/{type}"
TIMEOUT = 30


def fetch_listings() -> list[dict[str, Any]]:
    """Return all listings from /api/listings."""
    try:
        resp = requests.get(f"{BASE}/listings", timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        log.warning("Unexpected listings response type: %s", type(data))
        return []
    except Exception:
        log.exception("Failed to fetch listings")
        return []


def fetch_detail(slug: str) -> dict[str, Any] | None:
    """Return full listing detail (has `region` field)."""
    try:
        resp = requests.get(f"{BASE}/listings/details/{slug}", timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        log.exception("Failed to fetch detail for %s", slug)
        return None


def normalise(item: dict[str, Any], detail: dict[str, Any] | None) -> dict[str, Any]:
    """Build a flat dict ready for DB upsert + notification."""
    slug = item.get("slug", "")
    listing_type = item.get("type", "bounty")

    region = None
    if detail:
        region = detail.get("region") or None

    return {
        "id": item.get("id") or slug,
        "tab": listing_type,
        "title": item.get("title", ""),
        "slug": slug,
        "url": LISTING_URL_TPL.format(slug=slug, type=listing_type),
        "region": region,
        "is_global": region is None or region.strip().lower() in {
            "global", "worldwide", "remote", "online",
        },
        "reward_amount": item.get("rewardAmount"),
        "token": item.get("token"),
        "deadline": item.get("deadline"),
    }
