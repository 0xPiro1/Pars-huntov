"""Telegram notification sender."""
from __future__ import annotations

import logging
from typing import Any

import requests

log = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT = 15


def _format_message(item: dict[str, Any]) -> str:
    tab = (item.get("tab") or "bounty").upper()
    title = item.get("title", "—")
    url = item.get("url", "")

    lines = [f"🆕 [{tab}] {title}"]

    reward = item.get("reward_amount")
    token = item.get("token")
    if reward:
        reward_str = f"{reward} {token}" if token else str(reward)
        lines.append(f"💰 Reward: {reward_str}")

    deadline = item.get("deadline")
    if deadline:
        lines.append(f"⏰ Due: {str(deadline)[:10]}")

    lines.append(url)
    return "\n".join(lines)


def send_telegram(
    token: str,
    chat_id: str,
    item: dict[str, Any],
) -> bool:
    """Send a short Telegram message. Returns True on success."""
    text = _format_message(item)
    payload = {
        "chat_id": chat_id,
        "text": text,
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
