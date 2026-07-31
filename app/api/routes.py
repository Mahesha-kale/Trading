"""REST API. Health, strategies, backtest, optimize, trades, positions, signals."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.backtest.engine import BacktestConfig, Backtester
from app.backtest.optimize import optimize_grid, walk_forward
from app.backtest.report import render_report
from app.data.downloader import download_ohlcv, load_candles
from app.db import session_scope
from app.exchange.coindcx import CoinDCXClient
from app.models import BacktestResult, Signal, Trade
from app.strategy.registry import REGISTRY

router = APIRouter()


# --- models ---
class BacktestReq(BaseModel):
    strategy: str
    params: dict = {}
    timeframe: str = "15m"
    days: int = 180
    initial_capital: float = 10000.0
    leverage: int = 3


class OptimizeReq(BaseModel):
    strategy: str
    grid: dict[str, list]
    timeframe: str = "15m"
    days: int = 180
    score_key: str = "sharpe"
    walk_forward: bool = False
    n_splits: int = 5


class DownloadReq(BaseModel):
    timeframe: str = "15m"
    days: int = 365


class ModeReq(BaseModel):
    mode: str
    confirm: bool = False


class KillReq(BaseModel):
    on: bool = True


class TradeReq(BaseModel):
    action: str  # "buy" | "sell" | "close"
    leverage: int | None = None
    take_profit: float | None = None
    stop_loss: float | None = None
    margin: float | None = None  # INR margin → derives qty
    qty: float | None = None     # explicit qty (overrides margin)


class AutoReq(BaseModel):
    on: bool = True


class StrategyReq(BaseModel):
    name: str


# --- routes ---
@router.get("/health")
async def health():
    return {"status": "ok", "mode": "see config"}


@router.get("/strategies")
async def list_strategies():
    return [{"name": name, "params": cls.params, "timeframe": cls.meta.timeframe}
            for name, cls in REGISTRY.items()]


@router.post("/data/download")
async def data_download(req: DownloadReq):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=req.days)
    n = await download_ohlcv("B-BTC_USDT", req.timeframe, start, end)
    return {"rows": n}


@router.post("/backtest")
async def run_backtest(req: BacktestReq):
    if req.strategy not in REGISTRY:
        raise HTTPException(404, f"unknown strategy {req.strategy}")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=req.days)
    df = await load_candles("B-BTC_USDT", req.timeframe, start, end)
    if df.empty:
        raise HTTPException(400, "no data in DB; run /data/download first")
    strat = REGISTRY[req.strategy](req.params)
    cfg = BacktestConfig(initial_capital=req.initial_capital, leverage=req.leverage)
    res = Backtester(strat, cfg).run(df)
    report = render_report(res["metrics"], res["equity"], res["trades"],
                           req.strategy, req.params, "reports/backtest.html")
    # persist summary
    async with session_scope() as s:
        s.add(BacktestResult(
            strategy=req.strategy, symbol="B-BTC_USDT", timeframe=req.timeframe,
            params=str(req.params), start=start, end=end,
            net_profit=Decimal(str(res["metrics"]["net_profit"])),
            win_rate=Decimal(str(res["metrics"]["win_rate"])),
            profit_factor=Decimal(str(res["metrics"]["profit_factor"])) if res["metrics"]["profit_factor"] != float("inf") else Decimal("999"),
            max_drawdown=Decimal(str(res["metrics"]["max_drawdown"])),
            sharpe=Decimal(str(res["metrics"]["sharpe"])),
            num_trades=res["metrics"]["num_trades"], report_path=report,
        ))
    return {"metrics": _safe(res["metrics"]), "report": report, "num_trades": len(res["trades"])}


@router.post("/optimize")
async def run_optimize(req: OptimizeReq):
    if req.strategy not in REGISTRY:
        raise HTTPException(404, f"unknown strategy {req.strategy}")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=req.days)
    df = await load_candles("B-BTC_USDT", req.timeframe, start, end)
    if df.empty:
        raise HTTPException(400, "no data in DB; run /data/download first")
    if req.walk_forward:
        results = walk_forward(req.strategy, df, req.grid, req.n_splits, req.score_key)
        return {"results": [{"params": r.params, "score": r.score, "metrics": _safe(r.metrics)} for r in results]}
    best = optimize_grid(req.strategy, df, req.grid, req.score_key)
    return {"best_params": best.params, "best_score": best.score, "metrics": _safe(best.metrics)}


@router.get("/trades")
async def list_trades(limit: int = 100):
    async with session_scope() as s:
        res = await s.execute(select(Trade).order_by(Trade.entry_ts.desc()).limit(limit))
        rows = res.scalars().all()
    return [{
        "symbol": r.symbol, "strategy": r.strategy, "side": r.side,
        "entry_ts": r.entry_ts.isoformat(), "exit_ts": r.exit_ts.isoformat() if r.exit_ts else None,
        "entry_price": float(r.entry_price), "exit_price": float(r.exit_price) if r.exit_price else None,
        "quantity": float(r.quantity), "leverage": r.leverage,
        "pnl": float(r.pnl), "fees": float(r.fees) if r.fees is not None else 0.0,
        "exit_reason": r.exit_reason, "source": r.source,
    } for r in rows]


@router.get("/signals")
async def list_signals(limit: int = 50):
    async with session_scope() as s:
        res = await s.execute(select(Signal).order_by(Signal.ts.desc()).limit(limit))
        rows = res.scalars().all()
    return [{"ts": r.ts.isoformat(), "symbol": r.symbol, "strategy": r.strategy,
             "side": r.side, "price": float(r.price), "reason": r.reason} for r in rows]


@router.get("/positions")
async def positions():
    """Live positions from exchange (live mode) or engine state (paper/test)."""
    from app.config import settings as s_
    from app.main import _live_engine
    if s_.trading_mode == "live" and s_.coindcx_api_key:
        async with CoinDCXClient() as c:
            return await c.get_positions("B-BTC_USDT")
    # paper/test: expose the engine's simulated position so the UI can show it
    if _live_engine is not None and _live_engine.pos is not None:
        p = _live_engine.pos
        return {"positions": [{
            "pair": _live_engine.symbol, "position_size": p.qty,
            "avg_entry_price": p.entry_price, "leverage": p.leverage,
            "stop_loss": p.stop, "side": p.side,
            "unrealised_pnl": 0.0,  # ponytail: mark-to-market needs live price; UI shows realized on close
        }], "mode": s_.trading_mode, "note": "paper position from engine state"}
    return {"positions": [], "mode": s_.trading_mode, "note": "no open position"}


@router.get("/balance")
async def balance():
    """Paper/test: simulated engine equity. Live: USDT balance from exchange wallets."""
    from app.config import settings as s_
    if s_.trading_mode == "live" and s_.coindcx_api_key:
        try:
            async with CoinDCXClient() as c:
                wallets = await c.get_wallets()
            return {"mode": "live", "wallets": wallets}
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"wallet fetch failed: {e}")
    from app.main import _live_engine
    equity = _live_engine.risk.state.equity if _live_engine else None
    return {"mode": s_.trading_mode, "equity": equity, "initial_capital": 10000.0}


def _write_env_mode(mode: str) -> None:
    """Persist TRADING_MODE to .env (preserves all other lines). Local dev tool only."""
    from pathlib import Path
    p = Path(".env")
    lines = p.read_text().splitlines() if p.exists() else []
    out, found = [], False
    for ln in lines:
        if ln.startswith("TRADING_MODE="):
            out.append(f"TRADING_MODE={mode}")
            found = True
        else:
            out.append(ln)
    if not found:
        out.append(f"TRADING_MODE={mode}")
    p.write_text("\n".join(out) + "\n")


@router.post("/mode")
async def set_mode(req: ModeReq):
    """Switch trading mode. Paper/test flips in-memory + .env. Live requires
    confirm=true and real API keys; drops any simulated paper position and
    reconciles against the exchange. LIVE MODE PLACES REAL MONEY ORDERS."""
    from app.config import settings as s_
    allowed = {"test", "paper", "live"}
    if req.mode not in allowed:
        raise HTTPException(400, f"mode must be one of {allowed}")
    if req.mode == "live":
        if not (s_.coindcx_api_key and s_.coindcx_api_secret):
            raise HTTPException(400, "live mode requires COINDCX_API_KEY/SECRET in .env")
        if not req.confirm:
            raise HTTPException(409, "live mode requires confirm=true (real money at risk)")
    _write_env_mode(req.mode)
    s_.trading_mode = req.mode
    from app.main import _live_engine
    if _live_engine is not None:
        # Only live places real orders; test/paper stay simulated (never real money
        # unless explicitly live). test is meant as a startup-only API+data mode.
        _live_engine.paper = req.mode != "live"
        if req.mode == "live":
            _live_engine.pos = None  # discard simulated paper position before reconcile
            await _live_engine.reconcile()
    return {
        "mode": s_.trading_mode,
        "paper": _live_engine.paper if _live_engine else None,
        "warning": "LIVE: real orders will be placed on CoinDCX" if req.mode == "live" else "",
    }


@router.post("/kill")
async def kill_switch(req: KillReq):
    """Engage (on=true) or release (on=false) the risk kill switch. When engaged,
    the engine halts all new entries; existing position is NOT auto-closed."""
    from app.main import _live_engine
    if _live_engine is None:
        raise HTTPException(409, "no engine running")
    _live_engine.risk.kill_switch(req.on)
    return {"kill": req.on, "equity": _live_engine.risk.state.equity}


@router.post("/trade")
async def manual_trade(req: TradeReq):
    """UI-triggered manual trade. action=buy|sell|close; optional leverage,
    take_profit, stop_loss, margin (INR → qty), or explicit qty. Live places
    REAL orders on CoinDCX."""
    from app.main import _live_engine
    if _live_engine is None:
        raise HTTPException(409, "no engine running (test mode)")
    try:
        return await _live_engine.manual_trade(
            req.action, leverage=req.leverage, take_profit=req.take_profit,
            stop_loss=req.stop_loss, margin=req.margin, qty=req.qty)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"trade failed: {e}")


@router.get("/engine")
async def engine_status():
    """Engine control state for the UI: auto-trade on/off, active strategy, kill."""
    from app.main import _live_engine
    if _live_engine is None:
        return {"running": False}
    return {
        "running": True,
        "auto": _live_engine.auto_trade,
        "strategy": _live_engine.strategy.meta.name,
        "kill": _live_engine.risk.state.kill,
        "paper": _live_engine.paper,
        "has_position": _live_engine.pos is not None,
    }


@router.get("/quote")
async def quote():
    """Live price, FX, instrument min constraints, and equity — everything the
    manual-trade UI needs to autofill the minimum tradeable size and show risk."""
    from app.config import settings as s_
    from app.main import _live_engine
    async with CoinDCXClient() as c:
        try:
            price = await c.get_last_price("B-BTC_USDT")
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"price fetch failed: {e}")
        fx = 1.0
        if s_.margin_currency == "INR":
            try:
                fx = await c.get_usdt_inr()
            except Exception:  # noqa: BLE001
                pass
        try:
            inst = await c.get_instrument("B-BTC_USDT", s_.margin_currency)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"instrument fetch failed: {e}")
    equity = _live_engine.risk.state.equity if _live_engine else None
    return {
        "symbol": s_.symbol,
        "margin_currency": s_.margin_currency,
        "price": price,
        "fx": fx,
        "equity": equity,
        "taker_fee": s_.taker_fee,
        "maker_fee": s_.maker_fee,
        "slippage_bps": s_.slippage_bps,
        "min_quantity": float(inst.get("min_quantity", 0)),
        "quantity_increment": float(inst.get("quantity_increment", 0.001)),
        "min_notional": float(inst.get("min_notional", 0)),
        "price_increment": float(inst.get("price_increment", 0.1)),
    }


@router.post("/auto")
async def set_auto(req: AutoReq):
    """Start (on=true) / stop (on=false) automated signal-driven trading.
    Stop = manual-only: engine skips signal open/close; manual trades still work."""
    from app.main import _live_engine
    if _live_engine is None:
        raise HTTPException(409, "no engine running")
    _live_engine.auto_trade = req.on
    return {"auto": req.on, "strategy": _live_engine.strategy.meta.name}


@router.post("/strategy")
async def set_strategy(req: StrategyReq):
    """Switch the active strategy used by the auto-trader."""
    from app.main import _live_engine
    if _live_engine is None:
        raise HTTPException(409, "no engine running")
    try:
        _live_engine.set_strategy(req.name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"strategy": _live_engine.strategy.meta.name, "warmup": _live_engine.strategy.warmup}


def _safe(m: dict) -> dict:
    """Make JSON-serializable (inf -> string)."""
    out = {}
    for k, v in m.items():
        if isinstance(v, float) and v == float("inf"):
            out[k] = "inf"
        elif isinstance(v, (pd.Timestamp, datetime)):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out