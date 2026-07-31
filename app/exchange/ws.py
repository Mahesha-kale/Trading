"""CoinDCX futures WebSocket client. Auto-reconnect, resubscribe, callback dispatch.

Public channels:  {pair}_1m-futures -> candlestick, {pair}@prices-futures -> price-change.
Auth channels (join "coindcx" with signed payload): df-order-update, df-position-update.

Used by live engine. Channels subscribed per timeframe + price feed.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from collections.abc import Awaitable, Callable

import websockets

from app.config import settings
from app.logging import get_logger

log = get_logger("exchange.ws")

ChannelCb = Callable[[dict], Awaitable[None]]


class CoinDCXWS:
    def __init__(self, on_candle: ChannelCb, on_order: ChannelCb | None = None,
                 on_position: ChannelCb | None = None):
        self.on_candle = on_candle
        self.on_order = on_order
        self.on_position = on_position
        self._ws = None
        self._stop = asyncio.Event()
        self._channels: list[str] = []

    def subscribe_candle(self, pair: str, timeframe: str) -> None:
        # resolution suffix: 1m..1M
        self._channels.append(f"{pair}_{timeframe}-futures")

    def subscribe_price(self, pair: str) -> None:
        self._channels.append(f"{pair}@prices-futures")

    async def run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                await self._connect()
                backoff = 1.0
            except Exception as e:  # noqa: BLE001
                log.error("ws disconnected", error=str(e))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _connect(self) -> None:
        async with websockets.connect(settings.ws_url, ping_interval=20, ping_timeout=20) as ws:
            self._ws = ws
            # public channels
            join = {"channel": "coindcx", "auth": {}}
            for ch in self._channels:
                await ws.send(json.dumps({"method": "subscribe", "channels": [ch]}))
            # auth channel if creds present
            if settings.coindcx_api_key and settings.coindcx_api_secret:
                ts = str(int(time.time()))
                sig = hmac.new(settings.coindcx_api_secret.encode(),
                               (ts + "coindcx").encode(), hashlib.sha256).hexdigest()
                join["auth"] = {"key": settings.coindcx_api_key, "signature": sig, "timestamp": ts}
                await ws.send(json.dumps({"method": "join", "channels": ["coindcx"]}))
            log.info("ws subscribed", channels=self._channels)
            async for raw in ws:
                await self._dispatch(json.loads(raw))

    async def _dispatch(self, msg: dict) -> None:
        ch = msg.get("channel")
        # candlestick messages carry 'candlestick' or 'price-change' in channel name
        if ch and "candlestick" in str(msg) or (ch and "prices-futures" in ch):
            await self.on_candle(msg)
        elif ch == "df-order-update" and self.on_order:
            await self.on_order(msg)
        elif ch == "df-position-update" and self.on_position:
            await self.on_position(msg)

    def stop(self) -> None:
        self._stop.set()