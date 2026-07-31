"""Stress / scale self-checks. Large data, grid scaling, engine buffer bound,
risk kill switch, all registered strategies emit valid signals. No exchange
calls; engine buffer test patches _evaluate so it stays DB-free too."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from app.backtest.engine import BacktestConfig, Backtester
from app.backtest.optimize import optimize_grid
from app.live.engine import TradingEngine
from app.risk.manager import RiskManager
from app.strategy.ema_cross import EmaCross
from app.strategy.registry import REGISTRY, get_strategy


def _synth(n: int = 20000, seed: int = 2) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    drift = np.cumsum(rng.normal(0.0002, 0.01, n))
    close = 30000 + drift * 100
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    high = close * (1 + rng.uniform(0, 0.003, n))
    low = close * (1 - rng.uniform(0, 0.003, n))
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close,
                         "volume": rng.uniform(1, 10, n)}, index=idx)


def test_large_backtest_completes_fast():
    df = _synth(20000)
    t0 = time.monotonic()
    res = Backtester(EmaCross({"fast": 5, "slow": 20}), BacktestConfig()).run(df)
    dt = time.monotonic() - t0
    assert not res["equity"].empty
    assert dt < 30.0, f"backtest too slow: {dt:.1f}s"


def test_optimize_grid_scales():
    df = _synth(2000)
    grid = {"fast": [3, 5, 8, 13], "slow": [20, 40, 60, 100]}
    best = optimize_grid("ema_cross", df, grid, score_key="net_profit")
    assert best.params["fast"] < best.params["slow"]


def test_engine_buffer_bounded():
    eng = TradingEngine(EmaCross({"fast": 5, "slow": 10}), RiskManager(equity=10000.0))
    eng._min_bars = 10

    async def _noop_evaluate():  # patch out strategy/DB so only buffer logic runs
        pass
    eng._evaluate = _noop_evaluate  # type: ignore[method-assign]

    base = {"open": 30000.0, "high": 30100.0, "low": 29900.0, "close": 30050.0, "volume": 1.0}

    async def feed():
        for i in range(5000):
            await eng.on_candle({**base, "time": (1700000000 + i * 60) * 1000})

    import asyncio
    asyncio.run(feed())
    assert len(eng._buffer) <= eng._min_bars + 5, f"buffer grew unbounded: {len(eng._buffer)}"


def test_risk_kill_on_daily_loss():
    r = RiskManager(equity=10000.0, max_daily_loss=0.05)
    r.record_realized(-600.0)  # -6% exceeds 5% cap
    r.update_equity(9400.0)
    assert r.daily_loss_exceeded()
    assert not r.can_open()


def test_all_registered_strategies_signal():
    df = _synth(600)
    for name in REGISTRY:
        sig = get_strategy(name).generate_signals(df)
        assert sig.dtype.kind in "iu"
        assert set(np.unique(sig.dropna().astype(int))).issubset({-1, 0, 1}), name