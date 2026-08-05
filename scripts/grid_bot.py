"""Spot grid bot: structurally different from the perp price strategies. No
leverage, no funding, no liquidation -> positive carry in ranges, bounded risk
(grid floor). Harvests mean-reversion: each grid rung buys a dip one grid below
and sells one grid up, netting ~grid_spacing% per round trip minus fees. Bleeds
only when price trends through the grid floor (capped inventory = K units).

Backtested on cached Binance 15m (spot ~ perp basis is negligible vs grid step).
Bounded grid (levels -K..K), walk-forward train 70% / OOS 30%, grid-search
spacing g and rung count K on train.

Usage: python scripts/grid_bot.py [BTCUSDT|ETHUSDT]
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

FEE = 0.001  # spot taker ~0.1% (Binance/Kraken style); CoinDCX spot ~0.2% -> test sensitivity


def load(symbol: str) -> pd.Series:
    for ext in ("parquet", "csv"):
        p = f"reports/binance_{symbol}_15m.{ext}"
        try:
            df = (pd.read_parquet(p) if ext == "parquet"
                  else pd.read_csv(p, index_col=0, parse_dates=True))
            return df["close"].astype(float).sort_index()
        except Exception:
            continue
    raise SystemExit(f"no cache for {symbol}; run scripts/pull_binance.py first")


def grid_backtest(px: pd.Series, g: float, K: int, fee: float = FEE,
                   capital: float = 10000.0) -> pd.Series:
    """Trailing grid (martingale-free). Anchor ratchets UP with price (no buys on
    uptrends). When price drops g% below anchor -> buy 1 unit, set anchor to that
    buy (ladder down into dips). Each held buy sells when price recovers g% above
    its entry (+g per unit round trip minus 2 fees). Inventory capped at K units
    (sustained downtrend bleed is bounded by K, not infinite).

    This is the realistic grid bot; the fixed-center bounded grid dies when price
    trends away from the initial center. Trailing keeps the grid on the price."""
    unit = capital / (K + 1)  # notional per rung; K+1 so K buys + cash reserve
    open_buys: list[float] = []  # entry prices of held buys
    cash = 0.0
    anchor = float(px.iloc[0])
    eq_vals = [capital]
    for i in range(1, len(px)):
        c = float(px.iloc[i])
        # take profit: close any buy whose +g target hit
        still = []
        for ep in open_buys:
            if c >= ep * (1 + g):
                cash += unit + (c / ep - 1) * unit - 2 * fee * unit  # +g - 2fee
            else:
                still.append(ep)
        open_buys = still
        # ladder buy: price dropped g% below anchor, inventory under cap
        if c <= anchor * (1 - g) and len(open_buys) < K:
            open_buys.append(c)
            cash -= unit
            anchor = c
        # ratchet anchor up with price (so a small dip off a pump doesn't re-buy)
        elif c > anchor:
            anchor = c
        # mark open inventory at close
        mark = sum(unit * (c / ep - 1) for ep in open_buys)
        eq_vals.append(capital + cash + len(open_buys) * unit + mark)
    return pd.Series(eq_vals, index=px.index)


def metrics(eq: pd.Series) -> dict:
    rets = eq.pct_change().dropna()
    bpy = 365 * 24 * 4  # 15m bars
    sh = rets.mean() / rets.std() * np.sqrt(bpy) if rets.std() > 0 else 0
    peak = eq.cummax(); dd = ((eq - peak) / peak).min()
    yrs = len(eq) / bpy
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 1e-9)) - 1
    gp = rets[rets > 0].sum(); gl = -rets[rets < 0].sum()
    pf = gp / gl if gl > 0 else 0
    return {"sharpe": round(sh, 2), "max_dd": round(float(dd), 3),
            "cagr": round(cagr, 3), "pf": round(pf, 2), "n": len(eq),
            "end_eq": round(float(eq.iloc[-1]), 1)}


def main(symbol="BTCUSDT"):
    px = load(symbol)
    split = px.index[int(len(px) * 0.7)]
    train = px.loc[:split]; oos = px.loc[split:]
    print(f"{symbol}: {len(px)} bars {px.index[0].date()}->{px.index[-1].date()} "
          f"| split {split.date()} | train {len(train)} oos {len(oos)}\n", flush=True)
    # grid search on train: spacing g, rungs K
    grids = [(g, K) for g in (0.005, 0.01, 0.02) for K in (10, 20, 40)]
    best, best_sh = None, -1e9
    for g, K in grids:
        m = metrics(grid_backtest(train, g, K))
        if m["sharpe"] > best_sh:
            best_sh, best = m["sharpe"], (g, K)
    g, K = best
    print(f"best train grid: g={g} K={K} (train sh {best_sh})\n", flush=True)
    print(f"{'window':10} {'sh':>6} {'pf':>5} {'cagr':>6} {'maxdd':>7} {'end':>8}", flush=True)
    full = metrics(grid_backtest(px, g, K))
    oos = metrics(grid_backtest(oos, g, K))
    print(f"{'full':10} {full['sharpe']:6.2f} {full['pf']:5.2f} {full['cagr']:6.3f} "
          f"{full['max_dd']:7.3f} {full['end_eq']:8.1f}", flush=True)
    print(f"{'oos':10} {oos['sharpe']:6.2f} {oos['pf']:5.2f} {oos['cagr']:6.3f} "
          f"{oos['max_dd']:7.3f} {oos['end_eq']:8.1f}", flush=True)
    # buy&hold benchmark
    bh_full = float(px.iloc[-1] / px.iloc[0] - 1)
    bh_oos = float(px.loc[split:].iloc[-1] / px.loc[split:].iloc[0] - 1)
    print(f"{'buyhold':10} {'':>6} {'':>5} {'':>6} {'':>7} "
          f"{10000*(1+bh_full):8.1f} (full {bh_full*100:.0f}%, oos {bh_oos*100:.0f}%)", flush=True)
    verdict = ("GRID EDGE OOS" if oos["sharpe"] > 0.5 and oos["end_eq"] > 10000
               else "no grid edge OOS" if oos["sharpe"] < 0
               else "marginal grid OOS")
    print(f"\nverdict: {verdict} (oos sh {oos['sharpe']}, end {oos['end_eq']})")
    json.dump({"symbol": symbol, "best_grid": {"g": g, "K": K}, "full": full,
                "oos": oos, "buyhold_full": round(bh_full, 4), "buyhold_oos": round(bh_oos, 4),
                "fee": FEE, "verdict": verdict},
              open("reports/grid_bot.json", "w"), indent=2, default=str)
    print("-> reports/grid_bot.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT")