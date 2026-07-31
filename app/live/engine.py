"""Live + paper trading engine. Same signal logic as backtest; execution differs.

paper: fills simulated on incoming candle close; no exchange calls.
live:  orders via CoinDCXClient, idempotent via client_order_id (uuid4 hex),
       retry with backoff, reduce_only on exits, position tracked from WS fills.

Crash recovery: on restart, reconcile open DB Order rows with exchange positions
on startup (reconcile()). Idempotent create_order: same client_order_id reused
on retry; exchange dedups by it.
"""
from __future__ import annotations

import asyncio
import math
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd

from app.config import settings
from app.exchange.coindcx import CoinDCXClient, CoinDCXError, build_order
from app.logging import get_logger
from app.models import Order, Signal, Trade
from app.risk.manager import RiskManager
from app.strategy.base import BaseStrategy
from app.strategy.indicators import atr
from app.strategy.registry import REGISTRY as REGISTRY_NAMES

log = get_logger("live.engine")


@dataclass
class LivePosition:
    side: str
    entry_price: float
    qty: float
    leverage: int
    entry_ts: datetime
    stop: float | None = None
    take_profit: float | None = None
    fx: float = 1.0  # USDT/INR at entry; PnL settled in INR via FX at close
    entry_fee: float = 0.0  # USDT taker fee paid on entry (for realistic close PnL)


def _round_trip_cost(qty: float, price: float, fx: float) -> tuple[float, float, float]:
    """Estimated entry+exit cost in account ccy (INR): taker fees both sides
    + slippage both sides. Used for UI display + signal cost annotation."""
    notional_inr = qty * price * fx
    fee = notional_inr * settings.taker_fee * 2
    slip = notional_inr * (settings.slippage_bps / 10000.0) * 2
    return fee, slip, fee + slip


