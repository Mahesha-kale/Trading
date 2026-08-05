"""Faithful multi-symbol rank: backtest every strategy via run_faithful (mirrors
the live engine: entry on 0->1, exit on 1->0, RiskManager gating, maker fees,
liquidation). This is the backtest that predicts paper/live — the main Backtester
does not (see docs/strategies_report.md §7).

Runs on BTC + ETH + SOL perpetuals to find edge where BTC has none. Downloads
OHLCV to the DB on first run if the cache is thin.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import structlog as _sl

from app.backtest.engine import BacktestConfig
from app.backtest.faithful import run_faithful
from app.data.downloader import download_ohlcv, load_candles
from app.strategy.registry import get_strategy

_sl.configure(wrapper_class=_sl.make_filtering_bound_logger(logging.ERROR),
               cache_logger_on_first_use=False)

# name -> (tf, kind, deployable, grid). kind unused in faithful (exit on sig 0
# for all) but kept for parity. Only persistent-1 (deployable) strategies — the
# faithful contract requires them.
STRATEGIES = {
    "liquidity_sweep":        ("5m",  True,  {"atr_mult": [3.5], "sweep_pen": [0.001]}),
    "fair_value_gap":         ("5m",  True,  {"atr_mult": [3.0]}),
    "opening_range_breakout": ("15m", True,  {"range_bars": [3], "atr_mult": [4.0]}),
    "vwap_pullback":          ("5m",  True,  {"tol_atr": [0.7], "atr_mult": [3.5]}),
    "keltner_mr":             ("5m",  True,  {"mult": [2.2], "atr_mult": [3.0]}),
    "stochrsi_reversal":      ("5m",  True,  {"atr_mult": [3.0], "tp_mult": [2.0, 8.0]}),
    "cci_reversion":          ("5m",  True,  {"period": [20], "atr_mult": [3.0]}),
    "adx_trend":              ("15m", True,  {"adx_thresh": [28], "atr_mult": [4.0]}),
    "donchian_breakout":      ("15m", True,  {"lookback": [50], "atr_mult": [4.0]}),
    "ichimoku_breakout":      ("15m", True,  {"atr_mult": [4.0]}),
    "psar_trend":             ("15m", True,  {"atr_mult": [4.0]}),
    "obv_divergence":         ("15m", True,  {"swing": [40], "atr_mult": [4.0]}),
    "ema_pullback":           ("15m", True,  {"tol_atr": [0.4], "atr_mult": [4.0]}),
    "wyckoff":                ("15m", True,  {"sos_window": [80], "atr_mult": [5.0]}),
    "regime_gate":            ("15m", True,  {"bull": [None, "stochrsi_reversal"], "adx_thresh": [25]}),
}

SYMBOLS = ["B-BTC_USDT", "B-ETH_USDT", "B-SOL_USDT"]
TF_DAYS = {"5m": 150, "15m": 330}
LEVERAGE = 3
INT_KEYS = {"range_bars", "lookback", "period", "sos_window", "swing",
            "adx_thresh", "atr_period", "trend_ema", "trend_slope"}


def grid_combos(grid: dict[str, list]) -> list[dict]:
    keys = list(grid); out = [{}]
    for k in keys:
        out = [dict(b, **{k: v}) for b in out for v in grid[k]]
    return out


def cast(params: dict) -> dict:
    return {k: (int(v) if k in INT_KEYS and v is not None else v) for k, v in params.items()}


def score(m_full, m_test) -> float:
    if m_test["num_trades"] < 5:
        return -1.0
    oos_pf = min(m_test.get("profit_factor", 0), 5)
    oos_sh = max(m_test.get("sharpe", 0), -5)
    full_sh = max(m_full.get("sharpe", 0), -5)
    full_pf = min(m_full.get("profit_factor", 0), 5)
    max_dd = m_full.get("max_drawdown", 1)
    stability = (oos_sh / full_sh) if full_sh > 0 else (1.0 if oos_sh > 0 else 0)
    stability = max(min(stability, 2.0), -1.0)
    n = m_full.get("num_trades", 0)
    return float(20 * np.tanh(oos_pf / 2) + 15 * np.tanh(oos_sh / 2)
                 + 10 * np.tanh(full_sh / 2) + 15 * (1 - min(max_dd, 0.3) / 0.3)
                 + 15 * stability + 10 * min(n / 30.0, 1.0)
                 + (20 if m_full["net_profit"] > 0 and full_pf > 1 else 0))  # profit bonus


async def ensure_data(sym: str, tf: str) -> None:
    d = TF_DAYS[tf]
    end = datetime.now(timezone.utc)
    df = await load_candles(sym, tf, end - timedelta(days=d), end)
    if len(df) < d * 0.5 * ({"5m": 288, "15m": 96}[tf]):
        print(f"downloading {sym} {tf}...", flush=True)
        await download_ohlcv(sym, tf, end - timedelta(days=d), end)


async def run_one(name, tf, grid, df):
    split = int(len(df) * 0.7)
    train = df.iloc[:split].tail(8000)
    test = df.iloc[split:]
    cfg = BacktestConfig(maker_on_limit=True, leverage=LEVERAGE)
    best = None
    for params in grid_combos(grid):
        bp = cast(params)
        try:
            m = run_faithful(get_strategy(name, bp), train, cfg)["metrics"]
            sh = m.get("sharpe", 0) or 0
            if best is None or sh > best[1]:
                best = (bp, sh)
        except Exception:
            continue
    bp = best[0] if best else cast(grid_combos(grid)[0])
    f = run_faithful(get_strategy(name, bp), df, cfg)["metrics"]
    o = run_faithful(get_strategy(name, bp), test, cfg)["metrics"]
    return {"name": name, "tf": tf, "params": bp, "score": round(score(f, o), 2),
            "full_pf": round(f["profit_factor"], 2), "full_net": round(f["net_profit"], 1),
            "full_sh": round(f["sharpe"], 2), "full_dd": round(f["max_drawdown"], 3),
            "full_wr": round(f["win_rate"], 3), "trades": f["num_trades"],
            "oos_pf": round(o["profit_factor"], 2), "oos_sh": round(o["sharpe"], 2),
            "oos_net": round(o["net_profit"], 1), "oos_tr": o["num_trades"],
            "profitable": f["net_profit"] > 0 and f["profit_factor"] > 1}


async def main():
    cache = {}
    for sym in SYMBOLS:
        cache[sym] = {}
        for tf in ("5m", "15m"):
            await ensure_data(sym, tf)
            cache[sym][tf] = await load_candles(sym, tf,
                                                  datetime.now(timezone.utc) - timedelta(days=TF_DAYS[tf]),
                                                  datetime.now(timezone.utc))
            print(f"{sym} {tf}: {len(cache[sym][tf])} bars", flush=True)
    all_results = {}
    for sym in SYMBOLS:
        print(f"\n=== {sym} ===", flush=True)
        rows = []
        for i, (name, (tf, _dep, grid)) in enumerate(STRATEGIES.items(), 1):
            df = cache[sym][tf]
            if len(df) < 2000:
                continue
            try:
                r = await run_one(name, tf, grid, df)
            except Exception as e:  # noqa: BLE001
                r = {"name": name, "error": str(e)[:80]}
            rows.append(r)
            if "score" in r:
                flag = " *** PROFITABLE" if r["profitable"] else ""
                print(f"[{i:2}] {name:22} score={r['score']:6} PF={r['full_pf']:.2f} "
                      f"net={r['full_net']:7.1f} sh={r['full_sh']:.2f} dd={r['full_dd']:.3f} "
                      f"wr={r['full_wr']:.2f} tr={r['trades']} | oos PF={r['oos_pf']:.2f} "
                      f"sh={r['oos_sh']:.2f}{flag}", flush=True)
            else:
                print(f"[{i:2}] {name:22} ERR {r.get('error')}", flush=True)
        rows.sort(key=lambda x: x.get("score", -999), reverse=True)
        all_results[sym] = rows
    with open("reports/rank_faithful.json", "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print("\n=== CROSS-SYMBOL PROFITABLE ===")
    for sym, rows in all_results.items():
        prof = [r for r in rows if r.get("profitable")]
        print(f"{sym}: {len(prof)} profitable")
        for r in prof:
            print(f"  {r['name']:22} tf={r['tf']} PF={r['full_pf']:.2f} net={r['full_net']:.1f} "
                  f"sh={r['full_sh']:.2f} dd={r['full_dd']:.3f} tr={r['trades']} params={r['params']}")
    print("\n-> reports/rank_faithful.json")


if __name__ == "__main__":
    asyncio.run(main())