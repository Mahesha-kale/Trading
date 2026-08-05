"""Risk manager. One guard for all paths (backtest + live route through here).

Position sizing = risk per trade: size = (equity * risk_per_trade) / |stop_distance|.
Daily loss, drawdown, max positions, leverage cap, kill switch. Stateful for live.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from app.config import settings
from app.logging import get_logger

log = get_logger("risk")


@dataclass
class RiskState:
    equity: float
    peak_equity: float
    day_start_equity: float
    day: str  # YYYY-MM-DD
    realized_pnl_today: float = 0.0
    open_positions: int = 0
    kill: bool = False


class RiskManager:
    """Shared risk gate. Both backtest and live call pre_trade() before sizing."""

    def __init__(
        self,
        equity: float,
        risk_per_trade=settings.risk_per_trade,
        max_daily_loss=settings.max_daily_loss,
        max_drawdown=settings.max_drawdown,
        max_positions=settings.max_positions,
        max_leverage=settings.max_leverage,
    ):
        self.risk_per_trade = risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.max_drawdown = max_drawdown
        self.max_positions = max_positions
        self.max_leverage = max_leverage
        today = datetime.now(timezone.utc).date().isoformat()
        self.state = RiskState(equity=equity, peak_equity=equity, day_start_equity=equity, day=today)

    def update_equity(self, equity: float) -> None:
        st = self.state
        st.equity = equity
        st.peak_equity = max(st.peak_equity, equity)
        today = datetime.now(timezone.utc).date().isoformat()
        if today != st.day:
            st.day = today
            st.day_start_equity = equity
            st.realized_pnl_today = 0.0

    def record_realized(self, pnl: float) -> None:
        self.state.realized_pnl_today += pnl

    def kill_switch(self, on: bool = True) -> None:
        self.state.kill = on
        log.warning("kill_switch", on=on)

    # --- checks ---
    def daily_loss_exceeded(self) -> bool:
        if self.max_daily_loss <= 0:
            return False
        return self.state.realized_pnl_today <= -(self.max_daily_loss * self.state.day_start_equity)

    def drawdown_exceeded(self) -> bool:
        if self.max_drawdown <= 0 or self.state.peak_equity <= 0:
            return False
        return (self.state.peak_equity - self.state.equity) / self.state.peak_equity >= self.max_drawdown

    def can_open(self) -> bool:
        if self.state.kill:
            log.warning("can_open blocked: kill switch")
            return False
        if self.daily_loss_exceeded():
            log.warning("can_open blocked: daily loss", realized=self.state.realized_pnl_today)
            return False
        if self.drawdown_exceeded():
            log.warning("can_open blocked: drawdown", dd=(self.state.peak_equity - self.state.equity) / self.state.peak_equity)
            return False
        if self.state.open_positions >= self.max_positions:
            log.warning("can_open blocked: max positions", open=self.state.open_positions)
            return False
        return True

    def position_size(self, entry_price: float, stop_price: float | None,
                      leverage: int, atr: float | None = None,
                      fx_rate: float | None = None) -> float:
        """Return qty in base asset (BTC). Risk-based if stop given, else ATR-based, else fixed fraction.

        entry_price/stop_price/atr are in QUOTE terms (USDT for B-BTC_USDT).
        equity is in the account margin currency (INR for this account).
        fx_rate = account_ccy per USDT (e.g. USDTINR ~99.8); None = 1.0
        (single-currency, e.g. USDT-margined account or backtest). Leverage
        does NOT amplify risk — it only changes margin. Caller enforces
        leverage/margin caps.
        """
        # risk_amount = account-ccy willing to lose = equity * risk_per_trade.
        fx = fx_rate if fx_rate else 1.0
        risk_amount = self.state.equity * self.risk_per_trade  # account ccy (INR)
        if stop_price is not None and stop_price != 0:
            dist = abs(entry_price - stop_price)  # USDT
            qty = risk_amount / (dist * fx) if dist > 0 else 0.0
        elif atr is not None and atr > 0:
            qty = risk_amount / (atr * fx)
        else:
            qty = risk_amount / (entry_price * fx)
        return max(qty, 0.0)

    def check_leverage(self, leverage: int) -> int:
        if leverage > self.max_leverage:
            log.warning("leverage capped", requested=leverage, cap=self.max_leverage)
            return self.max_leverage
        if leverage < 1:
            return 1
        return leverage


def liquidation_price(side: str, entry: float, leverage: int,
                      maint_margin_rate: float = 0.005) -> float:
    """Isolated-margin approx liquidation price. ponytail: simplified; exchange
    uses tiered maintenance margin + fees. Use for warning only, not final truth."""
    lev = max(leverage, 1)
    # accept both engine position sides ("long"/"short") and order sides ("buy"/"sell")
    if side in ("buy", "long"):
        return entry * (1 - (1 / lev) + maint_margin_rate)
    return entry * (1 + (1 / lev) - maint_margin_rate)


def margin_required(notional: float, leverage: int) -> float:
    return notional / max(leverage, 1)