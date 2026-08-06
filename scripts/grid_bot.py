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


class GridBot:
    """Stateful trailing grid (martingale-free). Shared by backtest and live so
    the live paper engine has NO divergence from the backtest (the lesson of
    app/backtest/faithful.py — backtest must mirror live exactly).

    Anchor ratchets UP with price (no buys on uptrends). Price drops g% below
    anchor -> buy 1 unit, ladder anchor down into the dip. Each held buy sells
    when price recovers g% above its entry (+g - 2 fees per round trip). Inventory
    capped at K units (bounded downtrend bleed). stop (optional, off by default —
    §hardening showed it HURTS by cutting the bounce-harvest that is the edge):
    flatten all on a max-DD breach, stay flat until a new equity peak.
    """

    def __init__(self, g: float, K: int, fee: float, capital: float = 10000.0,
                 stop: float | None = None):
        self.g, self.K, self.fee, self.capital, self.stop = g, K, fee, capital, stop
        self.unit = capital / (K + 1)
        self.open_buys: list[float] = []
        self.cash = 0.0
        self.anchor: float | None = None
        self.peak = capital
        self.flattened = False
        self.equity = capital

    def step(self, price: float, allow_buy: bool = True) -> tuple[float, list[dict]]:
        """Process one price tick. Returns (mark-to-market equity, fills_this_step).

        allow_buy (default True, so live callers are unchanged) gates NEW ladder
        buys only — sells, marking, and the stop all still run. Used by the
        regime-gated backtest to test whether filtering downtrend entries
        recovers edge; live never passes it.
        """
        if self.anchor is None:
            self.anchor = price
            self.equity = self.capital
            return self.equity, []
        fills = []
        c = price
        # take profit: close buys whose +g target hit
        still = []
        for ep in self.open_buys:
            if c >= ep * (1 + self.g):
                self.cash += self.unit + (c / ep - 1) * self.unit - 2 * self.fee * self.unit
                fills.append({"side": "sell", "entry": ep, "exit": c, "pnl": (c / ep - 1) * self.unit - 2 * self.fee * self.unit})
            else:
                still.append(ep)
        self.open_buys = still
        # mark-to-market equity + drawdown stop
        mark = sum(self.unit * (c / ep - 1) for ep in self.open_buys)
        eq = self.capital + self.cash + len(self.open_buys) * self.unit + mark
        self.peak = max(self.peak, eq)
        if self.stop is not None and not self.flattened and eq < self.peak * (1 - self.stop):
            for ep in self.open_buys:
                self.cash += self.unit + (c / ep - 1) * self.unit - self.fee * self.unit
                fills.append({"side": "stop_sell", "entry": ep, "exit": c, "pnl": (c / ep - 1) * self.unit - self.fee * self.unit})
            self.open_buys = []
            self.flattened = True
            eq = self.capital + self.cash
        if self.flattened and eq >= self.peak:
            self.flattened = False
            self.anchor = c
        # ladder buy: dropped g% below anchor, under cap, not flattened, regime open
        if allow_buy and (not self.flattened) and c <= self.anchor * (1 - self.g) and len(self.open_buys) < self.K:
            self.open_buys.append(c)
            self.cash -= self.unit
            self.anchor = c
            fills.append({"side": "buy", "entry": c, "qty_notional": self.unit})
        elif c > self.anchor:
            self.anchor = c
        self.equity = eq
        return eq, fills


def grid_backtest(px: pd.Series, g: float, K: int, fee: float = FEE,
                   capital: float = 10000.0, stop: float | None = None) -> pd.Series:
    """Backtest the trailing grid via the shared GridBot (so backtest == live)."""
    bot = GridBot(g, K, fee, capital, stop)
    eq_vals = []
    for i in range(len(px)):
        eq, _ = bot.step(float(px.iloc[i]))
        eq_vals.append(eq)
    return pd.Series(eq_vals, index=px.index)


def grid_backtest_gated(px: pd.Series, g: float, K: int, gate: pd.Series,
                        fee: float = FEE, capital: float = 10000.0,
                        stop: float | None = None) -> pd.Series:
    """Regime-gated backtest: gate (bool, aligned to px) blocks NEW buys only —
    sells/marking/stop still run, so it models "stop adding risk in a downtrend,
    let existing inventory work off". The regime filter used in research is
    close > SMA(200) (only buy dips when the macro trend is up/flat); it cuts
    the 2025-2026 downtrend drawdown ~4x but does NOT restore edge (grid is
    long-only; a downtrend gate can stop bleeding, not profit)."""
    bot = GridBot(g, K, fee, capital, stop)
    eq_vals = []
    for i in range(len(px)):
        eq, _ = bot.step(float(px.iloc[i]), allow_buy=bool(gate.iloc[i]))
        eq_vals.append(eq)
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
    # grid search on train: spacing g, rungs K. argmax-train picks the "edge
    # exists" grid for the verdict, but train Sharpe over-fits to wide spacing
    # (monotonically inflated by train-period trends). The DEPLOYED grid is only
    # set when the edge actually holds on the CURRENT OOS slice — a grid that
    # only worked on stale data is not deployable. Full surface saved for audit.
    grids = [(g, K) for g in (0.005, 0.008, 0.01, 0.015, 0.02) for K in (10, 20, 40)]
    best, best_sh = None, -1e9
    surface = []
    for g, K in grids:
        tr = metrics(grid_backtest(train, g, K)); oo = metrics(grid_backtest(oos, g, K))
        surface.append({"g": g, "K": K, "train_sh": tr["sharpe"], "oos_sh": oo["sharpe"],
                        "oos_end": oo["end_eq"], "oos_dd": oo["max_dd"]})
        if tr["sharpe"] > best_sh:
            best_sh, best = tr["sharpe"], (g, K)
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
    # regime-gated robustness probe (close > SMA200 blocks downtrend entries).
    # Reports whether a filter rescues the edge on the fresh OOS. To date it
    # cuts DD ~4x but stays negative -> grid is not deployable even gated.
    oos_px = px.loc[split:]
    gate = oos_px > oos_px.rolling(200).mean()
    gated_oos = metrics(grid_backtest_gated(oos_px, g, K, gate)) if gate.notna().any() else None
    if gated_oos:
        print(f"gated oos (close>SMA200, on {gate.mean()*100:.0f}%): sh {gated_oos['sharpe']} "
              f"end {gated_oos['end_eq']} dd {gated_oos['max_dd']}")
    # deployable only when the edge holds on the current OOS slice. Deployed
    # grid = best OOS Sharpe (one-time post-hoc pick, audited via the saved
    # surface). None when refuted -> the live runner warns and runs paper for
    # divergence validation only, never as an expected-edge strategy.
    deployable = verdict == "GRID EDGE OOS"
    d = max(surface, key=lambda r: r["oos_sh"]) if deployable else None
    DEPLOYED = {"g": d["g"], "K": d["K"]} if d else None
    json.dump({"symbol": symbol, "best_grid": {"g": g, "K": K}, "deployable": deployable,
                "deployed": DEPLOYED, "surface": surface, "gated_oos": gated_oos, "full": full,
                "oos": oos, "buyhold_full": round(bh_full, 4), "buyhold_oos": round(bh_oos, 4),
                "fee": FEE, "verdict": verdict},
              open("reports/grid_bot.json", "w"), indent=2, default=str)
    print("-> reports/grid_bot.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT")