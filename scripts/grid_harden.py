"""Grid hardening before paper deployment: (1) rolling walk-forward re-tune (does
periodic re-tuning beat the static single-split params?), (2) inventory-stop
sweep (flatten open buys on a max-DD breach — does it cut the -30..50% dd without
killing Sharpe?), (3) multi-symbol portfolio (BTC + ETH grids, inverse-vol).

Reuses grid_backtest + metrics from grid_bot. Cached Binance 15m.

Usage: python scripts/grid_harden.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grid_bot import FEE, grid_backtest, load, metrics  # noqa: E402

GRIDS = [(g, K) for g in (0.01, 0.02, 0.03) for K in (10, 20, 40)]


def best_params(px: pd.Series, stop=None):
    best, best_sh = (0.02, 20), -1e9
    for g, K in GRIDS:
        m = metrics(grid_backtest(px, g, K, stop=stop))
        if m["sharpe"] > best_sh:
            best_sh, best = m["sharpe"], (g, K)
    return best, round(best_sh, 2)


def walk_forward(px: pd.Series, n=4, stop=None):
    """Rolling re-tune: tune on expanding train, score next OOS window, slide.
    Returns list of (params, oos_metrics)."""
    step = len(px) // (n + 1)
    folds = []
    for i in range(n):
        train = px.iloc[: (i + 1) * step]
        test = px.iloc[(i + 1) * step: (i + 2) * step]
        if len(train) < 4000 or len(test) < 2000:
            continue
        (g, K), _ = best_params(train, stop)
        om = metrics(grid_backtest(test, g, K, stop=stop))
        folds.append({"params": (g, K), "oos_sh": om["sharpe"],
                      "oos_net": om["end_eq"] - 10000, "oos_dd": om["max_dd"]})
    return folds


def main():
    out = {}
    for sym in ("BTCUSDT", "ETHUSDT"):
        px = load(sym)
        print(f"\n=== {sym} ({len(px)} bars) ===", flush=True)
        # (1) static vs rolling re-tune
        (g0, K0), tr_sh = best_params(px.iloc[: int(len(px) * 0.7)])
        oos = px.iloc[int(len(px) * 0.7):]
        static = metrics(grid_backtest(oos, g0, K0))
        wf = walk_forward(px, n=4)
        wf_shs = [f["oos_sh"] for f in wf]
        print(f"static:   g={g0} K={K0} (train sh {tr_sh}) -> OOS sh={static['sharpe']} dd={static['max_dd']}", flush=True)
        print(f"rolling:  {len(wf)} folds, mean OOS sh={np.mean(wf_shs):.2f} "
              f"sum OOS net={sum(f['oos_net'] for f in wf):.0f}", flush=True)
        # (2) inventory-stop sweep on static OOS
        print("stop sweep (static OOS):", flush=True)
        print(f"  {'stop':>6} {'sh':>6} {'pf':>5} {'cagr':>6} {'maxdd':>7} {'end':>8}", flush=True)
        stops = {"none": None, "0.15": 0.15, "0.20": 0.20, "0.25": 0.25}
        stop_res = {}
        for label, st in stops.items():
            m = metrics(grid_backtest(oos, g0, K0, stop=st))
            stop_res[label] = m
            print(f"  {label:>6} {m['sharpe']:6.2f} {m['pf']:5.2f} {m['cagr']:6.3f} "
                  f"{m['max_dd']:7.3f} {m['end_eq']:8.1f}", flush=True)
        out[sym] = {"static_oos": static, "rolling_wf": wf,
                    "rolling_mean_oos_sh": round(float(np.mean(wf_shs)), 2),
                    "stop_sweep": stop_res}
    # (3) multi-symbol portfolio: BTC + ETH grids (static best), inverse-vol
    btc, eth = load("BTCUSDT"), load("ETHUSDT")
    (gb, Kb), _ = best_params(btc.iloc[: int(len(btc) * 0.7)])
    (ge, Ke), _ = best_params(eth.iloc[: int(len(eth) * 0.7)])
    common = btc.index.intersection(eth.index)
    oos_start = common[int(len(common) * 0.7)]
    eb = grid_backtest(btc.loc[:oos_start], gb, Kb)  # train equity for vol
    ee = grid_backtest(eth.loc[:oos_start], ge, Ke)
    ob = grid_backtest(btc.loc[oos_start:], gb, Kb)  # OOS equity
    oe = grid_backtest(eth.loc[oos_start:], ge, Ke)
    # inverse-vol weights from train daily-return std
    wb = 1.0 / eb.pct_change().dropna().std()
    we = 1.0 / ee.pct_change().dropna().std()
    W = pd.Series({"BTC": wb, "ETH": we}); W = W / W.sum()
    # align OOS daily
    oos_df = pd.DataFrame({"BTC": ob, "ETH": oe}).pct_change().fillna(0)
    port_ret = (oos_df[W.index] * W).sum(axis=1)
    port_eq = (1 + port_ret).cumprod() * 10000
    pm = metrics(port_eq)
    corr = oos_df["BTC"].corr(oos_df["ETH"])
    print(f"\n=== PORTFOLIO BTC+ETH (inverse-vol, OOS) ===", flush=True)
    print(f"weights {dict(W.round(2))} | BTC-ETH daily corr {corr:.2f}", flush=True)
    print(f"portfolio OOS: sh={pm['sharpe']} pf={pm['pf']} cagr={pm['cagr']} "
          f"dd={pm['max_dd']} end={pm['end_eq']}", flush=True)
    print(f"  BTC alone OOS: {metrics(ob)['sharpe']} | ETH alone OOS: {metrics(oe)['sharpe']}", flush=True)
    out["portfolio"] = {"weights": dict(W.round(3)), "btc_eth_corr": round(corr, 2),
                         "oos": pm,
                         "btc_oos_sh": metrics(ob)["sharpe"], "eth_oos_sh": metrics(oe)["sharpe"]}
    json.dump(out, open("reports/grid_harden.json", "w"), indent=2, default=str)
    print("\n-> reports/grid_harden.json")


if __name__ == "__main__":
    main()