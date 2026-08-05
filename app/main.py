"""FastAPI app + CLI entry. Lifespan: init DB, optionally start live engine."""
from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.config import settings
from app.db import init_db
from app.logging import configure_logging, get_logger
from app.live.engine import TradingEngine
from app.risk.manager import RiskManager
from app.strategy.registry import get_strategy
from app.exchange.ws import CoinDCXWS

log = get_logger("main")
_live_engine: TradingEngine | None = None
_ws: CoinDCXWS | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("startup", mode=settings.trading_mode, symbol=settings.symbol)
    await init_db()
    # only auto-start engine in paper/live; test mode = API + data only
    if settings.trading_mode in ("paper", "live"):
        global _live_engine, _ws
        strat = get_strategy(settings.default_strategy)
        risk = RiskManager(equity=10000.0)
        _live_engine = TradingEngine(strat, risk)
        await _live_engine.seed_buffer()  # prefill indicators from DB (no warmup wait)
        if settings.trading_mode == "live":
            await _live_engine.reconcile()
        _ws = CoinDCXWS(on_candle=_live_engine.on_candle)
        _ws.subscribe_candle(settings.symbol, strat.meta.timeframe)  # match strategy TF, not hardcoded 1m
        _ws.subscribe_price(settings.symbol)
        asyncio.create_task(_ws.run())
        log.info("engine_started", mode=settings.trading_mode, tf=strat.meta.timeframe)
    yield
    if _ws:
        _ws.stop()
    log.info("shutdown")


app = FastAPI(title="CoinDCX BTC/USDT Futures Trader", version="0.1.0", lifespan=lifespan)
app.include_router(router, prefix="/api")


def cli():
    """`trader` entrypoint: `trader serve` starts uvicorn; `trader backtest` runs inline."""
    if len(sys.argv) < 2:
        print("usage: trader serve|download|backtest")
        return
    cmd = sys.argv[1]
    if cmd == "serve":
        import uvicorn
        uvicorn.run("app.main:app", host=settings.host, port=8000, reload=False)
    elif cmd == "download":
        from datetime import datetime, timedelta, timezone
        from app.data.downloader import download_ohlcv
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 365
        tf = sys.argv[3] if len(sys.argv) > 3 else "15m"
        configure_logging()
        n = asyncio.run(download_ohlcv("B-BTC_USDT", tf,
                                         datetime.now(timezone.utc) - timedelta(days=days),
                                         datetime.now(timezone.utc)))
        print(f"downloaded {n} candles ({tf}, {days}d)")
    elif cmd == "backtest":
        from datetime import datetime, timedelta, timezone
        from app.backtest.engine import BacktestConfig, Backtester
        from app.data.downloader import load_candles
        name = sys.argv[2] if len(sys.argv) > 2 else "ema_cross"
        days = int(sys.argv[3]) if len(sys.argv) > 3 else 180
        configure_logging()
        df = asyncio.run(load_candles("B-BTC_USDT", "15m",
                                       datetime.now(timezone.utc) - timedelta(days=days),
                                       datetime.now(timezone.utc)))
        strat = get_strategy(name)
        res = Backtester(strat, BacktestConfig()).run(df)
        print(res["metrics"])
    else:
        print(f"unknown command {cmd}")


if __name__ == "__main__":
    cli()