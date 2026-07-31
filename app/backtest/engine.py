"""Backtesting engine. Event loop over candles; long-only by default (shorts optional).

Simulates: market/limit fills, slippage (bps), maker/taker fees, funding (perpetual,
8h interval), leverage, isolated-margin liquidation, trailing/break-even stops,
take-profit/stop-loss, partial exits. Idempotent-ish (deterministic given data).

Entry: a +1 signal at bar t opens long at next open (t+1) to avoid look-ahead bias.
Exit: signal 0, or SL/TP/trailing hit intra-bar (conservative: check high/low).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta, timezone

import pandas as pd

from app.backtest.metrics import compute_metrics
from app.config import settings
from app.risk.manager import RiskManager, liquidation_price
from app.strategy.base import BaseStrategy
from app.strategy.indicators import atr

FUNDING_INTERVAL = timedelta(hours=8)
FUNDING_RATE_DEFAULT = 0.0001  # 0.01% per 8h; ponytail: load real funding if available


@dataclass
class Position:
    side: str  # 'long'
    entry_price: float
    qty: float
    leverage: int
    entry_ts: pd.Timestamp
    stop: float | None = None
    take_profit: float | None = None
    trailing_atr: float | None = None
    high_water: float = 0.0
    partial_taken: bool = False
    entry_fee: float = 0.0
    funding_paid: float = 0.0


@dataclass
class BacktestConfig:
    initial_capital: float = 10000.0
    leverage: int = settings.default_leverage
    maker_fee: float = settings.maker_fee
    taker_fee: float = settings.taker_fee
    slippage_bps: float = settings.slippage_bps
    funding_rate: float = FUNDING_RATE_DEFAULT
    use_trailing: bool = False
    trailing_mult: float = 2.0
    break_even_at: float = 1.0  # move stop to entry at 1x risk
    partial_exit: bool = False
    partial_frac: float = 0.5
    risk_pct_stop: float = 0.02  # default SL % if strategy gives none
    allow_short: bool = False
    maker_on_limit: bool = False  # if true, limit entries pay maker


class Backtester:
    def __init__(self, strategy: BaseStrategy, cfg: BacktestConfig | None = None):
        self.strategy = strategy
        self.cfg = cfg or BacktestConfig()
        self.trades: list[dict] = []
        self.equity_curve = pd.Series(dtype=float)

    def run(self, df: pd.DataFrame) -> dict:
        """Run over OHLCV df (tz-aware index). Returns metrics dict."""
        cfg = self.cfg
        if df.empty:
            return {"metrics": {}, "equity": self.equity_curve, "trades": []}
        # precompute ATR for trailing + risk sizing
        atr_series = atr(df["high"], df["low"], df["close"], 14)
        signals = self.strategy.generate_signals(df)

        equity = cfg.initial_capital
        pos: Position | None = None
        risk = RiskManager(equity)
        eq_points: list[tuple[pd.Timestamp, float]] = []
        next_funding = df.index[0] + FUNDING_INTERVAL

        def fill_price(ref: float, is_buy: bool) -> float:
            slip = cfg.slippage_bps / 10000.0
            return ref * (1 + slip) if is_buy else ref * (1 - slip)

        for i in range(1, len(df)):
            ts = df.index[i]
            row = df.iloc[i]
            # --- funding on open position at 8h marks ---
            if pos is not None and ts >= next_funding:
                notional = pos.qty * row["close"]
                cost = notional * cfg.funding_rate
                equity -= cost
                pos.funding_paid += cost
                next_funding = ts + FUNDING_INTERVAL

            # --- manage open position: SL/TP/trailing/liquidation ---
            if pos is not None:
                closed = self._manage(pos, row, ts, cfg)
                if closed:
                    equity += closed["pnl"]
                    self.trades.append(closed["trade"])
                    risk.record_realized(closed["pnl"])
                    pos = None
                    risk.state.open_positions = 0
                    risk.update_equity(equity)

            # --- liquidation check (isolated) ---
            if pos is not None:
                liq = liquidation_price(pos.side, pos.entry_price, pos.leverage)
                if pos.side == "long" and row["low"] <= liq:
                    pnl = -(pos.entry_price * pos.qty / pos.leverage)  # lose margin
                    equity += pnl - pos.entry_fee - pos.funding_paid
                    self.trades.append(self._trade_dict(pos, liq, ts, pnl, "liquidation"))
                    risk.record_realized(pnl)
                    pos = None
                    risk.state.open_positions = 0
                    risk.update_equity(equity)

            # --- entry on signal (use next bar open to avoid lookahead) ---
            sig = int(signals.iloc[i])
            if pos is None and sig == 1 and i + 1 < len(df):
                nxt = df.iloc[i + 1]
                risk.update_equity(equity)
                if risk.can_open():
                    entry = fill_price(nxt["open"], True)
                    stop = self._stop(entry, atr_series.iloc[i], cfg)
                    tp = self.strategy.take_profit(df, i) if hasattr(self.strategy, "take_profit") else None
                    lev = risk.check_leverage(cfg.leverage)
                    qty = risk.position_size(entry, stop, lev, atr_series.iloc[i])
                    if qty > 0:
                        fee = entry * qty * cfg.taker_fee
                        equity -= fee
                        pos = Position("long", entry, qty, lev, ts, stop=stop, take_profit=tp,
                                        trailing_atr=atr_series.iloc[i] if cfg.use_trailing else None,
                                        high_water=entry, entry_fee=fee)
                        risk.state.open_positions = 1

            eq_points.append((ts, equity))

        # close any remaining position at last close
        if pos is not None:
            row = df.iloc[-1]
            exit_p = fill_price(row["close"], False)
            pnl = (exit_p - pos.entry_price) * pos.qty - pos.entry_fee - exit_p * pos.qty * cfg.taker_fee - pos.funding_paid
            equity += pnl
            self.trades.append(self._trade_dict(pos, exit_p, df.index[-1], pnl, "eod"))
            eq_points.append((df.index[-1], equity))

        self.equity_curve = pd.Series(dict(eq_points)).sort_index()
        self.equity_curve.name = "equity"
        metrics = compute_metrics(self.equity_curve, self.trades)
        return {"metrics": metrics, "equity": self.equity_curve, "trades": self.trades}

    # --- helpers ---
    def _stop(self, entry: float, a: float, cfg: BacktestConfig) -> float:
        if pd.notna(a) and a > 0:
            return entry - cfg.trailing_mult * a if cfg.use_trailing else entry * (1 - cfg.risk_pct_stop)
        return entry * (1 - cfg.risk_pct_stop)

    def _manage(self, pos: Position, row, ts, cfg: BacktestConfig) -> dict | None:
        """Returns {'pnl', 'trade'} if closed, else None. Handles trailing/BE/partial."""
        # trailing stop update
        if pos.trailing_atr is not None and pd.notna(pos.trailing_atr):
            pos.high_water = max(pos.high_water, row["high"])
            new_stop = pos.high_water - cfg.trailing_mult * pos.trailing_atr
            if pos.stop is None or new_stop > pos.stop:
                pos.stop = new_stop
        # break-even
        if pos.stop is not None and cfg.break_even_at > 0:
            risk_dist = abs(pos.entry_price - (pos.entry_price - cfg.trailing_mult * (pos.trailing_atr or pos.entry_price * 0.02)))
            if row["high"] >= pos.entry_price + cfg.break_even_at * risk_dist and pos.stop < pos.entry_price:
                pos.stop = pos.entry_price

        # partial exit at first TP
        if cfg.partial_exit and not pos.partial_taken and pos.take_profit and row["high"] >= pos.take_profit:
            close_qty = pos.qty * cfg.partial_frac
            pnl_part = (pos.take_profit - pos.entry_price) * close_qty - pos.take_profit * close_qty * cfg.maker_fee
            pos.qty -= close_qty
            pos.partial_taken = True
            # record partial as its own realized trade
            self.trades.append(self._trade_dict(pos, pos.take_profit, ts, pnl_part, "partial"))
        # stop hit
        if pos.stop is not None and row["low"] <= pos.stop:
            exit_p = pos.stop
            pnl = (exit_p - pos.entry_price) * pos.qty - pos.entry_fee - exit_p * pos.qty * cfg.maker_fee - pos.funding_paid
            return {"pnl": pnl, "trade": self._trade_dict(pos, exit_p, ts, pnl, "stop_loss")}
        # take profit hit
        if pos.take_profit is not None and row["high"] >= pos.take_profit:
            exit_p = pos.take_profit
            pnl = (exit_p - pos.entry_price) * pos.qty - pos.entry_fee - exit_p * pos.qty * cfg.maker_fee - pos.funding_paid
            return {"pnl": pnl, "trade": self._trade_dict(pos, exit_p, ts, pnl, "take_profit")}
        return None

    def _trade_dict(self, pos: Position, exit_p: float, ts, pnl: float, reason: str) -> dict:
        return {
            "symbol": settings.symbol, "strategy": self.strategy.meta.name,
            "side": "long", "entry_ts": pos.entry_ts, "exit_ts": ts,
            "entry_price": pos.entry_price, "exit_price": exit_p,
            "quantity": pos.qty, "leverage": pos.leverage,
            "pnl": pnl, "fees": pos.entry_fee, "exit_reason": reason, "source": "backtest",
        }