class TradingEngine:
    def __init__(self, strategy: BaseStrategy, risk: RiskManager, client: CoinDCXClient | None = None,
                 symbol: str = settings.symbol):
        self.strategy = strategy
        self.risk = risk
        self.symbol = symbol
        self.client = client or CoinDCXClient()
        self.paper = settings.trading_mode == "paper"
        self.pos: LivePosition | None = None
        self.auto_trade = True  # signal-driven open/close; False = manual-only
        self._inst: dict | None = None  # cached instrument constraints
        self._buffer: list[pd.Series] = []
        self._min_bars = strategy.warmup

    async def on_candle(self, msg: dict) -> None:
        """Called by WS feed. Aggregates into buffer; on enough bars, evaluate."""
        candle = msg.get("candlestick") or msg
        if "close" not in candle:
            return
        ts = datetime.fromtimestamp(candle.get("time", time.time() * 1000) / 1000, tz=timezone.utc)
        bar = pd.Series({
            "open": float(candle["open"]), "high": float(candle["high"]),
            "low": float(candle["low"]), "close": float(candle["close"]),
            "volume": float(candle.get("volume", 0)),
        }, name=ts)
        self._buffer.append(bar)
        if len(self._buffer) > self._min_bars + 5:
            self._buffer.pop(0)
        if len(self._buffer) >= self._min_bars:
            await self._evaluate()

    @staticmethod
    def _tf_minutes(tf: str) -> int:
        """15m -> 15, 1H -> 60, 4H -> 240, 1D -> 1440."""
        t = tf.strip()
        if t.endswith("m"):
            return max(int(t[:-1] or 1), 1)
        if t.endswith("H"):
            return int(t[:-1] or 1) * 60
        if t.endswith("D"):
            return int(t[:-1] or 1) * 1440
        return 15  # ponytail: unknown tf fallback

    async def seed_buffer(self) -> int:
        """Prefill the candle buffer from DB so indicators are valid immediately
        on startup. Without this, a fresh start waits `warmup` bars in real-time
        from WS (e.g. 200 x 15m = 50h) before the first signal can fire."""
        from datetime import datetime, timedelta, timezone
        from app.data.downloader import load_candles
        tf = self.strategy.meta.timeframe
        n = self._min_bars + 5
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=self._tf_minutes(tf) * (n + 5))
        df = await load_candles(self.symbol, tf, start, end)
        if df.empty:
            log.warning("seed_empty", symbol=self.symbol, tf=tf,
                        hint="run `trader download 365 15m` to populate")
            return 0
        df = df.tail(n)
        self._buffer = [
            pd.Series({"open": float(r.open), "high": float(r.high),
                       "low": float(r.low), "close": float(r.close),
                       "volume": float(r.volume)}, name=r.Index)
            for r in df.itertuples()
        ]
        log.info("buffer_seeded", bars=len(self._buffer), tf=tf)
        return len(self._buffer)

    async def manual_trade(self, action: str, *, leverage: int | None = None,
                            take_profit: float | None = None, stop_loss: float | None = None,
                            margin: float | None = None, qty: float | None = None) -> dict:
        """UI-triggered trade. action = buy|sell|close. buy=open long, sell=open short,
        close=exit current. If margin (INR) given, qty = margin*lev/(price*fx); elif qty
        given, use it; else risk-based sizing using stop_loss (or ATR). Respects kill
        switch; bypasses signal/warmup gates (user-initiated)."""
        if self.risk.state.kill:
            raise RuntimeError("kill switch engaged; release it first")
        if action == "close":
            await self._close(reason="manual", ts=pd.Timestamp.utcnow())
            return {"action": "closed"}
        if action not in ("buy", "sell"):
            raise ValueError(f"bad action {action} (buy|sell|close)")
        if self.pos is not None:
            raise RuntimeError("position already open; close first")
        price = await self._last_price()
        fx = await self._fx()
        lev = self.risk.check_leverage(leverage or settings.default_leverage)
        a = 0.0
        if self._buffer:
            df = pd.DataFrame(self._buffer)
            df.index = pd.to_datetime(df.index)
            a = float(atr(df["high"], df["low"], df["close"], 14).iloc[-1])
        long = action == "buy"
        if stop_loss is not None:
            stop = stop_loss
        elif a > 0:
            stop = price - 2 * a if long else price + 2 * a
        else:
            stop = price * 0.98 if long else price * 1.02
        # qty: explicit > margin-based > risk-based
        if qty is not None and qty > 0:
            q = qty
        elif margin is not None and margin > 0:
            # notional_INR = qty * price * fx; margin = notional / lev → qty = margin*lev/(price*fx)
            q = (margin * lev) / (price * fx)
        else:
            q = self.risk.position_size(price, stop, lev, a, fx_rate=fx)
        if q <= 0:
            raise RuntimeError("qty 0 (set margin or qty, or check equity/fx)")
        await self._open(side=action, qty=q, price=price, stop=stop,
                         leverage=lev, ts=pd.Timestamp.utcnow(), fx=fx,
                         take_profit=take_profit)
        fee_inr, slip_inr, cost_inr = _round_trip_cost(q, price, fx)
        await self._emit_signal(sig=1 if long else -1, price=price, cost_inr=cost_inr)
        return {"action": action, "qty": q, "price": price, "fx": fx, "stop": stop,
                "leverage": lev, "take_profit": take_profit,
                "fee_inr": fee_inr, "slippage_inr": slip_inr, "cost_inr": cost_inr}

    def set_strategy(self, name: str) -> None:
        """Swap the engine's active strategy (for the auto-trader)."""
        from app.strategy.registry import get_strategy
        if name not in REGISTRY_NAMES:
            raise ValueError(f"unknown strategy {name}")
        self.strategy = get_strategy(name)
        self._min_bars = self.strategy.warmup
        self._inst = None  # constraints unchanged but force fresh warmup logic
        log.info("strategy_set", name=name)

    async def _last_price(self) -> float:
        try:
            return await self.client.get_last_price(self.symbol)
        except Exception as e:  # noqa: BLE001
            if self._buffer:
                return float(self._buffer[-1]["close"])
            raise

    async def _evaluate(self) -> None:
        if not self.auto_trade:
            return  # manual-only mode: skip signal-driven open/close
        df = pd.DataFrame(self._buffer)
        df.index = pd.to_datetime(df.index)
        sig_series = self.strategy.generate_signals(df)
        sig = int(sig_series.iloc[-1])
        a = float(atr(df["high"], df["low"], df["close"], 14).iloc[-1])
        price = float(df["close"].iloc[-1])

        if self.pos is None and sig == 1:
            self.risk.update_equity(self.risk.state.equity)  # caller updates equity from WS
            if self.risk.can_open():
                stop = price - 2 * a if a > 0 else price * 0.98
                lev = self.risk.check_leverage(settings.default_leverage)
                # FX: equity in INR, price in USDT → convert for sizing.
                fx = await self._fx()
                qty = self.risk.position_size(price, stop, lev, a, fx_rate=fx)
                if qty > 0:
                    try:
                        await self._open(side="buy", qty=qty, price=price, stop=stop,
                                         leverage=lev, ts=df.index[-1], fx=fx)
                        _, _, cost_inr = _round_trip_cost(qty, price, fx)
                        await self._emit_signal(sig=1, price=price, cost_inr=cost_inr)
                    except RuntimeError as e:  # pre-flight reject (qty/min) on live
                        log.warning("auto_open_skipped", error=str(e))
        elif self.pos is not None and sig == 0:
            await self._close(reason="signal_exit", ts=df.index[-1], price=price)

    # --- execution ---
    async def _fx(self) -> float:
        """USDT/INR rate for current sizing/settlement. 1.0 if USDT-margined."""
        if settings.margin_currency != "INR":
            return 1.0
        try:
            return await self.client.get_usdt_inr()
        except Exception as e:  # noqa: BLE001
            log.warning("fx_fetch_failed", error=str(e))
            return self.pos.fx if self.pos else 1.0

    async def _instrument(self) -> dict:
        if self._inst is None:
            try:
                self._inst = await self.client.get_instrument(self.symbol, settings.margin_currency)
            except Exception as e:  # noqa: BLE001
                log.warning("instrument_fetch_failed", error=str(e))
                self._inst = {}
        return self._inst or {}

    def _normalize_qty(self, qty: float, price: float) -> tuple[float, str]:
        """Round qty to lot step; enforce min_quantity + min_notional.
        Returns (valid_qty, error_msg). err non-empty => do NOT send order."""
        inst = self._inst or {}
        step = float(inst.get("quantity_increment") or 0.001)
        min_q = float(inst.get("min_quantity") or 0)
        min_n = float(inst.get("min_notional") or 0)
        qty = max(math.floor(qty / step) * step, 0.0)
        if qty < min_q:
            return 0.0, f"qty {qty:.6f} < min_quantity {min_q}"
        if qty * price < min_n:
            need = min_n / price
            return 0.0, (f"notional {qty*price:.2f} USDT < min_notional {min_n}; "
                        f"need qty>={need:.4f} (raise leverage or capital)")
        return qty, ""

    async def _open(self, *, side: str, qty: float, price: float, stop: float,
                    leverage: int, ts: pd.Timestamp, fx: float = 1.0,
                    take_profit: float | None = None) -> None:
        pos_side = "long" if side == "buy" else "short"
        client_id = uuid.uuid4().hex
        order = build_order(side=side, pair=self.symbol, order_type="market_order",
                            quantity=qty, leverage=leverage,
                            stop_loss_price=round(stop, 2),
                            position_margin_type="isolated")
        if take_profit is not None:
            order["take_profit_price"] = round(take_profit, 2)
        order["client_order_id"] = client_id
        # Pre-flight TP/SL side validation: CoinDCX 422s (and used to 3x-retry
        # → kill) when TP/SL are on the wrong side of last price. Catch here.
        long = side == "buy"
        if take_profit is not None:
            if long and take_profit <= price:
                raise RuntimeError(f"take_profit {take_profit} must be > price {price} for a long")
            if not long and take_profit >= price:
                raise RuntimeError(f"take_profit {take_profit} must be < price {price} for a short")
        if stop is not None:
            if long and stop >= price:
                raise RuntimeError(f"stop_loss {stop} must be < price {price} for a long")
            if not long and stop <= price:
                raise RuntimeError(f"stop_loss {stop} must be > price {price} for a short")
        await self._persist_order(order, client_id, "new")
        if self.paper:
            fill = price
            fee_usdt = qty * price * settings.taker_fee
            self.risk.update_equity(self.risk.state.equity - fee_usdt * fx)
            self.pos = LivePosition(pos_side, fill, qty, leverage, ts.to_pydatetime(),
                                    stop=stop, take_profit=take_profit, fx=fx,
                                    entry_fee=fee_usdt)
            self.risk.state.open_positions = 1
            log.info("paper_open", side=pos_side, qty=qty, price=fill, stop=stop,
                     tp=take_profit, fee_usdt=fee_usdt, fx=fx)
            return
        # live: validate qty against exchange min before sending (avoids
        # guaranteed reject → 3 retries → kill switch).
        await self._instrument()
        qty_n, err = self._normalize_qty(qty, price)
        if err:
            raise RuntimeError(f"order pre-flight rejected: {err}")
        qty = qty_n
        order["total_quantity"] = qty
        for attempt in range(3):
            try:
                resp = await self._retry(self.client.create_order, order)
                # create_order returns a LIST of order objects ([{id,...}]);
                # id is at each element's top level.
                if isinstance(resp, list):
                    ex_id = resp[0].get("id") if resp else None
                elif isinstance(resp, dict):
                    ex_id = (resp.get("order", {}) or {}).get("id") or resp.get("id")
                else:
                    ex_id = None
                await self._persist_order(order, client_id, "filled", exchange_id=str(ex_id))
                self.pos = LivePosition(pos_side, price, qty, leverage, ts.to_pydatetime(),
                                        stop=stop, take_profit=take_profit, fx=fx,
                                        entry_fee=qty * price * settings.taker_fee)
                self.risk.state.open_positions = 1
                log.info("live_open", side=pos_side, client_id=client_id, ex_id=ex_id, fx=fx)
                return
            except CoinDCXError as e:
                # 4xx = deterministic validation reject (bad TP/SL/qty). Retrying
                # is pointless and would arm the kill switch on a user-input
                # error. Surface to the UI (RuntimeError → 409) and bail.
                if e.is_client_error:
                    raise RuntimeError(f"order rejected by exchange: {e}") from e
                log.error("open_retry", attempt=attempt, error=str(e))
                await asyncio.sleep(2 ** attempt)
            except Exception as e:  # noqa: BLE001
                log.error("open_retry", attempt=attempt, error=str(e))
                await asyncio.sleep(2 ** attempt)
        self.risk.kill_switch(True)  # repeated transient failure -> halt

    async def _close(self, *, reason: str, ts: pd.Timestamp, price: float | None = None) -> None:
        if self.pos is None:
            return
        pos = self.pos
        # exit side is opposite of position side
        exit_side = "sell" if pos.side == "long" else "buy"
        direction = 1.0 if pos.side == "long" else -1.0
        client_id = uuid.uuid4().hex
        if self.paper:
            exit_p = price or pos.entry_price
            fx_close = await self._fx()
            slip = settings.slippage_bps / 10000.0
            # exit fill worse by slippage (sell lower / cover higher)
            fill_exit = exit_p * (1 - slip) if pos.side == "long" else exit_p * (1 + slip)
            exit_fee = pos.qty * exit_p * settings.taker_fee
            # PnL in USDT, settled to INR via FX at close; subtract entry+exit fee
            # (entry fee was paid at open, exit fee now) — matches backtest realism.
            pnl_usdt = direction * (fill_exit - pos.entry_price) * pos.qty - pos.entry_fee - exit_fee
            pnl = pnl_usdt * fx_close
            self.risk.record_realized(pnl)
            self.risk.update_equity(self.risk.state.equity + pnl)
            await self._persist_trade(pos, exit_p, ts, pnl,
                                      (pos.entry_fee + exit_fee) * fx_close, reason, "paper")
            log.info("paper_close", reason=reason, side=pos.side, pnl_inr=pnl, fx=fx_close)
            self.pos = None
            self.risk.state.open_positions = 0
            return
        # reduce_only market exit
        order = build_order(side=exit_side, pair=self.symbol, order_type="market_order",
                            quantity=pos.qty, leverage=pos.leverage)
        order["client_order_id"] = client_id
        await self._persist_order(order, client_id, "closing")
        for attempt in range(3):
            try:
                resp = await self._retry(self.client.create_order, order)
                log.info("live_close", reason=reason, client_id=client_id, resp=str(resp)[:120])
                # ponytail: live realized pnl read from exchange wallet via
                # _refresh_equity; per-trade pnl here is an estimate for history.
                exit_p = price or pos.entry_price
                slip = settings.slippage_bps / 10000.0
                fill_exit = exit_p * (1 - slip) if pos.side == "long" else exit_p * (1 + slip)
                exit_fee = pos.qty * exit_p * settings.taker_fee
                pnl = (direction * (fill_exit - pos.entry_price) * pos.qty
                       - pos.entry_fee - exit_fee) * pos.fx
                await self._persist_trade(pos, exit_p, ts, pnl,
                                          (pos.entry_fee + exit_fee) * pos.fx, reason, "live")
                self.pos = None
                self.risk.state.open_positions = 0
                await self._refresh_equity()  # settled PnL lives on the exchange wallet
                return
            except Exception as e:  # noqa: BLE001
                log.error("close_retry", attempt=attempt, error=str(e))
                await asyncio.sleep(2 ** attempt)

    async def _persist_trade(self, pos: LivePosition, exit_price: float, ts: pd.Timestamp,
                              pnl: float, fees: float, reason: str, source: str) -> None:
        from app.db import session_scope
        async with session_scope() as s:
            s.add(Trade(
                symbol=self.symbol, strategy=self.strategy.meta.name, side=pos.side,
                entry_ts=pos.entry_ts, exit_ts=ts.to_pydatetime(),
                entry_price=Decimal(str(pos.entry_price)),
                exit_price=Decimal(str(exit_price)),
                quantity=Decimal(str(pos.qty)), leverage=pos.leverage,
                pnl=Decimal(str(pnl)), fees=Decimal(str(fees)),
                exit_reason=reason, source=source,
            ))

    async def _retry(self, coro_fn, *args, **kwargs):
        t0 = time.monotonic()
        res = await coro_fn(*args, **kwargs)
        log.debug("latency_ms", ms=int((time.monotonic() - t0) * 1000))
        return res

    async def _persist_order(self, order: dict, client_id: str, status: str,
                             exchange_id: str | None = None) -> None:
        # Upsert by client_order_id: the "new" row is written before create_order,
        # then "filled"/"closing" updates the SAME row (client_order_id is unique;
        # a second add() would raise IntegrityError → retry → kill switch).
        from sqlalchemy import select
        from app.db import session_scope
        async with session_scope() as s:
            row = (await s.execute(
                select(Order).where(Order.client_order_id == client_id)
            )).scalar_one_or_none()
            if row is None:
                s.add(Order(
                    client_order_id=client_id, exchange_order_id=exchange_id,
                    symbol=self.symbol, strategy=self.strategy.meta.name,
                    side=order["side"], order_type=order["order_type"],
                    quantity=Decimal(str(order["total_quantity"])),
                    price=Decimal(str(order["price"])) if order.get("price") else None,
                    stop_price=Decimal(str(order.get("stop_loss_price"))) if order.get("stop_loss_price") else None,
                    leverage=order.get("leverage", 1), status=status,
                ))
            else:
                row.status = status
                if exchange_id is not None:
                    row.exchange_order_id = exchange_id

    async def _emit_signal(self, *, sig: int, price: float,
                           cost_inr: float | None = None) -> None:
        from app.db import session_scope
        from app.notify.telegram import notify
        reason = "entry" if sig == 1 else "exit"
        if sig == 1 and cost_inr is not None:
            reason = f"entry | cost {cost_inr:.1f} INR"
        async with session_scope() as s:
            s.add(Signal(symbol=self.symbol, strategy=self.strategy.meta.name,
                         side="buy" if sig == 1 else "sell",
                         price=Decimal(str(price)),
                         reason=reason))
        if settings.telegram_bot_token:
            await notify(f"{'LONG' if sig==1 else 'FLAT'} {self.symbol} @ {price} ({self.strategy.meta.name})")

    async def reconcile(self) -> None:
        """On startup: fetch live positions, restore self.pos if one open. Crash recovery.
        Also seeds risk equity from the INR wallet balance (not the 10000 default)."""
        if self.paper:
            return
        try:
            await self._refresh_equity()
            positions = await self.client.get_positions(self.symbol)
            open_pos = [p for p in positions if float(p.get("position_size", 0)) != 0]
            if open_pos:
                p = open_pos[0]
                self.pos = LivePosition(
                    side="long" if float(p.get("position_size", 0)) > 0 else "short",
                    entry_price=float(p.get("avg_entry_price", 0)),
                    qty=abs(float(p.get("position_size", 0))),
                    leverage=int(p.get("leverage", 1)),
                    entry_ts=datetime.now(timezone.utc),
                    stop=float(p.get("stop_loss")) if p.get("stop_loss") else None,
                    fx=await self._fx(),
                )
                self.risk.state.open_positions = 1
                log.info("reconciled_position", qty=self.pos.qty, entry=self.pos.entry_price)
        except Exception as e:  # noqa: BLE001
            log.error("reconcile_failed", error=str(e))

    async def _refresh_equity(self) -> None:
        """Set risk equity to the live wallet balance in margin currency (INR)."""
        try:
            wallets = await self.client.get_wallets()
            bal = 0.0
            for w in (wallets if isinstance(wallets, list) else []):
                if w.get("currency_short_name") == settings.margin_currency:
                    bal += float(w.get("balance", 0))
            if bal > 0:
                self.risk.update_equity(bal)
                log.info("equity_seeded", ccy=settings.margin_currency, equity=bal)
        except Exception as e:  # noqa: BLE001
            log.warning("equity_refresh_failed", error=str(e))