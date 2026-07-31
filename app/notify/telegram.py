"""Telegram notifier. Fire-and-forget; failures logged, never block trading."""
from __future__ import annotations

import httpx

from app.config import settings
from app.logging import get_logger

log = get_logger("notify.telegram")


async def notify(text: str) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(url, json={"chat_id": settings.telegram_chat_id, "text": text})
    except Exception as e:  # noqa: BLE001
        log.error("telegram_send_failed", error=str(e))