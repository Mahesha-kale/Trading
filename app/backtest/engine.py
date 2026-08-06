"""Backtesting engine. Event loop over candles; long-only by default (shorts optional).

Simulates: market/limit fills, slippage (bps), maker/taker fees, funding (perpetual,
8h interval), leverage, isolated-margin liquidation, trailing/break-even stops,
take-profit/stop-loss, partial exits. Idempotent-ish (deterministic given data).

Entry: a +1 signal at bar t opens long at next open (t+1) to avoid look-ahead bias.
Exit: SL/TP/trailing hit intra-bar (conservative: check high/low), else flatten at
last bar. NOTE: this engine does NOT exit on signal 0 -- by design it relies on the
ATR trailing stop (trend kind) or fixed stop + strategy.take_profit (reversion kind);
see scripts/rank.py cfg_for(). The signal-0 exit contract lives in the live/paper
engine and its mirror app/backtest/faithful.py, which expect persistent-1 (hold)
signals. Pulse-+1 strategies work here because the trailing/TP manages the exit.
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
    high_water: float = 0.0   # long: highest favorable price
    low_water: float = 0.0    # short: lowest favorable price
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
    regime_sma: int | None = None  # block new longs while close < SMA(N); trailing still exits
    funding_rates: "pd.Series | None" = None  # signed per-8h funding history
    # (index=8h mark UTC, value=signed rate). If given, funding at each 8h event
    # uses the asof rate (most recent <= bar ts) instead of the flat funding_rate
    # -- models real dynamic/signed funding (negative in bears: longs receive).


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
        # regime gate: SMA(N) of close. Below it, block new longs (don't force
        # exits -- trailing/TP still manages open positions, mirroring the grid
        # gate "stop adding long risk in a downtrend, let inventory work off").
        gate = (df["close"].rolling(cfg.regime_sma).mean()
                if cfg.regime_sma else None)

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
            # funding accrues on the position and is realized once at close (in
            # the exit pnl), NOT subtracted from cash here -- subtracting here
            # AND in the exit pnl double-counted it. equity stays flat during a
            # position (this engine tracks realized cash, not MTM).
            if pos is not None and ts >= next_funding:
                # sign: long pays funding (+cost), short receives it when rate>0
                # (-cost, i.e. income). funding_paid is a SIGNED cost accumulator
                # realized once at close via the exit pnl.
                s = 1 if pos.side == "long" else -1
                if cfg.funding_rates is not None:
                    r = cfg.funding_rates.asof(ts)
                    rate = float(r) if pd.notna(r) else cfg.funding_rate
                else:
                    rate = cfg.funding_rate
                pos.funding_paid += s * pos.qty * row["close"] * rate
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
                    risk.update_equity(equity, ts)

            # --- liquidation check (isolated) ---
            if pos is not None:
                liq = liquidation_price(pos.side, pos.entry_price, pos.leverage)
                hit = (pos.side == "long" and row["low"] <= liq) or \
                     (pos.side == "short" and row["high"] >= liq)
                if hit:
                    pnl = -(pos.entry_price * pos.qty / pos.leverage)  # lose margin
                    equity += pnl - pos.entry_fee - pos.funding_paid
                    self.trades.append(self._trade_dict(pos, liq, ts, pnl, "liquidation"))
                    risk.record_realized(pnl)
                    pos = None
                    risk.state.open_positions = 0
                    risk.update_equity(equity, ts)

            # --- entry on signal (use next bar open to avoid lookahead) ---
            # regime gate is symmetric: new longs only above SMA(N), new shorts
            # only below it (don't add long risk in a downtrend, don't add short
            # risk in an uptrend). allow_short gates the short side entirely.
            sig = int(signals.iloc[i])
            long_open = sig == 1 and (gate is None or row["close"] > gate.iloc[i])
            short_open = (sig == -1 and cfg.allow_short
                          and (gate is None or row["close"] < gate.iloc[i]))
            if pos is None and (long_open or short_open) and i + 1 < len(df):
                nxt = df.iloc[i + 1]
                risk.update_equity(equity, ts)
                if risk.can_open():
                    is_long = long_open
                    side = "long" if is_long else "short"
                    entry = fill_price(nxt["open"], is_long)  # long buys up, short sells down
                    stop = self._stop(entry, atr_series.iloc[i], cfg, side)
                    # take_profit is strategy-defined for longs (reversion); trend
                    # shorts ride the trailer -> no TP on the short side.
                    tp = (self.strategy.take_profit(df, i)
                          if (hasattr(self.strategy, "take_profit") and is_long) else None)
                    lev = risk.check_leverage(cfg.leverage)
                    qty = risk.position_size(entry, stop, lev, atr_series.iloc[i])
                    if qty > 0:
                        # maker_on_limit: limit entries pay maker (realistic for
                        # signal-on-close -> limit-next-bar models). Halves entry cost.
                        # entry fee accrues on the position and is realized once at
                        # close (exit pnl), not subtracted from cash here.
                        entry_fee_rate = cfg.maker_fee if cfg.maker_on_limit else cfg.taker_fee
                        fee = entry * qty * entry_fee_rate
                        trail = atr_series.iloc[i] if cfg.use_trailing else None
                        if is_long:
                            pos = Position("long", entry, qty, lev, ts, stop=stop, take_profit=tp,
                                            trailing_atr=trail, high_water=entry, entry_fee=fee)
                        else:
                            pos = Position("short", entry, qty, lev, ts, stop=stop, take_profit=None,
                                            trailing_atr=trail, low_water=entry, entry_fee=fee)
                        risk.state.open_positions = 1

            eq_points.append((ts, equity))

        # close any remaining position at last close
        if pos is not None:
            row = df.iloc[-1]
            s = 1 if pos.side == "long" else -1
            exit_p = fill_price(row["close"], pos.side == "short")  # long sells, short buys back
            pnl = (s * (exit_p - pos.entry_price) * pos.qty - pos.entry_fee
                   - exit_p * pos.qty * cfg.taker_fee - pos.funding_paid)
            equity += pnl
            self.trades.append(self._trade_dict(pos, exit_p, df.index[-1], pnl, "eod"))
            eq_points.append((df.index[-1], equity))

        self.equity_curve = pd.Series(dict(eq_points)).sort_index()
        self.equity_curve.name = "equity"
        metrics = compute_metrics(self.equity_curve, self.trades)
        return {"metrics": metrics, "equity": self.equity_curve, "trades": self.trades}

    # --- helpers ---
    def _stop(self, entry: float, a: float, cfg: BacktestConfig, side: str = "long") -> float:
        s = 1 if side == "long" else -1
        if pd.notna(a) and a > 0 and cfg.use_trailing:
            return entry - s * cfg.trailing_mult * a
        return entry * (1 - s * cfg.risk_pct_stop)

    def _manage(self, pos: Position, row, ts, cfg: BacktestConfig) -> dict | None:
        """Returns {'pnl', 'trade'} if closed, else None. Direction-aware: long and
        short share one path via sign s; long ratchets stop up off highs, short
        ratchets stop down off lows. pnl = s*(exit-entry)*qty - fees - funding."""
        s = 1 if pos.side == "long" else -1
        a = pos.trailing_atr
        # trailing stop update
        if a is not None and pd.notna(a):
            if s == 1:
                pos.high_water = max(pos.high_water, row["high"])
                new_stop = pos.high_water - cfg.trailing_mult * a
                if pos.stop is None or new_stop > pos.stop:
                    pos.stop = new_stop
            else:
                pos.low_water = min(pos.low_water, row["low"])
                new_stop = pos.low_water + cfg.trailing_mult * a
                if pos.stop is None or new_stop < pos.stop:
                    pos.stop = new_stop
        # break-even: move stop to entry once price moves break_even_at x risk
        if pos.stop is not None and cfg.break_even_at > 0:
            risk_dist = cfg.trailing_mult * (a if (a is not None and pd.notna(a)) else pos.entry_price * 0.02)
            favor = (row["high"] - pos.entry_price) if s == 1 else (pos.entry_price - row["low"])
            beyond = (pos.stop < pos.entry_price) if s == 1 else (pos.stop > pos.entry_price)
            if favor >= cfg.break_even_at * risk_dist and beyond:
                pos.stop = pos.entry_price

        # partial exit at first TP (long-oriented; trend shorts have no TP)
        if cfg.partial_exit and not pos.partial_taken and pos.take_profit is not None:
            hit = (row["high"] >= pos.take_profit) if s == 1 else (row["low"] <= pos.take_profit)
            if hit:
                close_qty = pos.qty * cfg.partial_frac
                pnl_part = (s * (pos.take_profit - pos.entry_price) * close_qty
                            - pos.take_profit * close_qty * cfg.maker_fee)
                pos.qty -= close_qty
                pos.partial_taken = True
                # record partial as its own realized trade
                self.trades.append(self._trade_dict(pos, pos.take_profit, ts, pnl_part, "partial"))
        # stop hit: long low<=stop, short high>=stop
        if pos.stop is not None and ((s == 1 and row["low"] <= pos.stop) or (s == -1 and row["high"] >= pos.stop)):
            exit_p = pos.stop
            pnl = (s * (exit_p - pos.entry_price) * pos.qty - pos.entry_fee
                   - exit_p * pos.qty * cfg.maker_fee - pos.funding_paid)
            return {"pnl": pnl, "trade": self._trade_dict(pos, exit_p, ts, pnl, "stop_loss")}
        # take profit hit: long high>=tp, short low<=tp
        if pos.take_profit is not None:
            tp_hit = (row["high"] >= pos.take_profit) if s == 1 else (row["low"] <= pos.take_profit)
            if tp_hit:
                exit_p = pos.take_profit
                pnl = (s * (exit_p - pos.entry_price) * pos.qty - pos.entry_fee
                       - exit_p * pos.qty * cfg.maker_fee - pos.funding_paid)
                return {"pnl": pnl, "trade": self._trade_dict(pos, exit_p, ts, pnl, "take_profit")}
        return None

    def _trade_dict(self, pos: Position, exit_p: float, ts, pnl: float, reason: str) -> dict:
        return {
            "symbol": settings.symbol, "strategy": self.strategy.meta.name,
            "side": pos.side, "entry_ts": pos.entry_ts, "exit_ts": ts,
            "entry_price": pos.entry_price, "exit_price": exit_p,
            "quantity": pos.qty, "leverage": pos.leverage,
            "pnl": pnl, "fees": pos.entry_fee, "exit_reason": reason, "source": "backtest",
        }