"""Divergence check for the live grid runner (#2).

Live feeds CoinDCX ticks (or 60s poll closes) through GridBot.step; the backtest
feeds 15m closes through the same step. This script asks: how much does equity
diverge between the two resolutions on the SAME realized price path?

Reads reports/grid_live_series.jsonl (ts, px, eq — recorded during live run).

Two checks:
  1. sanity: replay the recorded ticks through a fresh GridBot -> final equity
     must equal the live run's recorded final equity. Catches any loop/state bug
     (live step vs recorded step). Should be exactly 0.
  2. divergence: resample the recorded price path to 15m closes (backtest
     resolution), run GridBot on those, compare final equity to the live
     tick-stepped final equity. Gap = intra-bar effect the close-only backtest
     cannot see (wicks that trigger grid fills then revert). Sign + size tells
     you whether the backtest over- or under-states live edge.

Usage: python scripts/grid_live_replay.py [g] [K]   (defaults read from summary)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.resolve()))
from grid_bot import FEE, GridBot  # noqa: E402

SERIES = Path("reports/grid_live_series.jsonl")
SUMMARY = Path("reports/grid_live_summary.json")


def replay(prices: pd.Series, g: float, K: int, capital: float = 10000.0) -> float:
    bot = GridBot(g, K, FEE, capital)
    for p in prices:
        bot.step(float(p))
    return bot.equity


def main():
    if not SERIES.exists():
        raise SystemExit("no reports/grid_live_series.jsonl; run scripts/grid_live.py first")
    rows = [json.loads(line) for line in SERIES.read_text().splitlines() if line.strip()]
    if len(rows) < 2:
        raise SystemExit(f"only {len(rows)} samples; run longer before comparing")
    px = pd.Series([r["px"] for r in rows], index=pd.to_datetime([r["ts"] for r in rows], utc=True))
    live_eq = float(rows[-1]["eq"])

    g, K = 0.02, 20
    if SUMMARY.exists():
        s = json.loads(SUMMARY.read_text())
        g, K = s.get("g", g), s.get("K", K)

    # 1. sanity: fresh replay of recorded ticks must reproduce live equity
    sanity_eq = replay(px, g, K)
    drift = sanity_eq - live_eq

    # 2. divergence: resample to 15m closes (backtest resolution)
    bar_px = px.resample("15min").last().dropna()
    bar_eq = replay(bar_px, g, K) if len(bar_px) else live_eq
    gap = live_eq - bar_eq  # + = live better than backtest saw; - = backtest over-states

    n_bars = len(bar_px)
    print(f"live samples: {len(px)} | 15m bars: {n_bars}")
    print(f"live final equity:     {live_eq:.2f}")
    print(f"sanity replay equity: {sanity_eq:.2f}  (drift {drift:+.4f} — must be ~0)")
    print(f"15m-backtest equity:  {bar_eq:.2f}  (gap {gap:+.2f} — live vs close-only)")
    verdict = ("no loop divergence" if abs(drift) < 1e-6
               else f"LOOP BUG: drift {drift:+.4f}")
    bar_verdict = ("backtest UNDER-states live" if gap > 0
                   else "backtest OVER-states live" if gap < 0
                   else "no intra-bar gap")
    print(f"sanity: {verdict}")
    print(f"divergence: {bar_verdict} (gap {gap:+.2f} on {n_bars} bars)")
    print("note: gap meaningful only with enough bars; <~50 bars is noise.")
    json.dump({"live_samples": len(px), "bars": n_bars, "live_eq": live_eq,
                "sanity_eq": sanity_eq, "drift": drift, "bar_eq": bar_eq,
                "gap": gap, "sanity": verdict, "divergence": bar_verdict},
              open("reports/grid_live_replay.json", "w"), indent=2)
    print("-> reports/grid_live_replay.json")


if __name__ == "__main__":
    main()