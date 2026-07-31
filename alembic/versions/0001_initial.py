"""initial schema baseline

Revision ID: 0001
Revises:
Create Date: 2026-08-01

Baseline matching app.models.Base.metadata. On a DB already bootstrapped via
init_db()'s create_all, run `alembic stamp 0001` to mark it current without
recreating tables. On a fresh DB, `alembic upgrade head` creates everything.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import func

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "candle",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("high", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("low", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("close", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("volume", sa.Numeric(precision=30, scale=8), nullable=False),
        sa.Index("ix_candle_symbol", "symbol"),
        sa.Index("ix_candle_timeframe", "timeframe"),
        sa.Index("ix_candle_ts", "ts"),
        sa.UniqueConstraint("symbol", "timeframe", "ts", name="uq_candle_sym_tf_ts"),
    )

    op.create_table(
        "signal",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=func.now(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("strategy", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("reason", sa.Text(), server_default="", nullable=False),
        sa.Index("ix_signal_ts", "ts"),
        sa.Index("ix_signal_symbol", "symbol"),
        sa.Index("ix_signal_strategy", "strategy"),
    )

    op.create_table(
        "order",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_order_id", sa.String(length=64), nullable=False),
        sa.Column("exchange_order_id", sa.String(length=64), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=func.now(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("strategy", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("order_type", sa.String(length=24), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("stop_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("leverage", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="new", nullable=False),
        sa.Column("filled_qty", sa.Numeric(precision=20, scale=8), server_default="0", nullable=False),
        sa.Column("avg_fill_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.UniqueConstraint("client_order_id", name="uq_order_client_order_id"),
        sa.Index("ix_order_client_order_id", "client_order_id"),
        sa.Index("ix_order_exchange_order_id", "exchange_order_id"),
        sa.Index("ix_order_ts", "ts"),
        sa.Index("ix_order_symbol", "symbol"),
        sa.Index("ix_order_strategy", "strategy"),
    )

    op.create_table(
        "trade",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("strategy", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("entry_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("exit_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("leverage", sa.Integer(), server_default="1", nullable=False),
        sa.Column("pnl", sa.Numeric(precision=20, scale=8), server_default="0", nullable=False),
        sa.Column("fees", sa.Numeric(precision=20, scale=8), server_default="0", nullable=False),
        sa.Column("exit_reason", sa.String(length=32), server_default="", nullable=False),
        sa.Column("source", sa.String(length=16), server_default="backtest", nullable=False),
        sa.Index("ix_trade_symbol", "symbol"),
        sa.Index("ix_trade_strategy", "strategy"),
        sa.Index("ix_trade_entry_ts", "entry_ts"),
    )

    op.create_table(
        "backtest_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=func.now(), nullable=False),
        sa.Column("strategy", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("params", sa.Text(), nullable=False),
        sa.Column("start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("net_profit", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("win_rate", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("profit_factor", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("max_drawdown", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("sharpe", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("num_trades", sa.Integer(), nullable=False),
        sa.Column("report_path", sa.Text(), nullable=True),
        sa.Index("ix_backtest_result_ts", "ts"),
        sa.Index("ix_backtest_result_strategy", "strategy"),
    )

    op.create_table(
        "strategy_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("class_name", sa.String(length=64), nullable=False),
        sa.Column("params", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=func.now(), nullable=False),
        sa.UniqueConstraint("name", name="uq_strategy_config_name"),
        sa.Index("ix_strategy_config_name", "name"),
    )


def downgrade() -> None:
    op.drop_table("strategy_config")
    op.drop_table("backtest_result")
    op.drop_table("trade")
    op.drop_table("order")
    op.drop_table("signal")
    op.drop_table("candle")