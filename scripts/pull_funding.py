"""Pull BTCUSDT funding-rate history from Binance Vision (no API key, stdlib).
Binance publishes monthly fundingRate CSVs (calc_time,funding_interval_hours,
last_funding_rate) -- the rate is SIGNED (negative in bears: longs receive,
shorts pay). Caches to reports/binance_BTCUSDT_funding.parquet as a Series of
signed rates indexed by the 8h funding mark (UTC).

Usage: python scripts/pull_funding.py
"""
from __future__ import annotations

import io
import zipfile
from urllib.request import urlopen

import pandas as pd

BASE = "https://data.binance.vision/data/futures/um/monthly/fundingRate"


def _fetch_month(symbol: str, year: int, month: int) -> pd.DataFrame:
    url = f"{BASE}/{symbol}/{symbol}-fundingRate-{year}-{month:02d}.zip"
    with urlopen(url, timeout=30) as r:
        raw = r.read()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = z.namelist()[0]
        df = pd.read_csv(z.open(name))
    ts = pd.to_datetime(df["calc_time"], unit="ms", utc=True)
    # to_numpy(): pass the rate array positionally -- a Series keeps its RangeIndex
    # and DataFrame({"rate": series}, index=ts) would align by label -> all NaN.
    return pd.DataFrame({"rate": df["last_funding_rate"].astype(float).to_numpy()}, index=ts)


def fetch_funding(symbol: str = "BTCUSDT", start: str = "2023-01",
                  end: str = "2026-07", cache: bool = True) -> pd.Series:
    sy, sm = map(int, start.split("-")); ey, em = map(int, end.split("-"))
    frames = []; y, m = sy, sm
    while (y, m) <= (ey, em):
        try:
            frames.append(_fetch_month(symbol, y, m))
            print(f"  {symbol} funding {y}-{m:02d}: {len(frames[-1])}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  {symbol} funding {y}-{m:02d}: skip ({str(e)[:50]})", flush=True)
        m += 1
        if m > 12: y, m = y + 1, 1
    if not frames:
        return pd.Series(dtype=float)
    s = pd.concat(frames)["rate"].sort_index()
    s = s[~s.index.duplicated(keep="last")]
    if cache:
        out = f"reports/binance_{symbol}_funding.csv"
        try:
            s.to_frame().to_parquet(out.replace(".csv", ".parquet"))
            out = out.replace(".csv", ".parquet")
        except Exception:
            s.to_frame().to_csv(out)
        print(f"cached {len(s)} marks -> {out}", flush=True)
    return s


if __name__ == "__main__":
    s = fetch_funding("BTCUSDT", "2023-01", "2026-07")
    if len(s):
        print(f"BTCUSDT funding: {len(s)} marks {s.index[0]} -> {s.index[-1]} | "
              f"mean {s.mean():.6f} min {s.min():.6f} max {s.max():.6f}")
        # bear check: 2025-07 onward (the OOS downtrend) should skew negative
        bear = s.loc["2025-07":]
        print(f"  2025-07 onward: mean {bear.mean():.6f} frac<0 {(bear<0).mean():.2f}")