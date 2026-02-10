"""Superteam Earn watcher — polling entrypoint."""
from __future__ import annotations

import logging
import time

from app import db, filters, notifier, superteam
from app.settings import (
    DATABASE_URL,
    LOG_LEVEL,
    MAX_NOTIFS_PER_RUN,
    POLL_INTERVAL_SECONDS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


def run_cycle() -> int:
    """Single polling cycle. Returns number of notifications sent."""
    listings = superteam.fetch_listings()
    if not listings:
        log.info("No listings returned from API")
        return 0

    log.info("Fetched %d listings from API", len(listings))
    sent = 0

    for item in listings:
        if sent >= MAX_NOTIFS_PER_RUN:
            log.info("Hit MAX_NOTIFS_PER_RUN (%d), stopping cycle", MAX_NOTIFS_PER_RUN)
            break

        slug = item.get("slug")
        if not slug:
            continue

        # Fetch detail to get region
        detail = superteam.fetch_detail(slug)
        norm = superteam.normalise(item, detail)

        # Upsert into DB
        is_new = db.upsert_listing(DATABASE_URL, norm)

        # Decide whether to notify
        should_notify = is_new or db.needs_notification(DATABASE_URL, norm["id"])
        if not should_notify:
            continue

        # Country filter
        if not filters.is_allowed(norm.get("region")):
            log.debug("Skipped (region=%s): %s", norm.get("region"), norm["title"])
            continue

        # Send Telegram
        ok = notifier.send_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, norm)
        if ok:
            db.mark_notified(DATABASE_URL, norm["id"])
            sent += 1

    return sent


def main() -> None:
    log.info(
        "Watcher started  poll=%ds  max_notifs=%d",
        POLL_INTERVAL_SECONDS,
        MAX_NOTIFS_PER_RUN,
    )
    db.init_db(DATABASE_URL)

    while True:
        try:
            sent = run_cycle()
            log.info("Cycle done — %d notifications sent", sent)
        except Exception:
            log.exception("Cycle error")
        log.info("Sleeping %ds …", POLL_INTERVAL_SECONDS)
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
