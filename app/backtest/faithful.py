"""Signal-faithful backtest: mirrors the live/paper engine exactly so backtest
results predict paper/live performance.

The main `Backtester` opens on the first sig==1 then exits via its OWN trailing
stop / fixed stop / TP — it ignores sig==0. So its metrics do NOT reflect how the
live engine trades, which exits on sig==0 (the strategy's internal TP/SL in
`generate_signals`). That divergence made every prior backtest tuning
non-transferable to paper (see docs/strategies_report.md §7).

This module reproduces the live engine's loop: entry on 0->1, exit on 1->0,
`RiskManager` gating (daily-loss / drawdown / max-positions, same object live
uses), 2-ATR sizing stop, maker/taker fees on entry + maker on exit, isolated-
margin liquidation, 8h funding. Use for persistent-1 strategies only.

Returns the same {metrics, equity, trades} shape as Backtester so the rank
harness can consume it.
"""
from __future__ import annotations

import pandas as pd

from app.backtest.engine import FUNDING_INTERVAL, BacktestConfig
from app.backtest.metrics import compute_metrics
from app.risk.manager import RiskManager, liquidation_price
from app.strategy.base import BaseStrategy
from app.strategy.indicators import atr


def run_faithful(strategy: BaseStrategy, df: pd.DataFrame,
                 cfg: BacktestConfig | None = None) -> dict:
    cfg = cfg or BacktestConfig()
    if df.empty:
        return {"metrics": {}, "equity": pd.Series(dtype=float), "trades": []}
    sig = strategy.generate_signals(df)
    a = atr(df["high"], df["low"], df["close"], 14)
    risk = RiskManager(cfg.initial_capital)
    eq = cfg.initial_capital
    pos: dict | None = None
    eq_pts = [(df.index[0], eq)]
    trades: list[dict] = []
    next_funding = df.index[0] + FUNDING_INTERVAL

    def trade_dict(entry, qty, lev, entry_ts, exit_p, exit_ts, pnl, reason):
        return {"symbol": "B-BTC_USDT", "strategy": strategy.meta.name,
                "side": "long", "entry_ts": entry_ts, "exit_ts": exit_ts,
                "entry_price": entry, "exit_price": exit_p, "quantity": qty,
                "leverage": lev, "pnl": pnl, "fees": pos["entry_fee"] if pos else 0.0,
                "exit_reason": reason, "source": "faithful"}

    for i in range(1, len(df)):
        ts = df.index[i]; row = df.iloc[i]
        c = float(row["close"]); hi = float(row["high"]); lo = float(row["low"])
        s = int(sig.iloc[i])
        av = float(a.iloc[i]) if not pd.isna(a.iloc[i]) else 0.0

        # mark-to-market equity for the risk gate (live gets mark from WS)
        mark = eq + (c - pos["entry"]) * pos["qty"] if pos is not None else eq
        risk.update_equity(mark, ts)

        # 8h funding on open position
        if pos is not None and ts >= next_funding:
            cost = pos["qty"] * c * cfg.funding_rate
            eq -= cost; pos["funding_paid"] += cost
            next_funding = ts + FUNDING_INTERVAL

        # liquidation (intrabar low below liq price)
        if pos is not None and lo <= pos["liq"]:
            pnl = -(pos["entry"] * pos["qty"] / pos["lev"]) - pos["entry_fee"] - pos["funding_paid"]
            eq += pnl; risk.record_realized(pnl)
            trades.append(trade_dict(pos["entry"], pos["qty"], pos["lev"], pos["entry_ts"],
                                      pos["liq"], ts, pnl, "liquidation"))
            pos = None; eq_pts.append((ts, eq)); continue

        # exit on sig==0 (strategy-driven, the live contract)
        if pos is not None and s == 0:
            fee = c * pos["qty"] * cfg.maker_fee
            pnl = (c - pos["entry"]) * pos["qty"] - pos["entry_fee"] - fee - pos["funding_paid"]
            eq += pnl; risk.record_realized(pnl)
            trades.append(trade_dict(pos["entry"], pos["qty"], pos["lev"], pos["entry_ts"],
                                      c, ts, pnl, "signal_exit"))
            pos = None; eq_pts.append((ts, eq)); continue

        # entry on 0->1, gated by RiskManager (daily-loss / drawdown / max-pos)
        if pos is None and s == 1 and i + 1 < len(df) and risk.can_open():
            stop = c - 2 * av if av > 0 else c * 0.98  # live uses 2 ATR sizing stop
            lev = risk.check_leverage(cfg.leverage)
            qty = risk.position_size(c, stop, lev, av)
            if qty > 0:
                fee_rate = cfg.maker_fee if cfg.maker_on_limit else cfg.taker_fee
                fee = c * qty * fee_rate
                eq -= fee
                pos = {"entry": c, "qty": qty, "lev": lev, "entry_ts": ts,
                       "entry_fee": fee, "funding_paid": 0.0,
                       "liq": liquidation_price("long", c, lev)}
                eq_pts.append((ts, eq))

    if pos is not None:  # flatten at last bar
        c = float(df["close"].iloc[-1]); fee = c * pos["qty"] * cfg.maker_fee
        pnl = (c - pos["entry"]) * pos["qty"] - pos["entry_fee"] - fee - pos["funding_paid"]
        eq += pnl; risk.record_realized(pnl)
        trades.append(trade_dict(pos["entry"], pos["qty"], pos["lev"], pos["entry_ts"],
                                  c, df.index[-1], pnl, "eod"))
        eq_pts.append((df.index[-1], eq))

    equity = pd.Series(dict(eq_pts)).sort_index()
    equity.name = "equity"
    return {"metrics": compute_metrics(equity, trades), "equity": equity, "trades": trades}


if __name__ == "__main__":
    # self-check: runs on synthetic, persistent-1 strategy, produces trades.
    import numpy as np
    from app.strategy.batch import StochrsiReversal
    n = 2000
    idx = pd.date_range("2025-01-01", periods=n, freq="5min", tz="UTC")
    rng = np.random.default_rng(1)
    c = pd.Series(30000 + np.cumsum(rng.normal(0, 40, n)), index=idx)
    h = c * (1 + rng.uniform(0, 0.004, n)); l = c * (1 - rng.uniform(0, 0.004, n))
    v = pd.Series(rng.uniform(1, 20, n), index=idx)
    df = pd.DataFrame({"open": c, "high": h, "low": l, "close": c, "volume": v}, index=idx)
    r = run_faithful(StochrsiReversal({"atr_mult": 3.0, "tp_mult": 2.0}), df,
                     BacktestConfig(maker_on_limit=True, leverage=3))
    m = r["metrics"]
    print(f"faithful self-check: trades={m['num_trades']} PF={m['profit_factor']:.2f} "
          f"net={m['net_profit']:.1f} dd={m['max_drawdown']:.3f}")
    assert m["num_trades"] > 0, "expected trades on synthetic"
    print("ok")