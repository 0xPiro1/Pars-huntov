"""Watcher settings from environment variables."""
from __future__ import annotations

import os


def _env(key: str, default: str | None = None, required: bool = False) -> str:
    val = os.environ.get(key, default)
    if required and not val:
        raise RuntimeError(f"Missing required env var: {key}")
    return val  # type: ignore[return-value]


DATABASE_URL: str = _env("DATABASE_URL", required=True)
TELEGRAM_BOT_TOKEN: str = _env("TELEGRAM_BOT_TOKEN", required=True)
TELEGRAM_CHAT_ID: str = _env("TELEGRAM_CHAT_ID", required=True)
POLL_INTERVAL_SECONDS: int = int(_env("POLL_INTERVAL_SECONDS", "600"))
MAX_NOTIFS_PER_RUN: int = int(_env("MAX_NOTIFS_PER_RUN", "10"))
LOG_LEVEL: str = _env("LOG_LEVEL", "INFO")
