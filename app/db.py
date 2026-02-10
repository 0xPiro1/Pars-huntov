"""Postgres helpers for listings_seen table (via Supabase)."""
from __future__ import annotations

import logging
from typing import Any

import psycopg2

log = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS listings_seen (
    id              TEXT PRIMARY KEY,
    tab             TEXT NOT NULL,
    title           TEXT,
    url             TEXT,
    region          TEXT,
    is_global       BOOLEAN NOT NULL DEFAULT TRUE,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    notified_at     TIMESTAMPTZ
);
"""


def init_db(dsn: str) -> None:
    """Create table if not exists."""
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE_TABLE)
        conn.commit()
    log.info("DB initialised (listings_seen ready)")


def upsert_listing(dsn: str, item: dict[str, Any]) -> bool:
    """Insert or update listing. Returns True if row is NEW (first insert)."""
    sql = """
    INSERT INTO listings_seen (id, tab, title, url, region, is_global)
    VALUES (%(id)s, %(tab)s, %(title)s, %(url)s, %(region)s, %(is_global)s)
    ON CONFLICT (id) DO UPDATE
        SET last_seen_at = now(),
            title        = EXCLUDED.title,
            url          = EXCLUDED.url,
            region       = EXCLUDED.region,
            is_global    = EXCLUDED.is_global
    RETURNING (xmax = 0) AS is_new;
    """
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, item)
            row = cur.fetchone()
        conn.commit()
    return bool(row and row[0])


def needs_notification(dsn: str, listing_id: str) -> bool:
    """Return True if notified_at IS NULL for given listing."""
    sql = "SELECT notified_at FROM listings_seen WHERE id = %s;"
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (listing_id,))
            row = cur.fetchone()
    if row is None:
        return False
    return row[0] is None


def mark_notified(dsn: str, listing_id: str) -> None:
    """Set notified_at = now()."""
    sql = "UPDATE listings_seen SET notified_at = now() WHERE id = %s;"
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (listing_id,))
        conn.commit()


def get_stats(dsn: str) -> dict[str, Any]:
    """Return aggregate stats from listings_seen."""
    sql = """
    SELECT
        count(*)                              AS total,
        count(notified_at)                    AS notified,
        max(first_seen_at)                    AS last_first_seen
    FROM listings_seen;
    """
    last_sql = """
    SELECT title, tab, region
    FROM listings_seen
    ORDER BY first_seen_at DESC
    LIMIT 1;
    """
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            cur.execute(last_sql)
            last = cur.fetchone()
    return {
        "total": row[0] if row else 0,
        "notified": row[1] if row else 0,
        "last_first_seen": row[2] if row else None,
        "last_title": last[0] if last else None,
        "last_tab": last[1] if last else None,
        "last_region": last[2] if last else None,
    }


def get_latest(dsn: str, limit: int = 5) -> list[dict[str, Any]]:
    """Return latest N listings from listings_seen."""
    sql = """
    SELECT title, tab, region, url, first_seen_at
    FROM listings_seen
    ORDER BY first_seen_at DESC
    LIMIT %s;
    """
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            rows = cur.fetchall()
    return [
        {
            "title": r[0],
            "tab": r[1],
            "region": r[2],
            "url": r[3],
            "first_seen_at": r[4],
        }
        for r in rows
    ]
