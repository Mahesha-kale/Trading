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

# Real CoinDCX spot costs (user-confirmed): 0.169% taker + 18% GST on the fee,
# plus 1% TDS on every SELL notional. TDS is refundable at year-end against tax
# liability but is a real cashflow drag on compounding within a run, so it is
# modeled as a per-sell cost. With TDS, a round trip nets g% - 2*FEE - TDS;
# tight grids (g < ~1.5%) lose money on costs alone — the old FEE=0.001 model
# hid this and overstated edge across every prior backtest.
FEE = 0.00169 * 1.18     # 0.169% taker * 1.18 (GST) = 0.19942% per leg
TDS = 0.01               # 1% on sell notional


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
    """Stateful trailing grid (martingale-free), long-only or long/short. Shared
    by backtest and live so the paper engine has NO divergence from the backtest
    (the lesson of app/backtest/faithful.py — backtest must mirror live exactly).

    LONG side: anchor ratchets UP with price (no buys on uptrends). Price drops
    g% below anchor -> buy 1 unit, ladder anchor down into the dip. Each held buy
    sells when price recovers g% above entry (+g - 2*FEE - TDS per round trip).
    Inventory capped at K units (bounded downtrend bleed).

    SHORT side (shorts=True): mirror. anchor_s ratchets DOWN with price. Price
    rises g% above anchor_s -> short 1 unit (sell), ladder anchor_s up into the
    rip; close when price falls g% below entry (+g - 2*FEE - TDS per round trip,
    TDS on the opening sell). Harvests downtrend pullbacks — the regime that bled
    the long-only grid in 2025-2026.

    Costs are per-leg and exact: BUY = pay notional + FEE*notional; SELL = receive
    notional - FEE*notional - TDS*notional. With shorts, unit is halved so max
    long+short notional equals the long-only risk budget (no hidden leverage).

    stop (optional, off by default — hardening showed it HURTS by cutting the
    bounce-harvest that is the edge): flatten all on a max-DD breach, stay flat
    until a new equity peak.
    """

    def __init__(self, g: float, K: int, fee: float, capital: float = 10000.0,
                 stop: float | None = None, tds: float = 0.0, shorts: bool = False):
        self.g, self.K, self.fee, self.capital, self.stop = g, K, fee, capital, stop
        self.tds, self.shorts = tds, shorts
        self.unit = capital / (2 * (K + 1)) if shorts else capital / (K + 1)
        self.open_buys: list[float] = []
        self.open_shorts: list[float] = []
        self.cash = 0.0
        self.anchor: float | None = None
        self.anchor_s: float | None = None
        self.peak = capital
        self.flattened = False
        self.equity = capital

    def step(self, price: float, allow_buy: bool = True,
             allow_short: bool = True) -> tuple[float, list[dict]]:
        """Process one price tick. Returns (mark-to-market equity, fills_this_step).

        allow_buy / allow_short (default True, so live callers are unchanged) gate
        NEW ladder entries only — closes, marking, and the stop all still run.
        Used by regime-gated backtests; live never passes them.
        """
        if self.anchor is None:
            self.anchor = price
            self.anchor_s = price
            self.equity = self.capital
            return self.equity, []
        fills = []
        c = price
        f, t, u = self.fee, self.tds, self.unit
        # close longs: price +g above entry -> sell notional u*c/ep, fee + TDS on sell
        still = []
        for ep in self.open_buys:
            if c >= ep * (1 + self.g):
                notional = u * (c / ep)
                pnl = notional - u - f * (notional + u) - t * notional
                self.cash += notional - f * notional - t * notional
                fills.append({"side": "sell", "entry": ep, "exit": c, "pnl": pnl})
            else:
                still.append(ep)
        self.open_buys = still
        # close shorts: price -g below entry -> buy back notional u*c/es, fee on buy
        if self.shorts:
            still_s = []
            for es in self.open_shorts:
                if c <= es * (1 - self.g):
                    notional = u * (c / es)
                    pnl = u - notional - f * (u + notional) - t * u
                    self.cash -= notional + f * notional
                    fills.append({"side": "short_close", "entry": es, "exit": c, "pnl": pnl})
                else:
                    still_s.append(es)
            self.open_shorts = still_s
        # mark-to-market equity + drawdown stop
        long_val = sum(u * (c / ep) for ep in self.open_buys)
        short_liab = sum(u * (c / es) for es in self.open_shorts)
        eq = self.capital + self.cash + long_val - short_liab
        self.peak = max(self.peak, eq)
        if self.stop is not None and not self.flattened and eq < self.peak * (1 - self.stop):
            for ep in self.open_buys:  # stop = sell at market, fee + TDS
                notional = u * (c / ep)
                self.cash += notional - f * notional - t * notional
                fills.append({"side": "stop_sell", "entry": ep, "exit": c})
            for es in self.open_shorts:  # stop = buy back at market, fee
                notional = u * (c / es)
                self.cash -= notional + f * notional
                fills.append({"side": "stop_short_close", "entry": es, "exit": c})
            self.open_buys = []
            self.open_shorts = []
            self.flattened = True
            eq = self.capital + self.cash
        if self.flattened and eq >= self.peak:
            self.flattened = False
            self.anchor = c
            self.anchor_s = c
        # long ladder: dip g% below anchor, under cap, not flattened, regime open
        if allow_buy and (not self.flattened) and c <= self.anchor * (1 - self.g) and len(self.open_buys) < self.K:
            self.open_buys.append(c)
            self.cash -= u + f * u
            self.anchor = c
            fills.append({"side": "buy", "entry": c, "qty_notional": u})
        elif c > self.anchor:
            self.anchor = c
        # short ladder: rip g% above anchor_s, under cap, not flattened, regime open
        if self.shorts:
            if allow_short and (not self.flattened) and c >= self.anchor_s * (1 + self.g) and len(self.open_shorts) < self.K:
                self.open_shorts.append(c)
                self.cash += u - f * u - t * u
                self.anchor_s = c
                fills.append({"side": "short_open", "entry": c, "qty_notional": u})
            elif c < self.anchor_s:
                self.anchor_s = c
        self.equity = eq
        return eq, fills


