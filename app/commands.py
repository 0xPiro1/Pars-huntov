"""Telegram bot commands via getUpdates long polling."""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

import requests

from app import db, notifier
from app.settings import DATABASE_URL, MAX_NOTIFS_PER_RUN, POLL_INTERVAL_SECONDS

log = logging.getLogger(__name__)

GET_UPDATES_URL = "https://api.telegram.org/bot{token}/getUpdates"
TIMEOUT = 30

# Will be set from main.py before starting the thread
_run_cycle_fn: Callable[[], dict[str, int]] | None = None
_state: dict[str, Any] = {}
_token: str = ""


def init(token: str, state: dict[str, Any], run_cycle_fn: Callable) -> None:
    """Inject dependencies from main before starting the poll loop."""
    global _token, _state, _run_cycle_fn
    _token = token
    _state = state
    _run_cycle_fn = run_cycle_fn


# ── command handlers ─────────────────────────────────────────────

def cmd_help(chat_id: int | str) -> None:
    text = (
        "📋 Команды:\n"
        "/status — состояние watcher'а\n"
        "/test — тестовое сообщение\n"
        "/latest — последние 5 листингов\n"
        "/force — принудительный цикл fetch→notify\n"
        "/help — эта справка"
    )
    notifier.send_message(_token, chat_id, text)


def cmd_test(chat_id: int | str) -> None:
    notifier.send_message(_token, chat_id, "✅ test ok")


def cmd_status(chat_id: int | str) -> None:
    uptime = int(time.time() - _state.get("start_time", time.time()))
    last_check = _state.get("last_check_at")
    last_success = _state.get("last_success_at")
    last_error = _state.get("last_error")

    try:
        stats = db.get_stats(DATABASE_URL)
    except Exception as e:
        stats = {"total": "?", "notified": "?", "last_title": None, "last_tab": None, "last_region": None}
        log.exception("get_stats failed")

    lines = [
        "📊 Status",
        f"⏱ Uptime: {uptime}s",
        f"🔄 Poll interval: {POLL_INTERVAL_SECONDS}s",
        f"📅 Last check: {_fmt_ts(last_check)}",
        f"✅ Last success: {_fmt_ts(last_success)}",
        f"❌ Last error: {last_error or '—'}",
        "",
        f"📦 Total in DB: {stats['total']}",
        f"📨 Notified: {stats['notified']}",
    ]
    if stats.get("last_title"):
        lines.append(f"🆕 Last: [{stats['last_tab']}] {stats['last_title']} ({stats['last_region'] or '—'})")

    notifier.send_message(_token, chat_id, "\n".join(lines))


def cmd_latest(chat_id: int | str) -> None:
    try:
        rows = db.get_latest(DATABASE_URL, limit=5)
    except Exception:
        notifier.send_message(_token, chat_id, "❌ DB error")
        log.exception("get_latest failed")
        return

    if not rows:
        notifier.send_message(_token, chat_id, "📭 Пока нет записей")
        return

    lines = ["📋 Последние 5:"]
    for r in rows:
        ts = str(r["first_seen_at"])[:19] if r["first_seen_at"] else "?"
        region = r["region"] or "—"
        lines.append(f"\n[{r['tab']}] {r['title']}\n  🌍 {region} | 🕐 {ts}\n  {r['url']}")

    notifier.send_message(_token, chat_id, "\n".join(lines))


def cmd_force(chat_id: int | str) -> None:
    if _run_cycle_fn is None:
        notifier.send_message(_token, chat_id, "❌ run_cycle not initialised")
        return

    notifier.send_message(_token, chat_id, "⏳ Запускаю цикл…")
    try:
        result = _run_cycle_fn()
        text = (
            f"✅ done: new={result.get('new', 0)}, "
            f"notified={result.get('notified', 0)}, "
            f"skipped={result.get('skipped', 0)}"
        )
    except Exception as e:
        text = f"❌ Ошибка: {e}"
        log.exception("/force cycle error")

    notifier.send_message(_token, chat_id, text)


# ── dispatcher ───────────────────────────────────────────────────

COMMANDS: dict[str, Callable] = {
    "/status": cmd_status,
    "/test": cmd_test,
    "/latest": cmd_latest,
    "/force": cmd_force,
    "/help": cmd_help,
    "/start": cmd_help,
}


def _handle_update(update: dict[str, Any]) -> None:
    msg = update.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat_id = msg.get("chat", {}).get("id")
    if not chat_id or not text:
        return

    # Strip @botname suffix: /status@MyBot -> /status
    cmd = text.split()[0].split("@")[0].lower()

    handler = COMMANDS.get(cmd)
    if handler:
        log.info("Command %s from chat %s", cmd, chat_id)
        try:
            handler(chat_id)
        except Exception:
            log.exception("Command handler error: %s", cmd)


# ── main poll loop (runs in daemon thread) ───────────────────────

def poll_commands() -> None:
    """Long-poll getUpdates in a loop. Meant to run in a daemon thread."""
    offset = 0
    log.info("Commands poller started")

    while True:
        params: dict[str, Any] = {"timeout": TIMEOUT, "allowed_updates": ["message"]}
        if offset:
            params["offset"] = offset

        try:
            resp = requests.get(
                GET_UPDATES_URL.format(token=_token),
                params=params,
                timeout=TIMEOUT + 5,
            )
            data = resp.json()
            if not data.get("ok"):
                log.error("getUpdates error: %s", data)
                time.sleep(5)
                continue

            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                _handle_update(upd)

        except Exception:
            log.exception("getUpdates poll error")
            time.sleep(5)


# ── helpers ──────────────────────────────────────────────────────

def _fmt_ts(ts: float | None) -> str:
    if ts is None:
        return "—"
    import datetime
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
