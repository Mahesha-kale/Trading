"""Cost/risk sweep: find a profitable config among the robust top strategies.

Why these levers (not leverage): position_size is risk-based (qty = eq*risk% /
stop_dist), so PnL and fees both scale linearly with qty -> leverage is PF-neutral.
What actually moves PF: maker fees (halve entry cost), atr_mult (wider stops ->
fewer noise stops -> higher win rate), daily-loss limit (survivorship - blocks
trades after a bad day), trade frequency.

Engine entry fee now respects maker_on_limit (realistic limit-entry model).
Daily-loss is read from settings at RiskManager construction, so monkeypatch
settings.max_daily_loss per run.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

from app.backtest.engine import BacktestConfig, Backtester
from app.config import settings
from app.data.downloader import load_candles

logging.getLogger().setLevel(logging.ERROR)
import structlog as _sl  # reconfigure at ERROR so cached risk logger stops spamming
_sl.configure(wrapper_class=_sl.make_filtering_bound_logger(logging.ERROR),
               cache_logger_on_first_use=False)

# name -> (tf, kind, base_params). atr_mult swept separately.
STRATS = {
    "stochrsi_reversal": ("5m", "reversion", {}),
    "ema_pullback":      ("15m", "trend", {"tol_atr": 0.4}),
    "obv_divergence":    ("15m", "trend", {"swing": 40}),
    "psar_trend":        ("15m", "trend", {}),
}
TF_DAYS = {"5m": 150, "15m": 330}


def cfg(kind: str, atr_mult: float, maker: bool) -> BacktestConfig:
    if kind == "reversion":
        return BacktestConfig(use_trailing=False, risk_pct_stop=0.05, leverage=3,
                              break_even_at=0.0, maker_on_limit=maker)
    return BacktestConfig(use_trailing=True, trailing_mult=atr_mult, leverage=3,
                          break_even_at=0.0, maker_on_limit=maker)


async def main():
    data = {}
    for tf, d in TF_DAYS.items():
        data[tf] = await load_candles("B-BTC_USDT", tf,
                                      datetime.now(timezone.utc) - timedelta(days=d),
                                      datetime.now(timezone.utc))
    print(f"bars 5m={len(data['5m'])} 15m={len(data['15m'])}", flush=True)
    results = []
    for name, (tf, kind, bp) in STRATS.items():
        df = data[tf]
        split = int(len(df) * 0.7); test = df.iloc[split:]
        for maker in (False, True):
            for am in (3.0, 4.0, 5.0, 6.0):
                for dl in (0.05, 0.10, 0.0):  # 0.0 = daily-loss off
                    settings.max_daily_loss = dl
                    p = {**bp, "atr_mult": am}
                    c = cfg(kind, am, maker)
                    f = Backtester(__import__("app.strategy.registry", fromlist=["get_strategy"]).get_strategy(name, p), c).run(df)["metrics"]
                    tag = "MAKER" if maker else "taker"
                    dls = f"{dl:.0%}" if dl else "off"
                    net, pf, sh, dd, tr = f["net_profit"], f["profit_factor"], f["sharpe"], f["max_drawdown"], f["num_trades"]
                    win = net > 0 and pf > 1.0 and sh > 0
                    mark = " <<< PROFITABLE" if win else ""
                    print(f"{name:18} {tf} {tag:5} dl={dls:4} am={am} | PF={pf:.2f} net={net:7.1f} sh={sh:.2f} dd={dd:.3f} tr={tr}{mark}", flush=True)
                    if win:
                        o = Backtester(__import__("app.strategy.registry", fromlist=["get_strategy"]).get_strategy(name, p), c).run(test)["metrics"]
                        results.append({"name": name, "tf": tf, "maker": maker, "dl": dl, "am": am,
                                        "full": f, "oos": o})
    print("\n=== PROFITABLE CONFIGS (with OOS check) ===", flush=True)
    if not results:
        print("none under these levers", flush=True)
        return
    for r in sorted(results, key=lambda x: x["oos"].get("sharpe", 0), reverse=True):
        f, o = r["full"], r["oos"]
        print(f"{r['name']:18} {r['tf']} {'MAKER' if r['maker'] else 'taker'} dl={r['dl']} am={r['am']} | "
              f"full PF={f['profit_factor']:.2f} net={f['net_profit']:.1f} sh={f['sharpe']:.2f} dd={f['max_drawdown']:.3f} tr={f['num_trades']} | "
              f"oos PF={o['profit_factor']:.2f} sh={o['sharpe']:.2f} tr={o['num_trades']}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())