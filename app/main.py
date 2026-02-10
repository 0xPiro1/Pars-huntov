"""Superteam Earn watcher — polling entrypoint."""
from __future__ import annotations

import logging
import threading
import time

from app import commands, db, filters, notifier, superteam
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

# Shared state visible to commands thread
state: dict = {
    "start_time": time.time(),
    "last_check_at": None,
    "last_success_at": None,
    "last_error": None,
}


def run_cycle() -> dict[str, int]:
    """Single polling cycle. Returns {new, notified, skipped}."""
    state["last_check_at"] = time.time()

    listings = superteam.fetch_listings()
    if not listings:
        log.info("No listings returned from API")
        state["last_success_at"] = time.time()
        return {"new": 0, "notified": 0, "skipped": 0}

    log.info("Fetched %d listings from API", len(listings))
    new_count = 0
    notified_count = 0
    skipped_count = 0

    for item in listings:
        if notified_count >= MAX_NOTIFS_PER_RUN:
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
        if is_new:
            new_count += 1

        # Decide whether to notify
        should_notify = is_new or db.needs_notification(DATABASE_URL, norm["id"])
        if not should_notify:
            continue

        # Country filter
        if not filters.is_allowed(norm.get("region")):
            log.debug("Skipped (region=%s): %s", norm.get("region"), norm["title"])
            skipped_count += 1
            continue

        # Send Telegram
        ok = notifier.send_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, norm)
        if ok:
            db.mark_notified(DATABASE_URL, norm["id"])
            notified_count += 1

    state["last_success_at"] = time.time()
    state["last_error"] = None
    return {"new": new_count, "notified": notified_count, "skipped": skipped_count}


def main() -> None:
    log.info(
        "Watcher started  poll=%ds  max_notifs=%d",
        POLL_INTERVAL_SECONDS,
        MAX_NOTIFS_PER_RUN,
    )
    db.init_db(DATABASE_URL)

    # Start bot commands poller in a daemon thread
    commands.init(TELEGRAM_BOT_TOKEN, state, run_cycle)
    t = threading.Thread(target=commands.poll_commands, daemon=True)
    t.start()
    log.info("Commands poller thread started")

    # Watcher loop
    while True:
        try:
            result = run_cycle()
            log.info(
                "Cycle done — new=%d notified=%d skipped=%d",
                result["new"], result["notified"], result["skipped"],
            )
        except Exception as e:
            state["last_error"] = str(e)
            log.exception("Cycle error")
        log.info("Sleeping %ds …", POLL_INTERVAL_SECONDS)
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
