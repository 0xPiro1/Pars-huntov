"""Telegram notification sender."""
from __future__ import annotations

import html
import logging
from typing import Any

import requests

log = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT = 15


def _esc(text: str) -> str:
    """Escape HTML special chars for Telegram."""
    return html.escape(str(text))


def _format_message(item: dict[str, Any]) -> str:
    tab = _esc((item.get("tab") or "bounty").upper())
    title = _esc(item.get("title", "—"))
    url = item.get("url", "")
    region = _esc(item.get("region") or "—")

    lines = [f'🆕 <a href="{url}">{title}</a> — [{tab}] ({region})']

    reward = item.get("reward_amount")
    token = item.get("token")
    if reward:
        reward_str = f"{reward} {_esc(token)}" if token else str(reward)
        lines.append(f"💰 Reward: {reward_str}")

    deadline = item.get("deadline")
    if deadline:
        lines.append(f"⏰ Due: {str(deadline)[:10]}")

    return "\n".join(lines)


def send_telegram(
    token: str,
    chat_id: str,
    item: dict[str, Any],
) -> bool:
    """Send a short Telegram message (HTML). Returns True on success."""
    text = _format_message(item)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(
            API_URL.format(token=token),
            json=payload,
            timeout=TIMEOUT,
        )
        if resp.ok:
            log.info("TG sent: %s", item.get("title", "?")[:60])
            return True
        log.error("TG error %s: %s", resp.status_code, resp.text[:200])
        return False
    except Exception:
        log.exception("TG request failed")
        return False


def send_message(
    token: str,
    chat_id: str | int,
    text: str,
    parse_mode: str | None = None,
) -> bool:
    """Send a text message to a chat. Returns True on success."""
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        resp = requests.post(
            API_URL.format(token=token),
            json=payload,
            timeout=TIMEOUT,
        )
        return resp.ok
    except Exception:
        log.exception("TG send_message failed")
        return False
