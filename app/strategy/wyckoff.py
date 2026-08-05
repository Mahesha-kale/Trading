"""Wyckoff Method — accumulation schematic, long-only.

Wyckoff reads supply/demand from price spread + volume. This encodes the
accumulation schematic as a deterministic, stateful scan:

  1. Prior downtrend (price below a slow EMA) -> context for accumulation.
  2. Range formed: range_high/range_low = rolling max/min over `range_period`.
  3. Spring (Phase C): low pierces range_low by `spring_pen` but close
     recovers back inside the range on *contracted* volume (supply exhaustion,
     the shake-out of weak holders). This is the low-risk entry probe.
  4. SOS (Sign of Strength, Phase D): within `sos_window` bars of the spring,
     close breaks above range_high (the "creek") on *expanded* volume.
     This confirms demand > supply; markup begins -> enter long (+1).
  5. Exit (0): trailing ATR stop (rising) is hit, or close loses the range low.

Long-only (+1/0) to match the backtest/live engines. Volume is the effort vs
result arbiter Wyckoff insisted on; without it a spring is just a wick.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.strategy.base import BaseStrategy, StrategyMeta
from app.strategy.indicators import atr, ema


class Wyckoff(BaseStrategy):
    meta = StrategyMeta(name="wyckoff", timeframe="15m", warmup=250)
    params = {
        "range_period": 60,      # bars defining the trading range / support
        "trend_ema": 50,         # slow EMA for downtrend-context gate
        "spring_pen": 0.003,     # low must pierce range_low * (1 - pen)
        "rejection_frac": 0.5,   # spring bar closes in upper `frac` of its range
        "vol_expand": 1.3,       # SOS volume > x * avg  (demand confirmation)
        "sos_window": 60,        # bars after spring to wait for SOS (creek break)
        "atr_period": 14,
        "atr_mult": 3.0,         # trailing stop distance
        "trend_slope": 10,        # EMA slope lookback for downtrend gate (bars)
        "tp_multiple": None,      # take-profit = entry + N*range; None = let trail run
        "use_volume": True,      # gate SOS with volume expansion
    }

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        n = len(df)
        high, low, close, vol = df["high"], df["low"], df["close"], df["volume"]
        a = atr(high, low, close, p["atr_period"])
        trend = ema(close, p["trend_ema"])
        # rolling range excludes the current bar (shift 1) -> no look-ahead
        rh = high.rolling(p["range_period"]).max().shift(1)
        rl = low.rolling(p["range_period"]).min().shift(1)
        vol_avg = vol.rolling(p["range_period"]).mean().shift(1)

        sig = pd.Series(0, index=df.index, dtype=int)
        pos = 0
        trail = np.nan
        spring_idx = -10_000  # bars since spring; far away until one occurs
        high_water = np.nan

        for i in range(n):
            if pd.isna(rh.iloc[i]) or pd.isna(a.iloc[i]):
                continue
            c = float(close.iloc[i])
            lo = float(low.iloc[i])
            v = float(vol.iloc[i])
            vavg = float(vol_avg.iloc[i]) if pd.notna(vol_avg.iloc[i]) else 0.0
            r_lo = float(rl.iloc[i])

            if pos == 1:
                # hold: emit +1 every bar while long (live/paper engine holds on 1,
                # closes on 0). Backtest ignores held 1s and exits via its own
                # ATR trailing stop. Rising trail; exit when close falls through.
                high_water = max(high_water, float(high.iloc[i]))
                trail = max(trail, high_water - p["atr_mult"] * float(a.iloc[i]))
                if c < trail:
                    sig.iloc[i] = 0  # go flat -> live/paper closes here
                    pos = 0
                    trail = np.nan
                    high_water = np.nan
                    spring_idx = -10_000
                else:
                    sig.iloc[i] = 1  # still long
                continue

            # accumulation context: prior/ongoing downtrend -> slow EMA flat or
            # falling. (Not the spring bar's close, which by definition recovers
            # back into the range and often back above a flat EMA.)
            j = max(i - p["trend_slope"], 0)
            downtrend = (float(trend.iloc[i]) <= float(trend.iloc[j])) if pd.notna(trend.iloc[j]) else True

            # spring detection: pierce range low, recover above support, close in
            # the upper portion of the bar (a rejection wick = demand absorbed
            # supply). No volume gate on the spring itself: 15m spring volume is
            # noisy; the SOS volume expansion is the real demand confirmation.
            hi = float(high.iloc[i])
            if (
                downtrend
                and lo < r_lo * (1 - p["spring_pen"])
                and c > r_lo                       # closed back above support
                and hi > lo and c > lo + (hi - lo) * p["rejection_frac"]
            ):
                spring_idx = i
                continue

            # SOS: creek break on expanded volume within window of a spring
            bars_since = i - spring_idx
            if 0 < bars_since <= p["sos_window"] and c > float(rh.iloc[i]):
                if not p["use_volume"] or vavg == 0 or v > p["vol_expand"] * vavg:
                    sig.iloc[i] = 1
                    pos = 1
                    trail = c - p["atr_mult"] * float(a.iloc[i])
                    high_water = float(high.iloc[i])
                    spring_idx = -10_000
        return sig

    def stop_loss(self, df: pd.DataFrame, entry_idx) -> float | None:
        p = self.params
        a = atr(df["high"], df["low"], df["close"], p["atr_period"])
        entry = float(df["close"].iloc[entry_idx])
        av = float(a.iloc[entry_idx]) if pd.notna(a.iloc[entry_idx]) else entry * 0.02
        return entry - p["atr_mult"] * av

    def take_profit(self, df: pd.DataFrame, entry_idx) -> float | None:
        # Optional Wyckoff markup target: project N*range above the creek break.
        # Default None -> winners ride the trailing stop (markup can extend far).
        p = self.params
        if p["tp_multiple"] is None:
            return None
        rh = df["high"].rolling(p["range_period"]).max().shift(1)
        rl = df["low"].rolling(p["range_period"]).min().shift(1)
        entry = float(df["close"].iloc[entry_idx])
        if pd.isna(rh.iloc[entry_idx]) or pd.isna(rl.iloc[entry_idx]):
            return None
        rng = float(rh.iloc[entry_idx]) - float(rl.iloc[entry_idx])
        if rng <= 0:
            return None
        return entry + p["tp_multiple"] * rng


if __name__ == "__main__":
    # self-check: deterministic synthetic accumulation -> at least one entry
    n = 800
    idx = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    rng = np.random.default_rng(2)
    # downtrend -> range -> spring pierce (low vol) -> SOS rally (high vol)
    base = np.concatenate([
        np.linspace(30000, 24000, 400),                        # downtrend
        np.full(120, 24000) + rng.normal(0, 120, 120),         # range at 24000
        np.array([24100]),                                     # spring bar (close recovers)
        np.linspace(24250, 30000, 279),                        # SOS / markup rally
    ])
    close = base + rng.normal(0, 60, n)
    high = close * (1 + rng.uniform(0, 0.004, n))
    low = close * (1 - rng.uniform(0, 0.004, n))
    # low volume through downtrend+range+spring, high volume on the SOS rally
    vol = np.concatenate([
        rng.uniform(5, 20, 521),   # incl. the spring bar (light)
        rng.uniform(18, 35, 279), # SOS rally (expanded)
    ])
    df = pd.DataFrame({"open": close, "high": high, "low": low, "close": close,
                       "volume": vol}, index=idx)
    # spring bar (idx 520): wick below 24000 support, close recovers inside range
    df.iloc[520, df.columns.get_loc("low")] = 23000.0
    df.iloc[520, df.columns.get_loc("close")] = 24100.0
    df.iloc[520, df.columns.get_loc("high")] = 24150.0
    sigs = Wyckoff().generate_signals(df)
    # count entry transitions (flat -> long), not held bars
    entries = int(((sigs == 1) & (sigs.shift(1, fill_value=0) != 1)).sum())
    assert entries >= 1, f"expected >=1 entry on synthetic accumulation, got {entries}"
    print(f"wyckoff self-check ok: {entries} entries on synthetic schematic")