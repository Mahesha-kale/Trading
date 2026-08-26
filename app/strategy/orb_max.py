"""Opening Range Breakout — faithful port of Max Options Trading's ORB
(https://www.youtube.com/watch?v=lZn7zVRtAWk).

Crypto trades 24/7 with no market open, so the "opening range" is defined per
*session* (UTC/Asia/London/US). The first `range_bars` bars from the session
open define or_high/or_low; price breaks + retests that range -> entry. This
mirrors the video: break above OR high -> retest -> long; break below OR low ->
retest -> short; stop just beyond the opposite OR edge; 2:1 target. The
failed-breakout reversal toggle plays the opposite side when a break fails
("nothing more bullish than a failed bearish move").

Engine contract: pulse +1/-1 on the retest bar; engine opens at next bar open
and exits via the strategy-provided stop_loss (OR level) + take_profit (2:1).
Run as reversion-kind cfg (use_trailing=False) so the OR-level stop stays fixed.
One entry per session (entered flag); engine stop/TP manages the exit.
"""
from __future__ import annotations

from datetime import time

import numpy as np
import pandas as pd

from app.strategy.base import BaseStrategy, StrategyMeta
from app.strategy.indicators import atr


def _parse_session(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


class ORBMax(BaseStrategy):
    """Session-open opening-range breakout, long + short, OR-level stop, 2:1 TP.

    params:
      range_bars:    bars forming the opening range (video = 1 candle; 4 = 1h on 15m).
      session_open:  "HH:MM" UTC of the session open ("00:00","07:00","14:30").
      reversal:      True = trade the failed-breakout in the opposite direction (12:1).
      rr:            reward:risk target multiple (video = 2.0).
    """
    meta = StrategyMeta(name="orb_max", timeframe="15m", warmup=200)
    kind = "trend"  # exit style is reversion (fixed stop+TP), but signal is breakout
    params = {"range_bars": 4, "session_open": "00:00", "reversal": False, "rr": 2.0,
              "min_visits": 0,
              # retrace-depth entry (§35.18, alphazone RoboQuant reel): 0.0 = touch
              # of the edge + close back outside (video original); >0 = price must
              # retrace that fraction INTO the range, entry AT the touch (reel=0.4).
              "retrace_pct": 0.0,
              # entry style + breakout-strength filters (§35.19, prop-firm reel):
              # entry_mode close = fire AT the breakout-bar close (no retest);
              # min_relvol = signal-bar vol >= x * 20-bar mean vol (0=off);
              # min_atr_pct = ATR14/close >= x (0=off). Filters block the fire,
              # session may re-trigger on a later bar.
              "entry_mode": "retest", "min_relvol": 0.0, "min_atr_pct": 0.0,
              # exit-management variants (§35.14): tp_mode rr|fib|trail, fib level,
              # sl_mode or|atr (vol-adaptive ATR stop off the signal close).
              "tp_mode": "rr", "fib": 2.618, "sl_mode": "or", "atr_mult": 1.5}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        n = len(df)
        sig = pd.Series(0, index=df.index, dtype=int)
        sess_t = _parse_session(p["session_open"])
        rr = float(p["rr"])
        min_visits = int(p["min_visits"])
        # per-bar OR levels + intended side, for stop_loss/take_profit lookup.
        self._or_high = np.full(n, np.nan)
        self._or_low = np.full(n, np.nan)
        self._side = np.zeros(n, dtype=int)
        # ATR(14) for the vol-adaptive ATR stop (sl_mode="atr"); computed once.
        self._atr = atr(df["high"], df["low"], df["close"], 14).to_numpy()
        self._close = df["close"].to_numpy()  # signal-bar close as entry proxy for ATR stop
        if "volume" in df.columns:
            vols = df["volume"].to_numpy(dtype=float)
            vol20 = df["volume"].rolling(20, min_periods=1).mean().to_numpy()  # strength filter
        else:  # no volume feed (synthetic frames) -> relvol filter can't fire-block
            vols = np.full(n, np.nan)
            vol20 = np.full(n, np.nan)

        dates = df.index.normalize()
        highs = df["high"].to_numpy(); lows = df["low"].to_numpy()
        closes = df["close"].to_numpy()
        times = df.index.time

        cur_day = None; in_session = False; counted = 0
        or_high = -np.inf; or_low = np.inf
        armed_long = armed_short = entered = False
        # visit count: pre-break touches of the STOP level (or_low for longs,
        # or_high for shorts). "Put your order where your stop goes and count
        # how many times you get visited" — min_visits filters breakouts whose
        # stop level has been tested >= N times pre-break (validated level).
        visits_long = visits_short = 0

        for i in range(n):
            d = dates[i]
            if d != cur_day:
                cur_day = d; in_session = False; counted = 0
                or_high = -np.inf; or_low = np.inf
                armed_long = armed_short = entered = False
                visits_long = visits_short = 0
            if not in_session:
                if times[i] >= sess_t:
                    in_session = True
                else:
                    continue
            # build the opening range from the first range_bars session bars
            if counted < p["range_bars"]:
                or_high = max(or_high, float(highs[i]))
                or_low = min(or_low, float(lows[i]))
                counted += 1
                continue
            # publish OR levels for this bar (for stop/TP lookup at entry_idx)
            self._or_high[i] = or_high
            self._or_low[i] = or_low

            if entered:
                # arming still tracked so a later reversal/entry isn't missed pre-enter
                if closes[i] > or_high:
                    armed_long = True
                if closes[i] < or_low:
                    armed_short = True
                continue

            c = float(closes[i]); hi = float(highs[i]); lo = float(lows[i])
            fired = 0
            if p.get("entry_mode", "retest") == "close":
                # breakout-close entry (§35.19): fire on any bar CLOSING outside
                # the range (no retest wait). entered guards one-per-session;
                # armed flags irrelevant here.
                if c > or_high:
                    fired = 1
                elif c < or_low:
                    fired = -1
            elif p["reversal"]:
                # failed upside break -> short; failed downside break -> long
                if armed_long and c < or_high:
                    fired = -1
                elif armed_short and c > or_low:
                    fired = 1
            else:
                rp = float(p.get("retrace_pct", 0.0))
                if rp > 0.0 and or_high > or_low:
                    # deep-retrace entry (RoboQuant reel): after the break, price
                    # must retrace rp of the range back inside; entry AT the touch,
                    # no close-back-outside filter.
                    rng_ = or_high - or_low
                    if armed_long and lo <= or_high - rp * rng_:
                        fired = 1
                    elif armed_short and hi >= or_low + rp * rng_:
                        fired = -1
                else:
                    # retest entry: broke above, pulled back to OR high, closed back above
                    if armed_long and lo <= or_high and c > or_high:
                        fired = 1
                    elif armed_short and hi >= or_low and c < or_low:
                        fired = -1
            # visit-count filter: only fire if the stop level was tested >= min_visits
            if fired == 1 and visits_long < min_visits:
                fired = 0
            if fired == -1 and visits_short < min_visits:
                fired = 0
            # breakout-strength filters (§35.19): relative vol + ATR floor. A
            # blocked fire does NOT set entered -- a later bar may still qualify.
            if fired != 0:
                mrv = float(p.get("min_relvol", 0.0))
                if mrv > 0.0:
                    v20 = float(vol20[i])
                    if not np.isfinite(v20) or v20 <= 0 or vols[i] < mrv * v20:
                        fired = 0
            if fired != 0:
                mapct = float(p.get("min_atr_pct", 0.0))
                if mapct > 0.0:
                    a = float(self._atr[i])
                    if not np.isfinite(a) or a / c < mapct:
                        fired = 0
            if fired != 0:
                sig.iloc[i] = fired
                self._side[i] = fired
                entered = True
            # count visits to the stop level pre-break (before the break arms)
            if not armed_long and lo <= or_low:
                visits_long += 1
            if not armed_short and hi >= or_high:
                visits_short += 1
            # arm after the check so the break bar itself doesn't trigger retest
            if c > or_high:
                armed_long = True
            if c < or_low:
                armed_short = True
        return sig

    def stop_loss(self, df: pd.DataFrame, entry_idx) -> float | None:
        s = int(self._side[entry_idx]) if entry_idx < len(self._side) else 0
        if s == 0:
            return None
        if self.params.get("sl_mode", "or") == "atr":
            a = float(self._atr[entry_idx]) if entry_idx < len(self._atr) else np.nan
            c = float(self._close[entry_idx])
            if pd.notna(a) and a > 0:
                return c - s * self.params.get("atr_mult", 1.5) * a
            return None  # fall back to engine % stop
        if s == 1:
            return float(self._or_low[entry_idx])   # long stops below the range
        return float(self._or_high[entry_idx])      # short stops above the range

    def take_profit(self, df: pd.DataFrame, entry_idx) -> float | None:
        s = int(self._side[entry_idx]) if entry_idx < len(self._side) else 0
        if s == 0:
            return None
        mode = self.params.get("tp_mode", "rr")
        if mode == "trail":
            return None  # no TP cap -- let the ATR trailer ride winners
        oh = float(self._or_high[entry_idx]); ol = float(self._or_low[entry_idx])
        risk = oh - ol  # opening range = the risk (entry ≈ the retested edge)
        mult = self.params.get("fib", 2.618) if mode == "fib" else self.params["rr"]
        if s == 1:   # long: entry ≈ or_high, TP = or_high + mult*risk
            return oh + mult * risk
        return ol - mult * risk  # short: entry ≈ or_low, TP = or_low - mult*risk


def _demo() -> None:
    """Self-check on synthetic OHLC: long retest, short retest, OR-level stop/TP,
    failed-breakout reversal, one-entry-per-session, no-trade pre-session."""
    # session 00:00 UTC, range_bars=2. Build a 1-day 15m frame (96 bars).
    idx = pd.date_range("2026-01-01 00:00", periods=96, freq="15min", tz="UTC")
    o = np.full(96, 100.0); h = np.full(96, 100.0); l = np.full(96, 100.0); c = np.full(96, 100.0)
    # bars 0-1: range 100-101. bar 2: break above (close 102). bar 3: retest (low 101, close 101.5>101) -> long.
    h[1] = 101.0; l[1] = 100.0; c[1] = 101.0
    h[2] = 102.0; l[2] = 101.0; c[2] = 102.0  # break above or_high=101
    h[3] = 101.5; l[3] = 101.0; c[3] = 101.5  # retest: low<=101, close>101 -> +1
    df = pd.DataFrame({"open": o, "high": h, "low": l, "close": c}, index=idx)
    s = ORBMax({"range_bars": 2, "session_open": "00:00"}).generate_signals(df)
    assert int(s.iloc[3]) == 1, f"long retest should fire at bar 3, got {s.iloc[3]}"
    strat = ORBMax({"range_bars": 2, "session_open": "00:00"})
    strat.generate_signals(df)
    assert abs(strat.stop_loss(df, 3) - 100.0) < 1e-9, "long stop = or_low = 100"
    assert abs(strat.take_profit(df, 3) - 103.0) < 1e-9, "long TP = or_high + 2*(1) = 103"
    # one entry per session: no further fire after bar 3 even on another retest
    h2 = h.copy(); l2 = l.copy(); c2 = c.copy()
    h2[4] = 101.5; l2[4] = 101.0; c2[4] = 101.5
    df2 = pd.DataFrame({"open": o, "high": h2, "low": l2, "close": c2}, index=idx)
    s2 = ORBMax({"range_bars": 2, "session_open": "00:00"}).generate_signals(df2)
    assert int((s2 == 1).sum()) == 1, "one entry per session"

    # short retest: bar 2 break below or_low=100, bar 3 retest (high>=100, close<100) -> -1
    idxb = pd.date_range("2026-01-01 00:00", periods=96, freq="15min", tz="UTC")
    ob = np.full(96, 101.0); hb = np.full(96, 101.0); lb = np.full(96, 101.0); cb = np.full(96, 101.0)
    hb[1] = 101.0; lb[1] = 100.0; cb[1] = 100.0  # range 100-101
    hb[2] = 100.0; lb[2] = 99.0; cb[2] = 99.0    # break below or_low=100
    hb[3] = 100.0; lb[3] = 99.0; cb[3] = 99.5   # retest: high>=100, close<100? 99.5<100 -> -1
    dfb = pd.DataFrame({"open": ob, "high": hb, "low": lb, "close": cb}, index=idxb)
    sb = ORBMax({"range_bars": 2, "session_open": "00:00"}).generate_signals(dfb)
    assert int(sb.iloc[3]) == -1, f"short retest should fire at bar 3, got {sb.iloc[3]}"

    # failed-breakout reversal: break above then close back below -> short
    idxr = pd.date_range("2026-01-01 00:00", periods=96, freq="15min", tz="UTC")
    oR = np.full(96, 100.0); hR = np.full(96, 100.0); lR = np.full(96, 100.0); cR = np.full(96, 100.0)
    hR[1] = 101.0; lR[1] = 100.0; cR[1] = 101.0
    hR[2] = 102.0; lR[2] = 101.0; cR[2] = 102.0  # break above or_high=101
    hR[3] = 101.5; lR[3] = 100.5; cR[3] = 100.5  # close back below 101 -> failed -> -1
    dfr = pd.DataFrame({"open": oR, "high": hR, "low": lR, "close": cR}, index=idxr)
    sr = ORBMax({"range_bars": 2, "session_open": "00:00", "reversal": True}).generate_signals(dfr)
    assert int(sr.iloc[3]) == -1, f"reversal short should fire at bar 3, got {sr.iloc[3]}"

    # session gating: session_open 07:00 -> no trade before 07:00; range starts at 07:00
    idxs = pd.date_range("2026-01-01 00:00", periods=96, freq="15min", tz="UTC")
    os_ = np.full(96, 100.0); hs_ = np.full(96, 100.0); ls_ = np.full(96, 100.0); cs_ = np.full(96, 100.0)
    # put a break+retest at 02:00 (bar 8) -> must NOT fire (pre-session)
    hs_[8] = 102.0; ls_[8] = 101.0; cs_[8] = 102.0
    hs_[9] = 101.5; ls_[9] = 101.0; cs_[9] = 101.5
    dfs_ = pd.DataFrame({"open": os_, "high": hs_, "low": ls_, "close": cs_}, index=idxs)
    ss_ = ORBMax({"range_bars": 2, "session_open": "07:00"}).generate_signals(dfs_)
    assert int(ss_.iloc[9]) == 0, "no trade before session open"
    # visit-count filter: min_visits requires the stop level (or_low for long)
    # to be tested >= N times pre-break. Build a day where or_low is touched
    # once post-range before the break; min_visits=2 should block the entry.
    idxv = pd.date_range("2026-01-01 00:00", periods=96, freq="15min", tz="UTC")
    ov = np.full(96, 100.0); hv = np.full(96, 100.0); lv = np.full(96, 100.0); cv = np.full(96, 100.0)
    hv[1] = 101.0; lv[1] = 100.0; cv[1] = 101.0          # range 100-101
    lv[2] = 99.5; cv[2] = 100.5                          # visit: low pokes or_low=100 (1 visit)
    hv[3] = 102.0; lv[3] = 101.0; cv[3] = 102.0          # break above or_high=101
    hv[4] = 101.5; lv[4] = 101.0; cv[4] = 101.5         # retest -> +1 (visits_long=1)
    dfv = pd.DataFrame({"open": ov, "high": hv, "low": lv, "close": cv}, index=idxv)
    sv0 = ORBMax({"range_bars": 2, "session_open": "00:00", "min_visits": 0}).generate_signals(dfv)
    assert int(sv0.iloc[4]) == 1, "min_visits=0 should fire"
    sv2 = ORBMax({"range_bars": 2, "session_open": "00:00", "min_visits": 2}).generate_signals(dfv)
    assert int(sv2.iloc[4]) == 0, "min_visits=2 should block (only 1 visit)"
    # retrace-depth entry (retrace_pct=0.5, range 100-101): break above at bar 2,
    # shallow touch at bar 3 (low 100.9 > trigger 100.5) must NOT fire; deep
    # retrace at bar 4 (low 100.4 <= 100.5) fires at the touch even though the
    # close (100.45) is back INSIDE the range (no close-back filter).
    idxd = pd.date_range("2026-01-01 00:00", periods=96, freq="15min", tz="UTC")
    od = np.full(96, 100.0); hd = np.full(96, 100.0); ld = np.full(96, 100.0); cd = np.full(96, 100.0)
    hd[1] = 101.0; ld[1] = 100.0; cd[1] = 101.0   # range 100-101
    hd[2] = 102.0; ld[2] = 101.0; cd[2] = 102.0   # break above or_high=101
    hd[3] = 101.5; ld[3] = 100.9; cd[3] = 101.4   # shallow touch, no fire
    hd[4] = 101.0; ld[4] = 100.4; cd[4] = 100.45  # deep retrace -> +1 at touch
    dfd = pd.DataFrame({"open": od, "high": hd, "low": ld, "close": cd}, index=idxd)
    sd = ORBMax({"range_bars": 2, "session_open": "00:00", "retrace_pct": 0.5}).generate_signals(dfd)
    assert int(sd.iloc[3]) == 0, "shallow touch should not fire at retrace_pct=0.5"
    assert int(sd.iloc[4]) == 1, f"deep retrace should fire at bar 4, got {sd.iloc[4]}"
    # legacy path unchanged: same frame with retrace_pct=0 needs close-back-outside
    sd0 = ORBMax({"range_bars": 2, "session_open": "00:00"}).generate_signals(dfd)
    assert int(sd0.iloc[4]) == 0, "legacy retest needs close > or_high (100.45 < 101)"
    # breakout-close entry (entry_mode="close"): fires AT the breakout bar close,
    # no retest wait; min_relvol blocks weak-volume breaks. Range 100-101, bar 2
    # closes 102 > or_high=101 -> +1 at bar 2 (vs retest mode needing bar 3).
    vd = np.full(96, 100.0)
    vd[2] = 500.0  # breakout bar: ~2.1x the 3-bar mean (233) -> passes min_relvol=2
    dfc = pd.DataFrame({"open": od, "high": hd, "low": ld, "close": cd, "volume": vd}, index=idxd)
    sc1 = ORBMax({"range_bars": 2, "session_open": "00:00", "entry_mode": "close"}).generate_signals(dfc)
    assert int(sc1.iloc[2]) == 1, f"close entry should fire at breakout bar 2, got {sc1.iloc[2]}"
    sc2 = ORBMax({"range_bars": 2, "session_open": "00:00", "entry_mode": "close",
                  "min_relvol": 2.0}).generate_signals(dfc)
    assert int(sc2.iloc[2]) == 1, "strong-volume break passes min_relvol=2"
    sc3 = ORBMax({"range_bars": 2, "session_open": "00:00", "entry_mode": "close",
                  "min_relvol": 4.0}).generate_signals(dfc)
    assert int(sc3.iloc[2]) == 0, "min_relvol=4 blocks the 3x break"
    # blocked fire does not consume the session: bar 3 close still > or_high with
    # fresh volume spike should fire
    vd3 = vd.copy(); vd3[3] = 2500.0  # 3.1x the 4-bar mean (800) once bar2's 500 is in it
    cd3 = cd.copy(); cd3[3] = 101.4  # still above or_high; arm from bar 2 close
    dfc2 = pd.DataFrame({"open": od, "high": hd, "low": ld, "close": cd3, "volume": vd3}, index=idxd)
    sc4 = ORBMax({"range_bars": 2, "session_open": "00:00", "entry_mode": "close",
                  "min_relvol": 3.0}).generate_signals(dfc2)
    assert int(sc4.iloc[3]) == 1, "blocked bar2 -> bar3 re-fires when filter passes"
    print("orb_max self-check OK")


if __name__ == "__main__":
    _demo()