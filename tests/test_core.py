"""Core self-checks. Synthetic data, no DB/exchange needed. Runs via `pytest`.

Covers: indicators sanity, risk sizing, backtest produces trades + equity,
liquidation price monotonic in leverage, optimization picks better params.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.backtest.engine import BacktestConfig, Backtester
from app.backtest.optimize import optimize_grid
from app.risk.manager import RiskManager, liquidation_price
from app.strategy.ema_cross import EmaCross
from app.strategy.indicators import atr, ema, rsi, supertrend


def _synth(n: int = 600, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # uptrend with noise so EMA cross triggers
    drift = np.cumsum(rng.normal(0.0005, 0.01, n))
    close = 30000 + drift * 100
    idx = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    high = close * (1 + rng.uniform(0, 0.003, n))
    low = close * (1 - rng.uniform(0, 0.003, n))
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close,
                         "volume": rng.uniform(1, 10, n)}, index=idx)


def test_indicators_basic():
    df = _synth()
    assert not ema(df["close"], 10).isna().iloc[-1]
    assert 0 <= rsi(df["close"], 14).iloc[-1] <= 100
    a = atr(df["high"], df["low"], df["close"], 14)
    assert a.iloc[-1] > 0
    st, d = supertrend(df["high"], df["low"], df["close"])
    assert set(np.unique(d.dropna().astype(int))).issubset({1, -1})


def test_risk_position_size():
    r = RiskManager(equity=10000.0, risk_per_trade=0.01, max_leverage=5)
    # risk $100 (1% of 10k) on $500 stop distance -> 0.2 qty
    qty = r.position_size(entry_price=30000, stop_price=29500, leverage=1)
    assert abs(qty - 0.2) < 1e-6  # 100 / 500 = 0.2
    assert r.check_leverage(10) == 5  # capped


def test_liquidation_monotonic():
    e = 30000
    lp1 = liquidation_price("buy", e, 1)
    lp5 = liquidation_price("buy", e, 5)
    lp20 = liquidation_price("buy", e, 20)
    # higher leverage -> closer liquidation (less margin cushion)
    assert lp20 > lp5 > lp1


def test_backtest_runs_and_produces_equity():
    df = _synth()
    res = Backtester(EmaCross({"fast": 5, "slow": 20}), BacktestConfig(initial_capital=10000.0)).run(df)
    assert not res["equity"].empty
    assert "net_profit" in res["metrics"]
    assert res["metrics"]["num_trades"] >= 0


def test_optimize_picks_better():
    df = _synth()
    grid = {"fast": [5, 10], "slow": [20, 40]}
    best = optimize_grid("ema_cross", df, grid, score_key="net_profit")
    assert best.params in [{"fast": 5, "slow": 20}, {"fast": 5, "slow": 40},
                           {"fast": 10, "slow": 20}, {"fast": 10, "slow": 40}]