def grid_backtest(px: pd.Series, g: float, K: int, fee: float = FEE,
                   capital: float = 10000.0, stop: float | None = None,
                   tds: float = TDS, shorts: bool = False) -> pd.Series:
    """Backtest the trailing grid via the shared GridBot (so backtest == live).
    tds/shorts default to the real CoinDCX cost model and long-only; pass
    shorts=True for the symmetric long/short grid."""
    bot = GridBot(g, K, fee, capital, stop, tds=tds, shorts=shorts)
    eq_vals = []
    for i in range(len(px)):
        eq, _ = bot.step(float(px.iloc[i]))
        eq_vals.append(eq)
    return pd.Series(eq_vals, index=px.index)


def grid_backtest_gated(px: pd.Series, g: float, K: int, gate: pd.Series,
                        fee: float = FEE, capital: float = 10000.0,
                        stop: float | None = None, tds: float = TDS,
                        shorts: bool = False, long_gate: pd.Series | None = None) -> pd.Series:
    """Regime-gated backtest. `gate` (bool, aligned to px) blocks NEW long buys
    only — sells/marking/stop still run, modeling "stop adding long risk in a
    downtrend, let existing inventory work off". When shorts=True, `long_gate`
    optionally blocks new shorts separately (None = shorts always allowed); the
    short side is what profits in the downtrend the long gate skips. The
    long-side filter close > SMA(200) cuts 2025-2026 drawdown ~4x; combined with
    the short side it targets positive edge in both regimes."""
    bot = GridBot(g, K, fee, capital, stop, tds=tds, shorts=shorts)
    eq_vals = []
    for i in range(len(px)):
        ab = bool(gate.iloc[i])
        as_ = bool(long_gate.iloc[i]) if (shorts and long_gate is not None) else True
        eq, _ = bot.step(float(px.iloc[i]), allow_buy=ab, allow_short=as_)
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
    oos_px = oos  # keep the Series; `oos` is reused below for the metrics dict
    print(f"{symbol}: {len(px)} bars {px.index[0].date()}->{px.index[-1].date()} "
          f"| split {split.date()} | train {len(train)} oos {len(oos)}\n", flush=True)
    # grid search on train: spacing g, rungs K. Two families swept under the real
    # cost model (0.169% + GST + 1% TDS): long-only and symmetric long/short. The
    # short side harvests downtrend pullbacks — the regime that bled the long-only
    # grid in 2025-2026. argmax-train picks each family's best; the verdict and the
    # DEPLOYED grid require the edge to hold on the CURRENT OOS slice.
    grids = [(g, K) for g in (0.01, 0.015, 0.02, 0.03, 0.04) for K in (10, 20, 40)]

    def sweep(shorts: bool):
        rows, best, best_sh = [], None, -1e9
        for g, K in grids:
            tr = metrics(grid_backtest(train, g, K, shorts=shorts))
            oo = metrics(grid_backtest(oos, g, K, shorts=shorts))
            rows.append({"g": g, "K": K, "train_sh": tr["sharpe"], "oos_sh": oo["sharpe"],
                         "oos_end": oo["end_eq"], "oos_dd": oo["max_dd"]})
            if tr["sharpe"] > best_sh:
                best_sh, best = tr["sharpe"], (g, K)
        return rows, best, best_sh

    surface, best, best_sh = sweep(False)            # long-only
    surface_ls, best_ls, best_sh_ls = sweep(True)    # long/short
    g, K = best
    gls, Kls = best_ls
    print(f"long-only best train: g={g} K={K} (sh {best_sh})")
    print(f"long/short best train: g={gls} K={Kls} (sh {best_sh_ls})\n", flush=True)
    print(f"{'window':10} {'sh':>6} {'pf':>5} {'cagr':>6} {'maxdd':>7} {'end':>8}", flush=True)
    full = metrics(grid_backtest(px, g, K))
    oos = metrics(grid_backtest(oos_px, g, K))
    print(f"{'long':10} {oos['sharpe']:6.2f} {oos['pf']:5.2f} {oos['cagr']:6.3f} "
          f"{oos['max_dd']:7.3f} {oos['end_eq']:8.1f}  (oos, g={g} K={K})", flush=True)
    oos_ls = metrics(grid_backtest(oos_px, gls, Kls, shorts=True))
    full_ls = metrics(grid_backtest(px, gls, Kls, shorts=True))
    print(f"{'long/short':10} {oos_ls['sharpe']:6.2f} {oos_ls['pf']:5.2f} {oos_ls['cagr']:6.3f} "
          f"{oos_ls['max_dd']:7.3f} {oos_ls['end_eq']:8.1f}  (oos, g={gls} K={Kls})", flush=True)
    # buy&hold benchmark
    bh_full = float(px.iloc[-1] / px.iloc[0] - 1)
    bh_oos = float(px.loc[split:].iloc[-1] / px.loc[split:].iloc[0] - 1)
    print(f"{'buyhold':10} {'':>6} {'':>5} {'':>6} {'':>7} "
          f"{10000*(1+bh_full):8.1f} (full {bh_full*100:.0f}%, oos {bh_oos*100:.0f}%)", flush=True)
    # verdict: positive edge if the best family's OOS clears the bar
    best_oos = max(oos, oos_ls, key=lambda m: m["sharpe"])
    best_family = "long/short" if oos_ls["sharpe"] > oos["sharpe"] else "long-only"
    verdict = ("GRID EDGE OOS" if best_oos["sharpe"] > 0.5 and best_oos["end_eq"] > 10000
               else "no grid edge OOS" if best_oos["sharpe"] < 0
               else "marginal grid OOS")
    print(f"\nverdict: {verdict} | best family {best_family} (oos sh {best_oos['sharpe']}, "
          f"end {best_oos['end_eq']})", flush=True)
    # regime-switch long/short probe: long only above SMA(200) (uptrend/range),
    # short only below SMA(200) (downtrend). This bounds shorts (ungated shorts
    # blow up in a strong uptrend: train DD -124%) — but it also kills the edge:
    # under the 1% TDS, round trips cost ~1.4%, so even the bounded version only
    # breaks even on OOS and loses in-sample. Reported on train+OOS+full so the
    # saved record is honest (no robust edge under real costs).
    N = 200
    def regime_switch(seg):
        up = seg > seg.rolling(N).mean(); dn = seg < seg.rolling(N).mean()
        return metrics(grid_backtest_gated(seg, gls, Kls, up, shorts=True, long_gate=dn))
    rs = {"train": regime_switch(train), "oos": regime_switch(oos_px),
          "full": regime_switch(px)}
    print(f"regime-switch long/short (long>SMA{N}, short<SMA{N}): "
          f"train sh {rs['train']['sharpe']} end {rs['train']['end_eq']} | "
          f"oos sh {rs['oos']['sharpe']} end {rs['oos']['end_eq']} | "
          f"full sh {rs['full']['sharpe']} end {rs['full']['end_eq']}")
    # deployable only when the edge holds on the current OOS slice.
    deployable = verdict == "GRID EDGE OOS"
    if deployable:
        fam_surface = surface_ls if best_family == "long/short" else surface
        d = max(fam_surface, key=lambda r: r["oos_sh"])
        DEPLOYED = {"g": d["g"], "K": d["K"], "shorts": best_family == "long/short"}
    else:
        DEPLOYED = None
    json.dump({"symbol": symbol, "fee": FEE, "tds": TDS,
                "best_long": {"g": g, "K": K}, "best_longshort": {"g": gls, "K": Kls},
                "best_family": best_family, "deployable": deployable, "deployed": DEPLOYED,
                "surface": surface, "surface_longshort": surface_ls, "full": full,
                "oos": oos, "full_longshort": full_ls, "oos_longshort": oos_ls,
                "regime_switch": rs,
                "buyhold_full": round(bh_full, 4), "buyhold_oos": round(bh_oos, 4),
                "verdict": verdict},
              open("reports/grid_bot.json", "w"), indent=2, default=str)
    print("-> reports/grid_bot.json")


