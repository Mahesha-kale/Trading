"""Vectorized indicators on pandas. No TA-Lib dep — fewer wheels, full control.

EMA, RSI (Wilder), ATR (Wilder), Supertrend, MACD, Bollinger, VWAP.
All return pandas Series aligned to input index. NaN at warmup.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # Wilder smoothing
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(100.0)  # no loss -> RSI 100; warmup NaNs -> 100 (handled by caller)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def supertrend(high: pd.Series, low: pd.Series, close: pd.Series,
               period: int = 10, multiplier: float = 3.0) -> tuple[pd.Series, pd.Series]:
    """Returns (st_line, direction) where direction: 1 uptrend, -1 downtrend."""
    a = atr(high, low, close, period)
    hl2 = (high + low) / 2
    upper_basic = hl2 + multiplier * a
    lower_basic = hl2 - multiplier * a

    upper = upper_basic.copy()
    lower = lower_basic.copy()
    dir_ = pd.Series(1, index=close.index)

    for i in range(1, len(close)):
        if np.isnan(a.iloc[i]):
            continue
        upper.iloc[i] = (upper_basic.iloc[i] if (upper_basic.iloc[i] < upper.iloc[i - 1] or close.iloc[i - 1] > upper.iloc[i - 1])
                         else upper.iloc[i - 1])
        lower.iloc[i] = (lower_basic.iloc[i] if (lower_basic.iloc[i] > lower.iloc[i - 1] or close.iloc[i - 1] < lower.iloc[i - 1])
                         else lower.iloc[i - 1])
        dir_.iloc[i] = 1 if close.iloc[i] > upper.iloc[i - 1] else (-1 if close.iloc[i] < lower.iloc[i - 1] else dir_.iloc[i - 1])
        st = pd.Series(np.nan, index=close.index)
    st = pd.Series(np.where(dir_ == 1, lower, upper), index=close.index)
    return st, dir_


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = ema(close, fast) - ema(close, slow)
    sig = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - sig
    return macd_line, sig, hist


def bollinger(close: pd.Series, period: int = 20, std_mult: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(period).mean()
    sd = close.rolling(period).std()
    return mid, mid + std_mult * sd, mid - std_mult * sd


def vwap(df: pd.DataFrame) -> pd.Series:
    """Cumulative session VWAP. Resets daily by default (group by date)."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].replace(0, np.nan).ffill().fillna(0)
    grp = df.index.date
    cum_pv = (typical * vol).groupby(grp).cumsum()
    cum_v = vol.groupby(grp).cumsum()
    return (cum_pv / cum_v.replace(0, np.nan))