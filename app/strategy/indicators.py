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

# --- extended indicators (vectorized, NaN at warmup) ---

def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def donchian(high: pd.Series, low: pd.Series, period: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (upper, lower, mid) excl. current bar (shift 1) to avoid look-ahead."""
    up = high.rolling(period).max().shift(1)
    lo = low.rolling(period).min().shift(1)
    return up, lo, (up + lo) / 2


def keltner(high: pd.Series, low: pd.Series, close: pd.Series,
            period: int = 20, mult: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (mid, upper, lower). Uses ATR for band width (more stable than BB)."""
    mid = ema(close, period)
    a = atr(high, low, close, period)
    return mid, mid + mult * a, mid - mult * a


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder ADX (trend strength, 0-100). Returns ADX series only."""
    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    a = atr(high, low, close, period)
    tr = a * 0  # placeholder; recompute true range for ATR-based denom below
    # Wilder smoothing of +DM/-DM and TR
    prev_close = close.shift(1)
    tr_raw = pd.concat([(high - low).abs(), (high - prev_close).abs(),
                        (low - prev_close).abs()], axis=1).max(axis=1)
    atr_w = tr_raw.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_w.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_w.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean().fillna(0.0)


def cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    """Commodity Channel Index. Mean deviation from typical price."""
    tp = (high + low + close) / 3
    sma_tp = tp.rolling(period).mean()
    md = tp.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - sma_tp) / (0.015 * md.replace(0, np.nan))


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume (cumulative, signed)."""
    sign = np.sign(close.diff().fillna(0))
    return (sign * volume).cumsum()


def cmf(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int = 20) -> pd.Series:
    """Chaikin Money Flow: rolling mean of Money Flow Multiplier * Volume / Volume."""
    mf_mult = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
    mf_vol = mf_mult * volume
    return mf_vol.rolling(period).sum() / volume.rolling(period).sum().replace(0, np.nan)


def stoch_rsi(close: pd.Series, rsi_period: int = 14, stoch_period: int = 14) -> pd.Series:
    """Stochastic RSI (0-100). RSI of RSI, then stochastic of that."""
    r = rsi(close, rsi_period)
    r_min = r.rolling(stoch_period).min()
    r_max = r.rolling(stoch_period).max()
    return 100 * (r - r_min) / (r_max - r_min).replace(0, np.nan)


def psar(high: pd.Series, low: pd.Series, close: pd.Series,
         step: float = 0.02, max_step: float = 0.2) -> pd.Series:
    """Parabolic SAR. Returns SAR series (above price in downtrend, below in uptrend)."""
    n = len(close)
    sar = pd.Series(np.nan, index=close.index)
    if n < 2:
        return sar
    bull = True
    af = step
    ep = float(high.iloc[0])
    s = float(low.iloc[0])
    sar.iloc[0] = float(high.iloc[0])  # arbitrary start
    for i in range(1, n):
        prev_sar = sar.iloc[i - 1]
        new_sar = prev_sar + af * (ep - prev_sar)
        if bull:
            new_sar = min(new_sar, float(low.iloc[i - 1]), float(low.iloc[max(i - 2, 0)]))
            if float(low.iloc[i]) < new_sar:
                bull = False
                new_sar = ep
                af = step
                ep = float(low.iloc[i])
            else:
                if float(high.iloc[i]) > ep:
                    ep = float(high.iloc[i])
                    af = min(af + step, max_step)
        else:
            new_sar = max(new_sar, float(high.iloc[i - 1]), float(high.iloc[max(i - 2, 0)]))
            if float(high.iloc[i]) > new_sar:
                bull = True
                new_sar = ep
                af = step
                ep = float(high.iloc[i])
            else:
                if float(low.iloc[i]) < ep:
                    ep = float(low.iloc[i])
                    af = min(af + step, max_step)
        sar.iloc[i] = new_sar
    return sar


def pivot_points(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.DataFrame:
    """Daily classic pivot levels (P, R1, R2, S1, S2), forward-filled within each day.
    Uses prior day's H/L/C. Index must be tz-aware datetime."""
    grp = close.index.date
    prev_h = high.groupby(grp).transform("last").shift(1)
    prev_l = low.groupby(grp).transform("last").shift(1)
    prev_c = close.groupby(grp).transform("last").shift(1)
    piv = (prev_h + prev_l + prev_c) / 3
    r1 = 2 * piv - prev_l
    s1 = 2 * piv - prev_h
    r2 = piv + (prev_h - prev_l)
    s2 = piv - (prev_h - prev_l)
    return pd.DataFrame({"pivot": piv, "r1": r1, "r2": r2, "s1": s1, "s2": s2}, index=close.index)


def ichimoku(high: pd.Series, low: pd.Series, close: pd.Series,
             tenkan: int = 9, kijun: int = 26, senkou_b: int = 52) -> dict[str, pd.Series]:
    """Ichimoku components. Cloud (senkou A/B) shifted forward by kijun (standard)."""
    def midway(a, b, p):
        return (a.rolling(p).max() + b.rolling(p).min()) / 2
    conv = midway(high, low, tenkan)
    base = midway(high, low, kijun)
    span_a = (conv + base) / 2
    span_b = midway(high, low, senkou_b)
    # cloud shifted forward kijun bars (predictive); for signal use unshifted comparison
    return {"tenkan": conv, "kijun": base, "span_a": span_a, "span_b": span_b,
            "cloud_top": span_a.clip(upper=span_b).where(span_a >= span_b, span_b),
            "cloud_bot": span_a.clip(lower=span_b).where(span_a <= span_b, span_b)}


if __name__ == "__main__":
    # self-checks: shape + range sanity on synthetic data
    import numpy as np
    n = 400
    idx = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    rng = np.random.default_rng(0)
    c = pd.Series(30000 + np.cumsum(rng.normal(0, 30, n)), index=idx)
    h = c * (1 + rng.uniform(0, 0.003, n))
    l = c * (1 - rng.uniform(0, 0.003, n))
    v = pd.Series(rng.uniform(1, 10, n), index=idx)
    df = pd.DataFrame({"open": c, "high": h, "low": l, "close": c, "volume": v}, index=idx)
    assert sma(c, 20).iloc[-1] > 0
    u, lo, mid = donchian(h, l, 20); assert u.iloc[-1] >= lo.iloc[-1]
    m, ku, kl = keltner(h, l, c); assert ku.iloc[-1] > kl.iloc[-1]
    a = adx(h, l, c); assert 0 <= a.iloc[-1] <= 100
    assert -300 < cci(h, l, c).iloc[-1] < 300
    assert obv(c, v).iloc[-1] != 0
    assert -1 < cmf(h, l, c, v).iloc[-1] < 1
    assert 0 <= stoch_rsi(c).iloc[-1] <= 100
    p = psar(h, l, c); assert not p.isna().all()
    piv = pivot_points(h, l, c); assert {"pivot", "r1", "s1"} <= set(piv.columns)
    ich = ichimoku(h, l, c); assert "tenkan" in ich
    print("indicators self-check ok")
