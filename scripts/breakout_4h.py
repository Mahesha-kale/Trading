"""Step 2: non-laggy signal class on 4h. The crossover/supertrend strategies
whipsaw in chop; breakout/momentum with an ADX/chop filter may bleed less.
Tests donchian_breakout, ichimoku_breakout, obv_divergence, adx_trend
(app/strategy/batch.py, long-only persistent-1) on 4h, gated (regime_sma=200)
AND ungated, full + 70/30 OOS. Grid-tunes each strategy's own params on train
(sharpe) via the rank.py grids, then scores best on full + OOS.

OOS (2025-07->2026-07) is a downtrend (buyhold -42%): long-only trend will
either bleed (ungated, re-enters long) or go flat (gated, 0 trades). The
deliverable is whether a non-laggy signal bleeds LESS than the laggy
ema_cross/supertrend (which bled OOS sh ~-0.7 ungated). Reuses scripts/rank.py
cfg_for + cast_params + grid. Real perp costs (no TDS). Usage: python scripts/breakout_4h.py
"""
from __future__ import annotations

import logging

import pandas as pd
import structlog as _sl

from app.backtest.engine import BacktestConfig, Backtester
from app.strategy.registry import get_strategy

_sl.configure(wrapper_class=_sl.make_filtering_bound_logger(logging.ERROR),
               cache_logger_on_first_use=False)

SMA = 200
LEVERAGE = 3

# cfg_for from scripts/rank.py inlined (scripts/ is not a package)
def cfg_for(kind: str, atr_mult: float) -> BacktestConfig:
    if kind == "reversion":
        return BacktestConfig(use_trailing=False, risk_pct_stop=0.02, leverage=LEVERAGE,
                              break_even_at=0.0, maker_on_limit=True)
    return BacktestConfig(use_trailing=True, trailing_mult=atr_mult, leverage=LEVERAGE,
                          break_even_at=0.0, maker_on_limit=True)

INT_KEYS = {"range_bars", "lookback", "period", "fast", "slow", "sos_window",
            "swing", "adx_thresh", "adx_period", "atr_period", "trend_ema",
            "tenkan", "kijun", "senkou_b", "rsi_period", "stoch_period", "signal"}

def cast_params(name: str, params: dict) -> dict:
    return {k: (int(v) if k in INT_KEYS and v is not None else v) for k, v in params.items()}

def grid_combos(grid: dict) -> list[dict]:
    keys = list(grid); out = [{}]
    for k in keys:
        out = [dict(b, **{k: v}) for b in out for v in grid[k]]
    return out

# subset of rank.py STRATEGIES grids for the 4 non-laggy trend signals
GRIDS = {
    "adx_trend":         {"adx_thresh": [20, 28], "atr_mult": [3.0, 4.0]},
    "donchian_breakout": {"lookback": [30, 50], "atr_mult": [3.0, 4.0]},
    "ichimoku_breakout": {"atr_mult": [3.0, 4.0]},
    "obv_divergence":    {"swing": [25, 40], "atr_mult": [3.0, 4.0]},
}


def load_4h() -> pd.DataFrame:
    df = pd.read_csv("reports/binance_BTCUSDT_15m.csv", index_col=0, parse_dates=True)
    df = df.sort_index()
    return df.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                  "close": "last", "volume": "sum"}).dropna()


def cfg(kind: str, atr_mult: float, gated: bool) -> BacktestConfig:
    c = cfg_for(kind, atr_mult)
    c.regime_sma = SMA if gated else None
    return c


def mrow(m: dict) -> dict:
    return {"tr": int(m.get("num_trades", 0)),
            "sh": round(float(m.get("sharpe", 0)), 2),
            "net": round(float(m.get("net_profit", 0)), 1),
            "dd": round(float(m.get("max_drawdown", 0)), 3),
            "pf": round(float(m.get("profit_factor", 0)), 2),
            "win": round(float(m.get("win_rate", 0)), 3)}


def tune(name: str, grid: dict, df: pd.DataFrame, gated: bool, kind: str = "trend") -> tuple[dict, dict]:
    """Grid-tune params on full train (sharpe); return (best_params, full metrics)."""
    split = int(len(df) * 0.7)
    train = df.iloc[:split]
    best, best_sh = {}, -1e9
    for p in grid_combos(grid):
        bp = cast_params(name, p)
        am = float(bp.get("atr_mult", 3.0))
        try:
            m = Backtester(get_strategy(name, bp), cfg(kind, am, gated)).run(train)["metrics"]
            sh = m.get("sharpe", 0) or 0
            if sh > best_sh:
                best_sh, best = sh, bp
        except Exception:
            continue
    am = float(best.get("atr_mult", 3.0))
    full = Backtester(get_strategy(name, best), cfg(kind, am, gated)).run(df)["metrics"]
    return best, full


