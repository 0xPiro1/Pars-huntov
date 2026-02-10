"""Telegram bot commands via getUpdates long polling."""
from __future__ import annotations

import html
import logging
import threading
import time
from typing import Any, Callable

import requests

from app import db, notifier
from app.settings import DATABASE_URL, MAX_NOTIFS_PER_RUN, POLL_INTERVAL_SECONDS

log = logging.getLogger(__name__)

GET_UPDATES_URL = "https://api.telegram.org/bot{token}/getUpdates"
TIMEOUT = 30
FORCE_COOLDOWN = 60  # seconds

# Will be set from main.py before starting the thread
_run_cycle_fn: Callable[[], dict[str, int]] | None = None
_state: dict[str, Any] = {}
_token: str = ""

# /force guards
_force_running = False
_force_last_ts: float = 0.0
_force_lock = threading.Lock()


def _esc(text: str) -> str:
    return html.escape(str(text))


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


def _health_indicator() -> str:
    last_check = _state.get("last_check_at")
    if last_check is None:
        return "❓ unknown"
    elapsed = time.time() - last_check
    if elapsed > POLL_INTERVAL_SECONDS * 2:
        return "⚠️ stalled"
    return "✅ alive"


def cmd_status(chat_id: int | str) -> None:
    uptime = int(time.time() - _state.get("start_time", time.time()))
    last_check = _state.get("last_check_at")
    last_success = _state.get("last_success_at")
    last_error = _state.get("last_error")

    try:
        stats = db.get_stats(DATABASE_URL)
    except Exception:
        stats = {"total": "?", "notified": "?", "last_title": None, "last_tab": None, "last_region": None}
        log.exception("get_stats failed")

    lines = [
        "📊 <b>Status</b>",
        f"🩺 Health: {_health_indicator()}",
        f"⏱ Uptime: {uptime}s",
        f"🔄 Poll interval: {POLL_INTERVAL_SECONDS}s",
        f"📅 Last check: {_fmt_ts(last_check)}",
        f"✅ Last success: {_fmt_ts(last_success)}",
        f"❌ Last error: {_esc(last_error) if last_error else '—'}",
        "",
        f"📦 Total in DB: {stats['total']}",
        f"📨 Notified: {stats['notified']}",
    ]
    if stats.get("last_title"):
        title = _esc(stats["last_title"])
        tab = _esc(stats["last_tab"] or "?")
        region = _esc(stats["last_region"] or "—")
        # Build clickable link if we can find URL from latest
        try:
            latest = db.get_latest(DATABASE_URL, limit=1)
            url = latest[0]["url"] if latest else ""
        except Exception:
            url = ""
        if url:
            lines.append(f'🆕 Last: <a href="{url}">{title}</a> — [{tab}] ({region})')
        else:
            lines.append(f"🆕 Last: {title} — [{tab}] ({region})")

    notifier.send_message(_token, chat_id, "\n".join(lines), parse_mode="HTML")


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

    lines = ["📋 <b>Последние 5:</b>"]
    for r in rows:
        ts = str(r["first_seen_at"])[:19] if r["first_seen_at"] else "?"
        region = _esc(r["region"] or "—")
        title = _esc(r["title"] or "—")
        tab = _esc(r["tab"] or "?")
        url = r["url"] or ""
        lines.append(
            f'\n<a href="{url}">{title}</a> — [{tab}]'
            f"\n  🌍 {region} | 🕐 {ts}"
        )

    notifier.send_message(_token, chat_id, "\n".join(lines), parse_mode="HTML")


def cmd_force(chat_id: int | str) -> None:
    global _force_running, _force_last_ts

    if _run_cycle_fn is None:
        notifier.send_message(_token, chat_id, "❌ run_cycle not initialised")
        return

    with _force_lock:
        if _force_running:
            notifier.send_message(_token, chat_id, "⏳ Цикл уже выполняется, подожди")
            return
        elapsed = time.time() - _force_last_ts
        if elapsed < FORCE_COOLDOWN:
            wait = int(FORCE_COOLDOWN - elapsed)
            notifier.send_message(_token, chat_id, f"🕐 Cooldown: подожди ещё {wait}s")
            return
        _force_running = True

    notifier.send_message(_token, chat_id, "⏳ Запускаю цикл…")

    def _run() -> None:
        global _force_running, _force_last_ts
        t0 = time.time()
        try:
            result = _run_cycle_fn()
            duration = round(time.time() - t0, 1)
            text = (
                f"✅ done: new={result.get('new', 0)}, "
                f"notified={result.get('notified', 0)}, "
                f"skipped={result.get('skipped', 0)}, "
                f"duration={duration}s"
            )
        except Exception as e:
            text = f"❌ Ошибка: {_esc(str(e))}"
            log.exception("/force cycle error")
        finally:
            with _force_lock:
                _force_running = False
                _force_last_ts = time.time()
        notifier.send_message(_token, chat_id, text)

    threading.Thread(target=_run, daemon=True).start()


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
