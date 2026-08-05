"""Curated strategy batch for CoinDCX BTC/USDT perp research.

13 strategies spanning SMC/ICT, VWAP, mean-reversion, breakout, momentum,
volume, and pullback methodologies across 1m/5m/15m. All long-only and use
persistent-1 signal semantics: emit +1 every bar while long, 0 to go flat. The
live/paper engine holds on +1 and closes on 0; the backtest engine opens on
the first +1 and exits via its own ATR trailing stop (trend) or fixed stop +
strategy.take_profit (reversion) — see scripts/rank.py cfg selection.

`kind` = "trend" (engine ATR trailing) | "reversion" (engine fixed stop + TP).
Each reversion strategy implements take_profit(); trend strategies let the
trailer run.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.strategy.base import BaseStrategy, StrategyMeta
from app.strategy.indicators import (adx, atr, cci, cmf, donchian, ema, ichimoku,
                                     keltner, obv, psar, rsi, stoch_rsi, vwap)


def _held_series(n: int, idx) -> pd.Series:
    return pd.Series(0, index=idx, dtype=int)


# ---------------- SMC / ICT ----------------

class LiquiditySweep(BaseStrategy):
    """Liquidity sweep (SMC): price wicks below a recent swing low (grabs stop
    liquidity), then closes back above it -> demand swept the supply. Long on
    the reclaim. 1m/5m."""
    meta = StrategyMeta(name="liquidity_sweep", timeframe="5m", warmup=120)
    kind = "trend"
    params = {"swing": 20, "sweep_pen": 0.0015, "atr_period": 14, "atr_mult": 3.0}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        sig = _held_series(len(df), df.index)
        hh = df["high"].rolling(p["swing"]).max().shift(1)
        ll = df["low"].rolling(p["swing"]).min().shift(1)
        a = atr(df["high"], df["low"], df["close"], p["atr_period"])
        pos = 0; trail = np.nan; hw = np.nan
        for i in range(len(df)):
            if pd.isna(ll.iloc[i]) or pd.isna(a.iloc[i]):
                continue
            c = float(df["close"].iloc[i]); lo = float(df["low"].iloc[i]); hi = float(df["high"].iloc[i])
            if pos == 1:
                hw = max(hw, hi); trail = max(trail, hw - p["atr_mult"] * float(a.iloc[i]))
                if c < trail: pos = 0; sig.iloc[i] = 0
                else: sig.iloc[i] = 1
                continue
            r_lo = float(ll.iloc[i])
            if pos == 0 and lo < r_lo * (1 - p["sweep_pen"]) and c > r_lo:
                sig.iloc[i] = 1; pos = 1
                trail = c - p["atr_mult"] * float(a.iloc[i]); hw = hi
        return sig


class FairValueGap(BaseStrategy):
    """Bullish FVG (ICT): a 3-bar imbalance where bar[k-1].high < bar[k+1].low
    (gap up). Price retraces back down into the gap -> long on the reclaim
    (demand imbalance filled). 5m."""
    meta = StrategyMeta(name="fair_value_gap", timeframe="5m", warmup=100)
    kind = "reversion"
    params = {"atr_period": 14, "atr_mult": 2.5}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        sig = _held_series(len(df), df.index)
        a = atr(df["high"], df["low"], df["close"], p["atr_period"])
        highs = df["high"]; lows = df["low"]; closes = df["close"]
        gaps: list[tuple[int, float, float]] = []  # (bar_after_idx, gap_low, gap_high)
        pos = 0; entry = np.nan; tp = np.nan
        for i in range(2, len(df)):
            if pos == 1:
                if float(closes.iloc[i]) >= tp or float(closes.iloc[i]) < entry - p["atr_mult"] * float(a.iloc[i]):
                    pos = 0; sig.iloc[i] = 0
                else:
                    sig.iloc[i] = 1
                continue
            # detect fresh FVG ending at bar i (gap between i-2 high and i low)
            if float(highs.iloc[i - 2]) < float(lows.iloc[i]) and pd.notna(a.iloc[i]):
                gaps.append((i, float(highs.iloc[i - 2]), float(lows.iloc[i])))
            # price retraces into a recent bullish gap -> long
            c = float(closes.iloc[i]); lo = float(lows.iloc[i])
            for gi, glo, ghi in gaps[-8:]:
                if glo <= lo <= ghi and c > glo:  # dipped into gap, closed back above gap low
                    sig.iloc[i] = 1; pos = 1; entry = c
                    tp = c + (c - glo)  # project gap height up as target
                    break
        return sig

    def take_profit(self, df: pd.DataFrame, entry_idx) -> float | None:
        # reversion target handled inline via `tp`; engine TP not used here.
        return None


# ---------------- Session / VWAP ----------------

class OpeningRangeBreakout(BaseStrategy):
    """Opening-range breakout: define the first `range_min` minutes of each UTC
    day; break above that high -> long. 5m/15m."""
    meta = StrategyMeta(name="opening_range_breakout", timeframe="15m", warmup=200)
    kind = "trend"
    params = {"range_bars": 4, "atr_period": 14, "atr_mult": 3.0}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        sig = _held_series(len(df), df.index)
        a = atr(df["high"], df["low"], df["close"], p["atr_period"])
        dates = df.index.normalize()
        or_high = or_low = np.nan; cur_day = None; counted = 0
        pos = 0; trail = np.nan; hw = np.nan
        for i in range(len(df)):
            d = dates[i]
            if d != cur_day:
                cur_day = d; counted = 0; or_high = -np.inf; or_low = np.inf
            if counted < p["range_bars"]:
                or_high = max(or_high, float(df["high"].iloc[i]))
                or_low = min(or_low, float(df["low"].iloc[i]))
                counted += 1
                continue
            c = float(df["close"].iloc[i]); hi = float(df["high"].iloc[i])
            if pos == 1:
                hw = max(hw, hi); trail = max(trail, hw - p["atr_mult"] * float(a.iloc[i]))
                if c < trail: pos = 0; sig.iloc[i] = 0
                else: sig.iloc[i] = 1
                continue
            if pd.notna(a.iloc[i]) and c > or_high:
                sig.iloc[i] = 1; pos = 1
                trail = c - p["atr_mult"] * float(a.iloc[i]); hw = hi
        return sig


class VwapPullback(BaseStrategy):
    """VWAP pullback: price above rising session VWAP (intraday uptrend),
    pulls back to within `tol` of VWAP -> long. 5m."""
    meta = StrategyMeta(name="vwap_pullback", timeframe="5m", warmup=80)
    kind = "trend"
    params = {"tol_atr": 0.5, "atr_period": 14, "atr_mult": 2.5}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        sig = _held_series(len(df), df.index)
        v = vwap(df)
        a = atr(df["high"], df["low"], df["close"], p["atr_period"])
        pos = 0; trail = np.nan; hw = np.nan
        for i in range(1, len(df)):
            if pd.isna(v.iloc[i]) or pd.isna(a.iloc[i]):
                continue
            c = float(df["close"].iloc[i]); hi = float(df["high"].iloc[i])
            if pos == 1:
                hw = max(hw, hi); trail = max(trail, hw - p["atr_mult"] * float(a.iloc[i]))
                if c < trail: pos = 0; sig.iloc[i] = 0
                else: sig.iloc[i] = 1
                continue
            uptrend = float(v.iloc[i]) > float(v.iloc[i - 1]) and c > float(v.iloc[i])
            pulled = abs(float(df["low"].iloc[i]) - float(v.iloc[i])) <= p["tol_atr"] * float(a.iloc[i])
            if uptrend and pulled and c > float(v.iloc[i]):
                sig.iloc[i] = 1; pos = 1
                trail = c - p["atr_mult"] * float(a.iloc[i]); hw = hi
        return sig


# ---------------- Mean reversion ----------------

class KeltnerMeanReversion(BaseStrategy):
    """Keltner mean reversion: close < lower Keltner band (overextension down)
    -> long; target the Keltner mid. 5m."""
    meta = StrategyMeta(name="keltner_mr", timeframe="5m", warmup=100)
    kind = "reversion"
    params = {"period": 20, "mult": 2.0, "atr_period": 14, "atr_mult": 2.5}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        sig = _held_series(len(df), df.index)
        mid, up, lo = keltner(df["high"], df["low"], df["close"], p["period"], p["mult"])
        a = atr(df["high"], df["low"], df["close"], p["atr_period"])
        pos = 0; entry = np.nan; tp = np.nan
        for i in range(len(df)):
            if pd.isna(lo.iloc[i]): continue
            c = float(df["close"].iloc[i])
            if pos == 1:
                if c >= tp or c < entry - p["atr_mult"] * float(a.iloc[i]):
                    pos = 0; sig.iloc[i] = 0
                else: sig.iloc[i] = 1
                continue
            if c < float(lo.iloc[i]) and pd.notna(mid.iloc[i]):
                sig.iloc[i] = 1; pos = 1; entry = c; tp = float(mid.iloc[i])
        return sig

    def take_profit(self, df: pd.DataFrame, entry_idx) -> float | None:
        p = self.params
        mid, _, _ = keltner(df["high"], df["low"], df["close"], p["period"], p["mult"])
        return float(mid.iloc[entry_idx]) if pd.notna(mid.iloc[entry_idx]) else None


class StochrsiReversal(BaseStrategy):
    """StochRSI reversal: StochRSI < 20 (oversold) and curling up -> long;
    target the 50 mid. 5m."""
    meta = StrategyMeta(name="stochrsi_reversal", timeframe="5m", warmup=80)
    kind = "reversion"
    params = {"rsi_period": 14, "stoch_period": 14, "atr_period": 14, "atr_mult": 2.5,
              "tp_mult": 2.0}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        sig = _held_series(len(df), df.index)
        s = stoch_rsi(df["close"], p["rsi_period"], p["stoch_period"])
        a = atr(df["high"], df["low"], df["close"], p["atr_period"])
        pos = 0; entry = np.nan; tp = np.nan
        for i in range(2, len(df)):
            if pd.isna(s.iloc[i]): continue
            c = float(df["close"].iloc[i])
            if pos == 1:
                if c >= tp or c < entry - p["atr_mult"] * float(a.iloc[i]):
                    pos = 0; sig.iloc[i] = 0
                else: sig.iloc[i] = 1
                continue
            if float(s.iloc[i - 1]) < 20 and float(s.iloc[i]) > float(s.iloc[i - 1]) \
                    and float(df["close"].iloc[i]) > float(df["close"].iloc[i - 1]):
                sig.iloc[i] = 1; pos = 1; entry = c
                tp = c + p["tp_mult"] * float(a.iloc[i])  # tp_mult ATR target
        return sig

    def take_profit(self, df: pd.DataFrame, entry_idx) -> float | None:
        p = self.params
        a = atr(df["high"], df["low"], df["close"], p["atr_period"])
        if pd.isna(a.iloc[entry_idx]): return None
        return float(df["close"].iloc[entry_idx]) + p["tp_mult"] * float(a.iloc[entry_idx])


class CciReversion(BaseStrategy):
    """CCI reversion: CCI < -100 (oversold) -> long; target CCI back to 0
    (~price at SMA). 5m."""
    meta = StrategyMeta(name="cci_reversion", timeframe="5m", warmup=60)
    kind = "reversion"
    params = {"period": 20, "atr_period": 14, "atr_mult": 2.5}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        sig = _held_series(len(df), df.index)
        c = cci(df["high"], df["low"], df["close"], p["period"])
        sma_c = df["close"].rolling(p["period"]).mean()
        a = atr(df["high"], df["low"], df["close"], p["atr_period"])
        pos = 0; entry = np.nan; tp = np.nan
        for i in range(len(df)):
            if pd.isna(c.iloc[i]): continue
            cc = float(df["close"].iloc[i])
            if pos == 1:
                if cc >= tp or cc < entry - p["atr_mult"] * float(a.iloc[i]):
                    pos = 0; sig.iloc[i] = 0
                else: sig.iloc[i] = 1
                continue
            if float(c.iloc[i]) < -100 and pd.notna(sma_c.iloc[i]):
                sig.iloc[i] = 1; pos = 1; entry = cc; tp = float(sma_c.iloc[i])
        return sig

    def take_profit(self, df: pd.DataFrame, entry_idx) -> float | None:
        p = self.params
        sma_c = df["close"].rolling(p["period"]).mean()
        return float(sma_c.iloc[entry_idx]) if pd.notna(sma_c.iloc[entry_idx]) else None


# ---------------- Momentum / trend ----------------

class AdxTrend(BaseStrategy):
    """ADX trend: ADX > threshold (strong trend) + fast EMA > slow EMA -> long
    on the trend. 15m."""
    meta = StrategyMeta(name="adx_trend", timeframe="15m", warmup=200)
    kind = "trend"
    params = {"adx_period": 14, "adx_thresh": 25, "fast": 20, "slow": 50,
              "atr_period": 14, "atr_mult": 3.0}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        sig = _held_series(len(df), df.index)
        ad = adx(df["high"], df["low"], df["close"], p["adx_period"])
        ef = ema(df["close"], p["fast"]); es = ema(df["close"], p["slow"])
        a = atr(df["high"], df["low"], df["close"], p["atr_period"])
        pos = 0; trail = np.nan; hw = np.nan
        for i in range(1, len(df)):
            if pd.isna(ad.iloc[i]) or pd.isna(a.iloc[i]): continue
            c = float(df["close"].iloc[i]); hi = float(df["high"].iloc[i])
            if pos == 1:
                hw = max(hw, hi); trail = max(trail, hw - p["atr_mult"] * float(a.iloc[i]))
                if c < trail: pos = 0; sig.iloc[i] = 0
                else: sig.iloc[i] = 1
                continue
            if float(ad.iloc[i]) > p["adx_thresh"] and float(ef.iloc[i]) > float(es.iloc[i]) \
                    and c > float(df["close"].iloc[i - 1]):
                sig.iloc[i] = 1; pos = 1
                trail = c - p["atr_mult"] * float(a.iloc[i]); hw = hi
        return sig


class DonchianBreakout(BaseStrategy):
    """Donchian breakout + ADX filter: close > N-bar high with ADX rising
    (breakout with momentum, not chop). 15m."""
    meta = StrategyMeta(name="donchian_breakout", timeframe="15m", warmup=200)
    kind = "trend"
    params = {"lookback": 40, "adx_period": 14, "adx_thresh": 20,
              "atr_period": 14, "atr_mult": 3.0}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        sig = _held_series(len(df), df.index)
        up, lo, _ = donchian(df["high"], df["low"], p["lookback"])
        ad = adx(df["high"], df["low"], df["close"], p["adx_period"])
        a = atr(df["high"], df["low"], df["close"], p["atr_period"])
        pos = 0; trail = np.nan; hw = np.nan
        for i in range(1, len(df)):
            if pd.isna(up.iloc[i]) or pd.isna(a.iloc[i]): continue
            c = float(df["close"].iloc[i]); hi = float(df["high"].iloc[i])
            if pos == 1:
                hw = max(hw, hi); trail = max(trail, hw - p["atr_mult"] * float(a.iloc[i]))
                if c < trail: pos = 0; sig.iloc[i] = 0
                else: sig.iloc[i] = 1
                continue
            if c > float(up.iloc[i]) and float(ad.iloc[i]) > p["adx_thresh"]:
                sig.iloc[i] = 1; pos = 1
                trail = c - p["atr_mult"] * float(a.iloc[i]); hw = hi
        return sig


class IchimokuBreakout(BaseStrategy):
    """Ichimoku: price above the cloud + tenkan > kijun (bullish) -> long.
    Exit when price falls back through the cloud bottom. 15m."""
    meta = StrategyMeta(name="ichimoku_breakout", timeframe="15m", warmup=120)
    kind = "trend"
    params = {"tenkan": 9, "kijun": 26, "senkou_b": 52, "atr_period": 14, "atr_mult": 3.0}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        sig = _held_series(len(df), df.index)
        ich = ichimoku(df["high"], df["low"], df["close"], p["tenkan"], p["kijun"], p["senkou_b"])
        tk, kj, sa, sb = ich["tenkan"], ich["kijun"], ich["span_a"], ich["span_b"]
        a = atr(df["high"], df["low"], df["close"], p["atr_period"])
        pos = 0; trail = np.nan; hw = np.nan
        for i in range(1, len(df)):
            if pd.isna(sa.iloc[i]) or pd.isna(sb.iloc[i]) or pd.isna(a.iloc[i]): continue
            c = float(df["close"].iloc[i]); hi = float(df["high"].iloc[i])
            cloud_top = max(float(sa.iloc[i]), float(sb.iloc[i]))
            cloud_bot = min(float(sa.iloc[i]), float(sb.iloc[i]))
            if pos == 1:
                hw = max(hw, hi); trail = max(trail, hw - p["atr_mult"] * float(a.iloc[i]))
                if c < trail or c < cloud_bot: pos = 0; sig.iloc[i] = 0
                else: sig.iloc[i] = 1
                continue
            if c > cloud_top and float(tk.iloc[i]) > float(kj.iloc[i]):
                sig.iloc[i] = 1; pos = 1
                trail = c - p["atr_mult"] * float(a.iloc[i]); hw = hi
        return sig


class PsarTrend(BaseStrategy):
    """Parabolic SAR trend: PSAR flips below price (uptrend start) -> long;
    exit when PSAR flips above (downtrend). 15m."""
    meta = StrategyMeta(name="psar_trend", timeframe="15m", warmup=100)
    kind = "trend"
    params = {"step": 0.02, "max_step": 0.2, "atr_period": 14, "atr_mult": 3.0}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        sig = _held_series(len(df), df.index)
        s = psar(df["high"], df["low"], df["close"], p["step"], p["max_step"])
        a = atr(df["high"], df["low"], df["close"], p["atr_period"])
        pos = 0; trail = np.nan; hw = np.nan
        for i in range(2, len(df)):
            if pd.isna(s.iloc[i]) or pd.isna(s.iloc[i - 1]) or pd.isna(a.iloc[i]): continue
            c = float(df["close"].iloc[i]); hi = float(df["high"].iloc[i])
            if pos == 1:
                hw = max(hw, hi); trail = max(trail, hw - p["atr_mult"] * float(a.iloc[i]))
                below = float(s.iloc[i]) < c  # SAR still below -> uptrend intact
                if (not below) or c < trail: pos = 0; sig.iloc[i] = 0
                else: sig.iloc[i] = 1
                continue
            # flip: SAR was above prev close, now below current close
            if float(s.iloc[i - 1]) > float(df["close"].iloc[i - 1]) and float(s.iloc[i]) < c:
                sig.iloc[i] = 1; pos = 1
                trail = c - p["atr_mult"] * float(a.iloc[i]); hw = hi
        return sig


class ObvDivergence(BaseStrategy):
    """OBV bullish divergence: price makes a higher low while OBV makes a
    higher low (accumulation) -> long on confirmation. 15m."""
    meta = StrategyMeta(name="obv_divergence", timeframe="15m", warmup=200)
    kind = "trend"
    params = {"swing": 30, "atr_period": 14, "atr_mult": 3.0}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        sig = _held_series(len(df), df.index)
        o = obv(df["close"], df["volume"])
        ll = df["low"].rolling(p["swing"]).min()
        oll = o.rolling(p["swing"]).min()
        a = atr(df["high"], df["low"], df["close"], p["atr_period"])
        pos = 0; trail = np.nan; hw = np.nan
        for i in range(p["swing"], len(df)):
            if pd.isna(ll.iloc[i]) or pd.isna(oll.iloc[i]) or pd.isna(a.iloc[i]): continue
            c = float(df["close"].iloc[i]); hi = float(df["high"].iloc[i])
            if pos == 1:
                hw = max(hw, hi); trail = max(trail, hw - p["atr_mult"] * float(a.iloc[i]))
                if c < trail: pos = 0; sig.iloc[i] = 0
                else: sig.iloc[i] = 1
                continue
            # recent low above prior swing low (price higher low) AND OBV higher low
            prev_low = float(ll.iloc[i - 1]); cur_low = float(df["low"].iloc[i])
            prev_o = float(oll.iloc[i - 1]); cur_o = float(o.iloc[i])
            if cur_low > prev_low and cur_o > prev_o and c > float(df["close"].iloc[i - 1]):
                sig.iloc[i] = 1; pos = 1
                trail = c - p["atr_mult"] * float(a.iloc[i]); hw = hi
        return sig


class EmaPullback(BaseStrategy):
    """EMA pullback: EMA50 > EMA200 (uptrend), price pulls back to EMA20 and
    bounces -> long. 15m."""
    meta = StrategyMeta(name="ema_pullback", timeframe="15m", warmup=250)
    kind = "trend"
    params = {"pullback_ema": 20, "fast": 50, "slow": 200,
              "tol_atr": 0.5, "atr_period": 14, "atr_mult": 3.0}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        sig = _held_series(len(df), df.index)
        e20 = ema(df["close"], p["pullback_ema"]); e50 = ema(df["close"], p["fast"]); e200 = ema(df["close"], p["slow"])
        a = atr(df["high"], df["low"], df["close"], p["atr_period"])
        pos = 0; trail = np.nan; hw = np.nan
        for i in range(2, len(df)):
            if pd.isna(e200.iloc[i]) or pd.isna(a.iloc[i]): continue
            c = float(df["close"].iloc[i]); hi = float(df["high"].iloc[i]); lo = float(df["low"].iloc[i])
            if pos == 1:
                hw = max(hw, hi); trail = max(trail, hw - p["atr_mult"] * float(a.iloc[i]))
                if c < trail: pos = 0; sig.iloc[i] = 0
                else: sig.iloc[i] = 1
                continue
            uptrend = float(e50.iloc[i]) > float(e200.iloc[i])
            near = abs(lo - float(e20.iloc[i])) <= p["tol_atr"] * float(a.iloc[i])
            bounced = c > float(df["close"].iloc[i - 1]) and c > float(e20.iloc[i])
            if uptrend and near and bounced:
                sig.iloc[i] = 1; pos = 1
                trail = c - p["atr_mult"] * float(a.iloc[i]); hw = hi
        return sig


# ---------------- Regime gate ----------------

class RegimeGate(BaseStrategy):
    """Regime router. Tag each bar bull/bear/sideways (EMA-slope + ADX), then take
    entries only from the strategy assigned to the current regime; flat otherwise.

    Evidence (docs/strategies_report.md): no static strategy is profitable
    full-sample, but edge is regime-conditional — ema_pullback wins sideways+bear,
    stochrsi wins bull (on 5m). This gate captures that: trade the sideways/bear
    book via ema_pullback, flat (or stochrsi) in bull. One timeframe (15m) so all
    subs share the df.

    Backtest engine ignores the signal while in position (exits via its own
    trailing stop), so the gate only needs sub-strategy ENTRY transitions; it
    holds persistent-1 and emits 0 only when the regime flips to an unassigned
    (flat) one. Live engine mirrors this (hold on 1, close on 0).

    params:
      bull/sideways/bear: registry name of sub-strategy, or None = flat.
      ema_period: slow EMA for slope regime tag.
      adx_period/thresh: ADX < thresh -> sideways; else trend by slope.
    """
    meta = StrategyMeta(name="regime_gate", timeframe="15m", warmup=250)
    kind = "trend"  # engine ATR trailing exits both trend + reversion subs acceptably
    params = {"bull": None, "sideways": "ema_pullback", "bear": "ema_pullback",
              "ema_period": 200, "adx_period": 14, "adx_thresh": 20,
              "atr_period": 14, "atr_mult": 3.0}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        from app.strategy.registry import get_strategy  # local: avoid import cycle
        sig = _held_series(len(df), df.index)
        regime = self._regime(df, p)
        # precompute each assigned sub's signal series once (entry triggers live in it)
        subs: dict[str, pd.Series] = {}
        for r, nm in (("bull", p["bull"]), ("sideways", p["sideways"]), ("bear", p["bear"])):
            if nm:
                try:
                    subs[r] = get_strategy(nm, {}).generate_signals(df)
                except Exception:
                    subs[r] = pd.Series(0, index=df.index, dtype=int)
        pos = 0
        for i in range(len(df)):
            r = regime.iloc[i]
            if not isinstance(r, str) or r not in p or i < 1:
                if pos == 1:
                    sig.iloc[i] = 1  # hold through NaN regime (warmup)
                continue
            nm = p[r]  # sub-strategy name for this regime (None = flat)
            if pos == 1:
                if nm is None:           # regime flipped to flat -> exit
                    pos = 0; sig.iloc[i] = 0
                else:                    # hold; engine trailing manages the stop
                    sig.iloc[i] = 1
                continue
            if nm and r in subs:        # enter on sub's 0->1 transition
                s = subs[r]
                if s.iloc[i - 1] != 1 and s.iloc[i] == 1:
                    sig.iloc[i] = 1; pos = 1
        return sig

    def _regime(self, df: pd.DataFrame, p: dict) -> pd.Series:
        close = df["close"]
        e = close.ewm(span=p["ema_period"], adjust=False).mean()
        slope = e.diff(p["ema_period"] // 4)
        thr = close * 0.001
        a = adx(df["high"], df["low"], df["close"], p["adx_period"])
        tag = pd.Series("sideways", index=df.index)
        trending = a > p["adx_thresh"]
        tag[(slope > thr) & trending] = "bull"
        tag[(slope < -thr) & trending] = "bear"
        return tag


if __name__ == "__main__":
    # self-check: each strategy runs on synthetic data and produces a Series.
    n = 600
    idx = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    rng = np.random.default_rng(1)
    c = pd.Series(30000 + np.cumsum(rng.normal(0, 40, n)), index=idx)
    h = c * (1 + rng.uniform(0, 0.004, n)); l = c * (1 - rng.uniform(0, 0.004, n))
    v = pd.Series(rng.uniform(1, 20, n), index=idx)
    df = pd.DataFrame({"open": c, "high": h, "low": l, "close": c, "volume": v}, index=idx)
    for cls in [LiquiditySweep, FairValueGap, OpeningRangeBreakout, VwapPullback,
                KeltnerMeanReversion, StochrsiReversal, CciReversion, AdxTrend,
                DonchianBreakout, IchimokuBreakout, PsarTrend, ObvDivergence,
                EmaPullback, RegimeGate]:
        s = cls().generate_signals(df)
        assert s.dtype == int and len(s) == n, cls.meta.name
        print(f"{cls.meta.name:24s} ok  signals={int((s==1).sum())} kind={cls.kind}")