def main():
    df = load_4h()
    split_ts = df.index[int(len(df) * 0.7)]
    oos = df.loc[split_ts:]
    bh_full = df["close"].iloc[-1] / df["close"].iloc[0] - 1
    bh_oos = oos["close"].iloc[-1] / oos["close"].iloc[0] - 1
    print(f"4h BTC: {len(df)} bars {df.index[0].date()}->{df.index[-1].date()} "
          f"| split {split_ts.date()} | oos {len(oos)}", flush=True)
    print(f"buy&hold: full {bh_full*100:.0f}% | oos {bh_oos*100:.0f}% (downtrend)\n", flush=True)
    print(f"{'strategy':18}{'gate':5}{'params':22}{'win':4}{'tr':>4}{'sh':>6}"
          f"{'net':>9}{'dd':>7}{'pf':>6}   (full | oos)", flush=True)
    # trend: breakout/momentum (donchian, ichimoku, obv, adx)
    for name, grid in GRIDS.items():
        for gated in (False, True):
            bp, mf = tune(name, grid, df, gated)
            am = float(bp.get("atr_mult", 3.0))
            mo = Backtester(get_strategy(name, bp), cfg("trend", am, gated)).run(oos)["metrics"]
            ff, oo = mrow(mf), mrow(mo)
            ps = ",".join(f"{k}={v}" for k, v in bp.items() if k != "atr_mult") or "-"
            print(f"{name:18}{'Y' if gated else 'N':5}{ps:22}"
                  f"{'FULL':4}{ff['tr']:4d}{ff['sh']:6.2f}{ff['net']:9.1f}{ff['dd']:7.3f}{ff['pf']:6.2f}",
                  flush=True)
            print(f"{'':18}{'':5}{'':22}"
                  f"{'OOS':4}{oo['tr']:4d}{oo['sh']:6.2f}{oo['net']:9.1f}{oo['dd']:7.3f}{oo['pf']:6.2f}",
                  flush=True)
    # reversion: long-only mean-revert buys oversold dips, sells the bounce. In a
    # CHOPPY downtrend OOS it can net positive without shorts -- the only long-only
    # class that profits in chop. cfg_for('reversion') = fixed stop + strategy TP.
    print(f"\n--- reversion (long-only, buy dips / sell bounce) ---", flush=True)
    REV = {
        "keltner_mr":        {"mult": [1.8, 2.2], "atr_mult": [2.0, 3.0]},
        "stochrsi_reversal": {"atr_mult": [2.0, 3.0]},
        "cci_reversion":     {"period": [15, 20], "atr_mult": [2.0, 3.0]},
    }
    for name, grid in REV.items():
        for gated in (False, True):
            bp, mf = tune(name, grid, df, gated, kind="reversion")
            am = float(bp.get("atr_mult", 3.0))
            mo = Backtester(get_strategy(name, bp), cfg("reversion", am, gated)).run(oos)["metrics"]
            ff, oo = mrow(mf), mrow(mo)
            ps = ",".join(f"{k}={v}" for k, v in bp.items() if k != "atr_mult") or "-"
            print(f"{name:18}{'Y' if gated else 'N':5}{ps:22}"
                  f"{'FULL':4}{ff['tr']:4d}{ff['sh']:6.2f}{ff['net']:9.1f}{ff['dd']:7.3f}{ff['pf']:6.2f}",
                  flush=True)
            print(f"{'':18}{'':5}{'':22}"
                  f"{'OOS':4}{oo['tr']:4d}{oo['sh']:6.2f}{oo['net']:9.1f}{oo['dd']:7.3f}{oo['pf']:6.2f}",
                  flush=True)
    print("\nOOS is a CHOPPY downtrend: long-only trend bleeds (gate does NOT go flat "
          "here -- price crosses SMA200 on rallies, re-arming longs). Only mean-revert "
          "(buy dips) can profit long-only in chop. Edge only if OOS sh>0 & net>0.")


if __name__ == "__main__":
    main()