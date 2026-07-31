"""Central configuration. Single source of truth, loaded from env."""
from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Exchange
    coindcx_api_key: str = ""
    coindcx_api_secret: str = ""
    trading_mode: str = "paper"  # test | paper | live
    symbol: str = "B-BTC_USDT"
    # CoinDCX futures: same B-BTC_USDT contract can be margined in USDT or INR.
    # This account uses INR margin; PnL settles in INR. Set MARGIN_CURRENCY in .env to override.
    margin_currency: str = "INR"

    rest_base: str = "https://api.coindcx.com"
    public_base: str = "https://public.coindcx.com"
    ws_url: str = "wss://stream.coindcx.com"

    # Infra
    database_url: str = "postgresql+asyncpg://trader:trader@localhost:5432/trader"
    redis_url: str = "redis://localhost:6379/0"

    # Risk
    risk_per_trade: float = 0.01
    max_daily_loss: float = 0.05
    max_drawdown: float = 0.20
    max_positions: int = 3
    max_leverage: int = 10
    default_leverage: int = 10

    # Backtest costs
    maker_fee: float = 0.00025
    taker_fee: float = 0.0006
    slippage_bps: float = 2.0

    # Notifications
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    log_level: str = "INFO"

    # Bind address. 127.0.0.1 = localhost-only (safe default, no API auth).
    # Docker prod sets HOST=0.0.0.0 via docker-compose so nginx can reach it.
    host: str = "127.0.0.1"

    @field_validator("trading_mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        allowed = {"test", "paper", "live"}
        if v not in allowed:
            raise ValueError(f"trading_mode must be one of {allowed}")
        return v

    @property
    def live(self) -> bool:
        return self.trading_mode == "live"


settings = Settings()