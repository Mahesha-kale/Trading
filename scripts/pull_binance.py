"""Pull long public history from Binance Vision (no API key, stdlib only).

Binance publishes monthly kline CSVs for USDT-M perp futures. We pull BTCUSDT
+ ETHUSDT 15m over a multi-year window the CoinDCX API can't reach (its 15m cap
is ~330d). Used for multi-regime walk-forward — the single-regime CoinDCX window
is why no strategy showed durable edge.

Caches to reports/binance_<symbol>_<tf>.parquet on first fetch so re-runs are
instant. Falls back to CSV if pandas has no parquet writer (it does).
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from urllib.request import urlopen

import pandas as pd

BASE = "https://data.binance.vision/data/futures/um/monthly/klines"
COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
        "quote_vol", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]
# market -> Binance Vision path segment. futures/um = USDT-M perp; spot = spot.
MARKETS = {"futures": "futures/um", "spot": "spot"}


def _fetch_month(symbol: str, tf: str, year: int, month: int, base: str = BASE) -> pd.DataFrame:
    url = f"{base}/{symbol}/{tf}/{symbol}-{tf}-{year}-{month:02d}.zip"
    with urlopen(url, timeout=30) as r:
        raw = r.read()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = z.namelist()[0]
        # Futures monthly klines ship WITH a header row; spot monthly klines are
        # headerless. Read headered; fall back to headerless with COLS names.
        df = pd.read_csv(z.open(name))
        if "open_time" not in df.columns:
            df = pd.read_csv(z.open(name), header=None, names=COLS)
    # Binance switched spot klines from ms (13-digit) to microseconds (16-digit)
    # ~2025; futures stayed ms. Normalize: if any open_time looks like µs (>1e14),
    # the whole file is µs -> divide to ms. Then drop stray rows outside 2020..2035.
    ot = df["open_time"].astype("int64")
    if ot.max() > 1e14:
        ot = ot // 1000
    df = df.assign(open_time=ot)
    df = df[ot.between(int(1.5e12), int(2.05e12))]
    df["ts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df[["ts", "open", "high", "low", "close", "volume"]].set_index("ts")
    df = df.astype(float)
    return df


def fetch_binance(symbol: str = "BTCUSDT", tf: str = "15m",
                  start: str = "2023-01", end: str = "2025-07",
                  cache: bool = True, market: str = "futures") -> pd.DataFrame:
    """Fetch monthly klines start..end inclusive (YYYY-MM). Returns OHLCV df.

    market: "futures" (USDT-M perp, default) or "spot". Spot klines live at
    data/spot/monthly/klines and use the same CSV layout as futures.
    """
    base = f"https://data.binance.vision/data/{MARKETS[market]}/monthly/klines"
    tag = "" if market == "futures" else "_spot"
    sy, sm = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    frames = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        try:
            frames.append(_fetch_month(symbol, tf, y, m, base))
            print(f"  {symbol} {tf} {y}-{m:02d}: {len(frames[-1])} bars", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  {symbol} {tf} {y}-{m:02d}: skip ({str(e)[:50]})", flush=True)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames).sort_index()
    df.name = "ohlcv"
    if cache:
        out = f"reports/binance_{symbol}{tag}_{tf}.parquet"
        try:
            df.to_parquet(out)
        except Exception:
            df.to_csv(out.replace(".parquet", ".csv"))
        print(f"cached {len(df)} bars -> {out}", flush=True)
    return df


if __name__ == "__main__":
    import sys
    market = sys.argv[1] if len(sys.argv) > 1 else "futures"
    syms = sys.argv[2:] if len(sys.argv) > 2 else ("BTCUSDT", "ETHUSDT")
    for sym in syms:
        df = fetch_binance(sym, "15m", "2023-01", "2026-07", market=market)
        if df.empty:
            print(f"{sym} 15m [{market}]: EMPTY (all months skipped)")
        else:
            print(f"{sym} 15m [{market}]: {len(df)} bars {df.index[0]} -> {df.index[-1]}")