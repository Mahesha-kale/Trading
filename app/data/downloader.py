"""Historical OHLCV downloader. Fetches in windows, persists to DB, dedup via unique index."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import session_scope
from app.exchange.coindcx import CoinDCXClient
from app.logging import get_logger
from app.models import Candle

log = get_logger("data.downloader")

# CoinDCX candle endpoint window cap ~ a few months; keep windows small to be safe.
WINDOW = timedelta(days=30)


async def download_ohlcv(
    pair: str, timeframe: str, start: datetime, end: datetime, client: CoinDCXClient | None = None,
) -> int:
    """Download candles from start..end (UTC), upsert into DB. Returns rows written."""
    own = client is None
    client = client or CoinDCXClient()
    total = 0
    try:
        cur = start.astimezone(timezone.utc)
        end = end.astimezone(timezone.utc)
        while cur < end:
            nxt = min(cur + WINDOW, end)
            rows = await client.get_candles(pair, timeframe, int(cur.timestamp()), int(nxt.timestamp()))
            if rows:
                await _upsert(pair, timeframe, rows)
                total += len(rows)
                log.info("fetched", pair=pair, tf=timeframe, n=len(rows), at=cur.date().isoformat())
            cur = nxt + timedelta(seconds=1)
    finally:
        if own:
            await client.aclose()
    return total


async def _upsert(pair: str, timeframe: str, rows: list[dict]) -> None:
    values = []
    for r in rows:
        ts = datetime.fromtimestamp(r["time"] / 1000, tz=timezone.utc)
        values.append({
            "symbol": pair, "timeframe": timeframe, "ts": ts,
            "open": Decimal(str(r["open"])), "high": Decimal(str(r["high"])),
            "low": Decimal(str(r["low"])), "close": Decimal(str(r["close"])),
            "volume": Decimal(str(r.get("volume", 0))),
        })
    if not values:
        return
    # asyncpg caps query params at 32767; 8 cols/row -> chunk at 2000 rows so
    # 1m/5m windows (43200/8640 rows) don't blow the limit. 15m worked by luck.
    async with session_scope() as s:
        for i in range(0, len(values), 2000):
            chunk = values[i:i + 2000]
            stmt = pg_insert(Candle).values(chunk)
            stmt = stmt.on_conflict_do_nothing(index_elements=["symbol", "timeframe", "ts"])
            await s.execute(stmt)


async def load_candles(pair: str, timeframe: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Load candles from DB into a sorted DataFrame indexed by ts."""
    async with session_scope() as s:
        q = (select(Candle)
             .where(Candle.symbol == pair, Candle.timeframe == timeframe,
                    Candle.ts >= start, Candle.ts <= end)
             .order_by(Candle.ts))
        res = await s.execute(q)
        rows = res.scalars().all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([{
        "ts": r.ts, "open": float(r.open), "high": float(r.high), "low": float(r.low),
        "close": float(r.close), "volume": float(r.volume),
    } for r in rows])
    df = df.set_index("ts").sort_index()
    return df


# self-check: indicator window math sanity (cheap)
if __name__ == "__main__":  # pragma: no cover
    async def _demo():
        c = CoinDCXClient()
        # instrument metadata fetch only needs public; run in test mode guard
        try:
            inst = await c.get_instrument(settings.symbol)
            print("instrument keys:", list(inst)[:10] if inst else "no data")
        finally:
            await c.aclose()
    asyncio.run(_demo())