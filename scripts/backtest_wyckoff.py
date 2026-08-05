"""Backtest + tune Wyckoff, render HTML report. Train 70% / test 30% split.

Engine uses its own ATR trailing stop (cfg.use_trailing) sized to the strategy's
atr_mult, since engine._stop ignores strategy.stop_loss. The strategy's own
trailing exit (c < trail) and the engine's then agree.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.backtest.engine import BacktestConfig, Backtester
from app.backtest.optimize import optimize_grid
from app.backtest.report import render_report
from app.data.downloader import load_candles
from app.logging import configure_logging
from app.strategy.registry import get_strategy

configure_logging()

GRID = {
    "range_period": [60, 80],
    "vol_expand": [1.2, 1.5],
    "sos_window": [40, 60, 80],
    "atr_mult": [3.0, 5.0, 8.0],
}


def cfg_for(atr_mult: float) -> BacktestConfig:
    # low leverage (swing); engine ATR trailing stop mirrors the strategy's
    # atr_mult and is the backtest exit (backtest ignores held sig=1). Paper
    # exits via the strategy's own sig=0 trail; both are ATR-trailing, close.
    return BacktestConfig(use_trailing=True, trailing_mult=atr_mult,
                          leverage=3, break_even_at=0.0)


async def main():
    df = await load_candles("B-BTC_USDT", "15m",
                            datetime.now(timezone.utc) - timedelta(days=365),
                            datetime.now(timezone.utc))
    split = int(len(df) * 0.7)
    train_full, test = df.iloc[:split], df.iloc[split:]
    # tune on a recent slice of train (faster); evaluate on full test OOS.
    train = train_full.tail(12000)
    print(f"tune {len(train)}  test {len(test)}  full {len(df)}")

    base = Backtester(get_strategy("wyckoff"), cfg_for(3.0)).run(df)
    print("baseline:", {k: round(v, 4) if isinstance(v, float) else v for k, v in base["metrics"].items()})

    # grid search with matching ATR-trailing cfg (engine._stop ignores
    # strategy.stop_loss, so trailing_mult must mirror atr_mult).
    from app.backtest.optimize import grid_params
    cfgs = list(grid_params(GRID))
    print(f"grid: {len(cfgs)} configs")
    cand_results = []
    for n, params in enumerate(cfgs, 1):
        bp = {}
        for k, v in params.items():
            if k in ("range_period", "sos_window"):
                bp[k] = int(v)
            elif v is None:
                bp[k] = None
            else:
                bp[k] = float(v)
        m = Backtester(get_strategy("wyckoff", bp), cfg_for(bp["atr_mult"])).run(train)["metrics"]
        cand_results.append((bp, m.get("sharpe", 0) or 0, m))
        if n % 6 == 0:
            print(f"  {n}/{len(cfgs)} done, last sharpe {round(m.get('sharpe',0) or 0,2)}")
    cand_results.sort(key=lambda x: x[1], reverse=True)
    bp, sc, _ = cand_results[0]
    print("best train params:", bp, "sharpe", round(sc, 3))
    cand_results.sort(key=lambda x: x[1], reverse=True)
    bp, sc, _ = cand_results[0]
    print("best train params:", bp, "sharpe", round(sc, 3))

    test_res = Backtester(get_strategy("wyckoff", bp), cfg_for(bp["atr_mult"])).run(test)
    full_res = Backtester(get_strategy("wyckoff", bp), cfg_for(bp["atr_mult"])).run(df)
    print("test :", {k: round(v, 3) if isinstance(v, float) else v for k, v in test_res["metrics"].items()})
    print("full :", {k: round(v, 3) if isinstance(v, float) else v for k, v in full_res["metrics"].items()})
    print("test trades", len(test_res["trades"]), " full trades", len(full_res["trades"]))

    out = render_report(full_res["metrics"], full_res["equity"], full_res["trades"],
                        "wyckoff", bp, "reports/wyckoff.html")
    print("report:", out)


if __name__ == "__main__":
    asyncio.run(main())