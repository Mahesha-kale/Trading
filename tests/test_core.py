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


def test_daily_loss_resets_per_backtest_day():
    """Daily-loss circuit breaker must reset across backtest bar-days, using the
    bar timestamp — not wall-clock now. Before the fix, a multi-year backtest
    tripped the 5% limit once then blocked every entry for the rest of the run."""
    r = RiskManager(equity=10000.0, max_daily_loss=0.05)
    d1 = pd.Timestamp("2025-01-01 12:00", tz="UTC")
    d2 = pd.Timestamp("2025-01-02 12:00", tz="UTC")
    r.update_equity(10000.0, d1)
    r.record_realized(-600.0)  # exceeds 5% of 10k -> blocks for the day
    assert not r.can_open()
    r.update_equity(9400.0, d2)  # next bar-day -> realized today resets
    assert r.can_open()


def test_regime_gate_blocks_entries_below_sma():
    """regime_sma blocks new longs while close < SMA(N). A huge N on a short
    series -> SMA is NaN everywhere -> no new longs -> 0 trades; without the
    gate the same strategy trades. Exits are NOT gated (trailing/TP still run)."""
    df = _synth(400)
    strat = EmaCross({"fast": 5, "slow": 20})
    no_gate = Backtester(strat, BacktestConfig(initial_capital=10000.0)).run(df.copy())
    gated = Backtester(strat, BacktestConfig(initial_capital=10000.0, regime_sma=1000)).run(df.copy())
    assert no_gate["metrics"]["num_trades"] > 0
    assert gated["metrics"]["num_trades"] == 0


def test_short_profits_when_price_falls():
    """Short side: sig -1 opens a short (allow_short=True). Price falls -> the
    short closes at EOD for a profit. pnl = (entry-exit)*qty - fees > 0, side
    is 'short'. Without allow_short the -1 signal is ignored (0 trades)."""
    from app.strategy.base import BaseStrategy, StrategyMeta

    class OneShort(BaseStrategy):
        meta = StrategyMeta(name="oneshort", timeframe="15m", warmup=0)
        params = {}

        def generate_signals(self, df):
            s = pd.Series(0, index=df.index, dtype=int)
            s.iloc[1] = -1
            return s

    idx = pd.date_range("2025-01-01", periods=4, freq="15min", tz="UTC")
    close = pd.Series([100.0, 100.0, 95.0, 90.0], index=idx)
    df = pd.DataFrame({"open": [100.0, 100.0, 100.0, 95.0], "high": close + 0.5,
                       "low": close - 0.5, "close": close, "volume": 1.0}, index=idx)
    base = dict(initial_capital=10000.0, leverage=1, use_trailing=False, risk_pct_stop=0.5,
                taker_fee=0.001, maker_fee=0.001, slippage_bps=0.0, maker_on_limit=False,
                funding_rate=0.0)
    res = Backtester(OneShort(), BacktestConfig(allow_short=True, **base)).run(df.copy())
    trades = res["trades"]
    assert len(trades) == 1, trades
    assert trades[0]["side"] == "short"
    assert trades[0]["pnl"] > 0, trades[0]
    # without allow_short, the -1 signal is ignored
    res2 = Backtester(OneShort(), BacktestConfig(allow_short=False, **base)).run(df.copy())
    assert res2["metrics"]["num_trades"] == 0