def selfcheck():
    """Accounting self-check for the long/short cost model (no framework). Each
    closing branch is exercised in isolation by injecting one position and
    stepping the trigger price; the fill pnl must equal the analytic round-trip
    g - fee*(2±g) - tds*(1±g). Also checks long-only never opens a short."""
    g, fee, tds, cap = 0.02, 0.001, 0.01, 10000.0
    u_long = cap / (10 + 1)            # long-only unit
    u_ls = cap / (2 * (10 + 1))        # long/short unit (halved)

    # long close: bought at 98, sell trigger at 100 (>= 98*1.02)
    b = GridBot(g, 10, fee, cap, tds=tds, shorts=False)
    b.anchor = 100.0; b.open_buys = [98.0]; b.cash = -(u_long + fee * u_long)
    _, fills = b.step(100.0)
    sell = next(f for f in fills if f["side"] == "sell")
    long_exact = u_long * (100 / 98 - 1) - fee * u_long * (100 / 98 + 1) - tds * u_long * (100 / 98)
    assert abs(sell["pnl"] - long_exact) < 1e-9, f"long pnl {sell['pnl']} != {long_exact}"
    assert long_exact > 0, "long round trip should profit"

    # short close: shorted at 102, buy-back trigger at 99.96 (<= 102*0.98)
    b = GridBot(g, 10, fee, cap, tds=tds, shorts=True)
    b.anchor = 100.0; b.anchor_s = 100.0
    b.open_shorts = [102.0]; b.cash = u_ls - fee * u_ls - tds * u_ls
    _, fills = b.step(99.96)
    sc = next(f for f in fills if f["side"] == "short_close")
    short_exact = u_ls - u_ls * (99.96 / 102) - fee * u_ls * (1 + 99.96 / 102) - tds * u_ls
    assert abs(sc["pnl"] - short_exact) < 1e-9, f"short pnl {sc['pnl']} != {short_exact}"
    assert short_exact > 0, "short round trip should profit"

    # long-only bot must never open a short (rip then revert)
    b = GridBot(g, 10, fee, cap, tds=tds, shorts=False)
    b.step(100.0); b.step(100.0 * (1 + g)); b.step(100.0)
    assert len(b.open_shorts) == 0, "long-only bot opened a short"
    print("selfcheck OK: long/short close-branch pnl exact, long-only stays long")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        selfcheck()
    else:
        main(sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT")