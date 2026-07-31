"""SQLAlchemy models. One file for MVP; split as it grows.

Tables: candle, signal, order, trade, backtest_result, strategy_config.
All money fields are Decimal(20,8). Timestamps UTC, tz-naive stored as epoch ms is
avoided; use DateTime with timezone-aware via server defaults where possible.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Side(PyEnum):
    buy = "buy"
    sell = "sell"


class OrderType(PyEnum):
    market = "market_order"
    limit = "limit_order"
    stop_market = "stop_market"
    stop_limit = "stop_limit"


class Candle(Base):
    __tablename__ = "candle"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), index=True)  # 1m,5m,15m,30m,1H,4H,1D
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    volume: Mapped[Decimal] = mapped_column(Numeric(30, 8))

    __table_args__ = (Index("uq_candle_sym_tf_ts", "symbol", "timeframe", "ts", unique=True),)


class Signal(Base):
    __tablename__ = "signal"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    strategy: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(8))
    price: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    reason: Mapped[str] = mapped_column(Text, default="")


class Order(Base):
    __tablename__ = "order"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # idempotency key
    exchange_order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    strategy: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[str] = mapped_column(String(24))
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    leverage: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="new")  # new,filled,canceled,rejected
    filled_qty: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0)
    avg_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)


class Trade(Base):
    __tablename__ = "trade"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    strategy: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(8))
    entry_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    exit_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    leverage: Mapped[int] = mapped_column(Integer, default=1)
    pnl: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0)
    fees: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0)
    exit_reason: Mapped[str] = mapped_column(String(32), default="")
    source: Mapped[str] = mapped_column(String(16), default="backtest")  # backtest,paper,live


class BacktestResult(Base):
    __tablename__ = "backtest_result"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    strategy: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(8))
    params: Mapped[str] = mapped_column(Text)  # JSON
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    net_profit: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    win_rate: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    profit_factor: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    max_drawdown: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    sharpe: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    num_trades: Mapped[int] = mapped_column(Integer)
    report_path: Mapped[str | None] = mapped_column(Text, nullable=True)


class StrategyConfig(Base):
    __tablename__ = "strategy_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    class_name: Mapped[str] = mapped_column(String(64))
    params: Mapped[str] = mapped_column(Text)  # JSON
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())