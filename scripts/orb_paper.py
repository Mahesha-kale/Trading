"""ORB live paper trader (sub-project 7, §35.17).

Bar-driven paper runner for orb_max on Binance USDT-M perp public klines.
NOT the carry funding/tick loop (scripts/carry_trader.py) -- ORB is OHLC-bar:
session-open range, retest entry, OR-level stop, 2:1 TP. Polls 15m klines every
60s, acts only on CLOSED candles (no look-ahead). One position per asset,
single-position model (mirrors app/backtest/engine.py:163).

Research verdict stands: §35.16 NY+Asia 0/40 pass K-fold, CIlo<0. This is
OBSERVATION, not deployment. $200 notional/trade, lev 3, real perp costs
(maker 0.025%/taker 0.06%/2bps slip). Honest paper PnL.

run:  python -m scripts.orb_paper                 # paper, ETH+PAXG, 60s poll
      python -m scripts.orb_paper --capital 1000 --notional 200
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.request import urlopen

import pandas as pd

from app.logging import configure_logging
from app.strategy.registry import get_strategy

configure_logging()
log = logging.getLogger("orb_paper")
REPORTS = Path("reports")
LEDGER = REPORTS / "orb_paper.csv"
STATE_PATH = REPORTS / "orb_paper_state.json"
KLINES = "https://fapi.binance.com/fapi/v1/klines"

# per-asset config: ETH from §35.19 closest-ever cell (close entry + relvol 2.0
# filter -- INDETERMINATE not refuted: 4/4 folds +, net +3573, killed only by
# CIlo=-0.06; live-forward resolves the bootstrap); PAXG from §35.16 (refuted,
# kept as control). Exit E1 (rr2, OR stop).
ASSETS = [
    {"sym": "ETHUSDT", "session_open": "13:00", "range_bars": 3,
     "entry_mode": "close", "min_relvol": 2.0},                     # ETH NY close+rv2
    {"sym": "PAXGUSDT", "session_open": "00:00", "range_bars": 5},  # XAU Asia retest
]
TF = "15m"
POLL_S = 60
LIMIT = 300               # klines to fetch (warmup 200 + range + buffer)
MAKER = 0.00025
TAKER = 0.0006
SLIP = 0.0002             # 2bps each side
LEV = 3
MAX_DD = 0.25


@dataclass
class Pos:
    side: int = 0          # 0 flat, +1 long, -1 short
    qty: float = 0.0       # base-asset qty (notional/entry)
    entry: float = 0.0
    stop: float = 0.0
    tp: float = 0.0
    entry_ts: int = 0


@dataclass
class AssetState:
    sym: str = ""
    last_bar_ot: int = 0   # last processed bar openTime (ms)
    pos: Pos = field(default_factory=Pos)
    equity: float = 0.0
    peak: float = 0.0
    halted: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AssetState":
        p = d.pop("pos", {})
        st = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        st.pos = Pos(**{k: v for k, v in p.items() if k in Pos.__dataclass_fields__})
        return st


def fetch_klines(sym: str, interval: str = TF, limit: int = LIMIT) -> pd.DataFrame:
    """Binance USDT-M public klines -> OHLCV df of CLOSED bars only.
    Row: [openTime, open, high, low, close, volume, closeTime, ...].
    Last row is the in-progress candle -> drop it (closeTime in the future)."""
    url = f"{KLINES}?symbol={sym}&interval={interval}&limit={limit}"
    raw = json.load(urlopen(url, timeout=15))
    now_ms = int(time.time() * 1000)
    rows = [r for r in raw if int(r[6]) <= now_ms]   # closeTime <= now = closed
    if not rows:
        return pd.DataFrame()
    # Binance kline row has 12 fields; keep first 7 (ot,o,h,l,c,v,closeTime).
    df = pd.DataFrame([r[:7] for r in rows], columns=["ot", "o", "h", "l", "c", "v", "ct"])
    df["open"] = df["o"].astype(float)
    df["high"] = df["h"].astype(float)
    df["low"] = df["l"].astype(float)
    df["close"] = df["c"].astype(float)
    df["volume"] = df["v"].astype(float)
    df.index = pd.to_datetime(df["ot"], unit="ms", utc=True)
    return df[["open", "high", "low", "close", "volume"]].sort_index()


def _round_trip_cost(notional: float) -> float:
    """Taker both sides (market entry/exit) + 2bps slippage each side."""
    return 2 * (TAKER + SLIP) * notional


def _process_bar(st: AssetState, cfg: dict, df: pd.DataFrame, i: int,
                 notional: float) -> list[dict]:
    """Process one closed bar i. Returns ledger rows to append."""
    out = []
    bar = df.iloc[i]
    ot = int(bar.name.timestamp() * 1000)
    hi, lo, c = float(bar["high"]), float(bar["low"]), float(bar["close"])

    # 1. exit-check on an already-open position (entry bar does not exit-check)
    if st.pos.side != 0:
        hit = None
        if st.pos.side == 1:
            if lo <= st.pos.stop:
                hit = ("EXIT_SL", st.pos.stop)
            elif st.pos.tp and hi >= st.pos.tp:
                hit = ("EXIT_TP", st.pos.tp)
        else:  # short
            if hi >= st.pos.stop:
                hit = ("EXIT_SL", st.pos.stop)
            elif st.pos.tp and lo <= st.pos.tp:
                hit = ("EXIT_TP", st.pos.tp)
        if hit:
            ev, px = hit
            gross = st.pos.side * (px - st.pos.entry) * st.pos.qty
            pnl = gross - _round_trip_cost(notional)
            st.equity += pnl
            st.peak = max(st.peak, st.equity)
            out.append({"ts": ot, "sym": st.sym, "event": ev, "price": round(px, 6),
                        "qty": st.pos.qty, "pnl": round(pnl, 4),
                        "equity": round(st.equity, 4)})
            st.pos = Pos()

    # 2. entry-check only when flat
    if st.pos.side == 0:
        sub = df.iloc[: i + 1]
        strat = get_strategy("orb_max", {**cfg, "rr": 2.0, "tp_mode": "rr",
                                          "sl_mode": "or", "reversal": False})
        sig = strat.generate_signals(sub)
        s = int(sig.iloc[i])
        if s != 0:
            stop = strat.stop_loss(sub, i)
            tp = strat.take_profit(sub, i)
            if stop is None or tp is None:
                return out  # no valid levels -> skip (fall back would be guessing)
            qty = notional / c
            st.pos = Pos(side=s, qty=qty, entry=c, stop=float(stop),
                         tp=float(tp), entry_ts=ot)
            out.append({"ts": ot, "sym": st.sym,
                        "event": "ENTER_LONG" if s == 1 else "ENTER_SHORT",
                        "price": round(c, 6), "qty": round(qty, 6),
                        "pnl": 0.0, "equity": round(st.equity, 4)})
    return out


def _dd_halt(st: AssetState, last_close: float, notional: float) -> list[dict]:
    """If DD breached, force-flatten open pos at last_close (realize) + halt.
    Returns ledger rows (the force-exit), empty if no halt."""
    if st.peak <= 0:
        return []
    dd = (st.peak - st.equity) / st.peak
    if dd < MAX_DD:
        return []
    out = []
    if st.pos.side != 0 and last_close > 0:
        gross = st.pos.side * (last_close - st.pos.entry) * st.pos.qty
        pnl = gross - _round_trip_cost(notional)
        st.equity += pnl
        out.append({"ts": int(time.time() * 1000), "sym": st.sym,
                     "event": "EXIT_DD", "price": round(last_close, 6),
                     "qty": st.pos.qty, "pnl": round(pnl, 4),
                     "equity": round(st.equity, 4)})
        st.pos = Pos()
    st.halted = True
    out.append({"ts": int(time.time() * 1000), "sym": st.sym, "event": "DD_HALT",
                 "price": "", "qty": "", "pnl": "", "equity": round(st.equity, 4)})
    log.warning("%s DD halt dd=%.2f peak=%.0f eq=%.0f", st.sym, dd, st.peak, st.equity)
    return out


def _ledger_append(rows: list[dict]) -> None:
    if not rows:
        return
    new = not LEDGER.exists()
    with open(LEDGER, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ts", "sym", "event", "price", "qty",
                                          "pnl", "equity"])
        if new:
            w.writeheader()
        for r in rows:
            w.writerow(r)


def _save_state(states: dict, capital: float) -> None:
    d = {"capital": capital, "assets": {k: v.to_dict() for k, v in states.items()}}
    STATE_PATH.write_text(json.dumps(d, indent=2, default=str))


def _load_state(capital: float) -> dict:
    states = {}
    if STATE_PATH.exists():
        try:
            d = json.loads(STATE_PATH.read_text())
            for k, v in d.get("assets", {}).items():
                states[k] = AssetState.from_dict(v)
        except (json.JSONDecodeError, OSError, TypeError):
            log.warning("state corrupt -> fresh")
    for a in ASSETS:
        states.setdefault(a["sym"], AssetState(sym=a["sym"], equity=capital, peak=capital))
        states[a["sym"]].sym = a["sym"]
        if states[a["sym"]].equity == 0.0:
            states[a["sym"]].equity = capital
            states[a["sym"]].peak = capital
    return states


async def poll_once(states: dict, capital: float, notional: float) -> None:
    for cfg in ASSETS:
        sym = cfg["sym"]
        st = states[sym]
        if st.halted:
            continue
        try:
            df = await asyncio.to_thread(fetch_klines, sym)
        except Exception as e:  # noqa: BLE001 - feed fault boundary
            log.warning("%s feed error: %s", sym, str(e)[:80])
            continue
        if df.empty or len(df) < 30:
            continue
        # process every new closed bar since last_bar_ot, in order
        new_rows = []
        for i in range(len(df)):
            ot = int(df.index[i].timestamp() * 1000)
            if ot <= st.last_bar_ot:
                continue
            new_rows.extend(_process_bar(st, cfg, df, i, notional))
            st.last_bar_ot = ot
        _ledger_append(new_rows)
        if new_rows:
            log.info("%s: %d events eq=%.2f pos=%s", sym, len(new_rows),
                     st.equity, st.pos.side)
        last_close = float(df.iloc[-1]["close"])
        halt_rows = _dd_halt(st, last_close, notional)
        if halt_rows:
            _ledger_append(halt_rows)
    _save_state(states, capital)


async def run_loop(capital: float, notional: float) -> None:
    states = _load_state(capital)
    # seed last_bar_ot to the latest CLOSED bar on a fresh state so we only
    # process LIVE-FORWARD bars (no historical backfill into the ledger).
    for cfg in ASSETS:
        st = states[cfg["sym"]]
        if st.last_bar_ot != 0:
            continue
        try:
            df = await asyncio.to_thread(fetch_klines, cfg["sym"])
        except Exception as e:  # noqa: BLE001
            log.warning("%s seed fetch failed: %s", cfg["sym"], str(e)[:80])
            continue
        if not df.empty:
            st.last_bar_ot = int(df.index[-1].timestamp() * 1000)
            log.info("%s seeded last_bar_ot=%d (live-forward from here)", st.sym, st.last_bar_ot)
    _save_state(states, capital)
    log.info("orb_paper start capital=%s notional=%s assets=%s",
             capital, notional, [a["sym"] for a in ASSETS])
    while True:
        await poll_once(states, capital, notional)
        await asyncio.sleep(POLL_S)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=1000.0)
    ap.add_argument("--notional", type=float, default=200.0,
                    help="notional per trade in USDT")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run_loop(args.capital, args.notional))


def demo() -> None:
    """Self-check: fetch live klines, run one bar through _process_bar, verify
    signal/SL/TP plumbing + ledger + state round-trip. No network skip -- uses
    a fixed synthetic frame so it runs offline."""
    import numpy as np
    idx = pd.date_range("2026-01-01 00:00", periods=96, freq="15min", tz="UTC")
    o = np.full(96, 100.0); h = np.full(96, 100.0); l = np.full(96, 100.0)
    c = np.full(96, 100.0)
    h[1] = 101.0; l[1] = 100.0; c[1] = 101.0
    h[2] = 102.0; l[2] = 101.0; c[2] = 102.0   # break above or_high=101
    h[3] = 101.5; l[3] = 101.0; c[3] = 101.5   # retest -> +1
    df = pd.DataFrame({"open": o, "high": h, "low": l, "close": c}, index=idx)
    st = AssetState(sym="TEST", equity=1000.0, peak=1000.0)
    cfg = {"sym": "TEST", "session_open": "00:00", "range_bars": 2}
    rows = _process_bar(st, cfg, df, 3, notional=200.0)
    assert st.pos.side == 1, ("should enter long at bar 3", st.pos.side)
    assert abs(st.pos.entry - 101.5) < 1e-9
    assert abs(st.pos.stop - 100.0) < 1e-9, "long stop = or_low"
    assert abs(st.pos.tp - 103.0) < 1e-9, "long TP = or_high + 2*risk"
    assert rows[0]["event"] == "ENTER_LONG" and rows[0]["price"] == 101.5
    # next bar hits TP (high 103.5 >= 103, low 101.6 > stop 100) -> exit TP
    h2 = h.copy(); h2[4] = 103.5; c2 = c.copy(); c2[4] = 103.0
    l2 = l.copy(); l2[4] = 101.6
    df2 = pd.DataFrame({"open": o, "high": h2, "low": l2, "close": c2}, index=idx)
    rows2 = _process_bar(st, cfg, df2, 4, notional=200.0)
    assert st.pos.side == 0, "should exit on TP"
    assert rows2[0]["event"] == "EXIT_TP"
    gross = 1 * (103.0 - 101.5) * (200.0 / 101.5)
    assert abs(rows2[0]["pnl"] - round(gross - _round_trip_cost(200.0), 4)) < 1e-6
    assert abs(st.equity - (1000.0 + rows2[0]["pnl"])) < 1e-3
    # state round-trip
    st.last_bar_ot = 12345
    d = st.to_dict(); st2 = AssetState.from_dict(d)
    assert st2.pos.side == 0 and st2.last_bar_ot == 12345 and abs(st2.equity - st.equity) < 1e-9
    # short entry + SL exit
    ob = np.full(96, 101.0); hb = np.full(96, 101.0); lb = np.full(96, 101.0); cb = np.full(96, 101.0)
    hb[1] = 101.0; lb[1] = 100.0; cb[1] = 100.0
    hb[2] = 100.0; lb[2] = 99.0; cb[2] = 99.0
    hb[3] = 100.0; lb[3] = 99.0; cb[3] = 99.5
    dfb = pd.DataFrame({"open": ob, "high": hb, "low": lb, "close": cb}, index=idx)
    stb = AssetState(sym="TEST2", equity=1000.0, peak=1000.0)
    rb = _process_bar(stb, cfg, dfb, 3, notional=200.0)
    assert stb.pos.side == -1 and rb[0]["event"] == "ENTER_SHORT"
    assert abs(stb.pos.stop - 101.0) < 1e-9 and abs(stb.pos.tp - 98.0) < 1e-9
    # short SL: high pokes above stop=101
    hb4 = hb.copy(); hb4[4] = 101.5
    dfb2 = pd.DataFrame({"open": ob, "high": hb4, "low": lb, "close": cb}, index=idx)
    rb2 = _process_bar(stb, cfg, dfb2, 4, notional=200.0)
    assert stb.pos.side == 0 and rb2[0]["event"] == "EXIT_SL"
    print("orb_paper self-check OK")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        demo()
    elif len(sys.argv) > 1:
        main()
    else:
        demo()