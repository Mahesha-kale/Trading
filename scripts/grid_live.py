"""Live paper runner for the spot grid bot (#1). Streams live CoinDCX spot price
via Socket.IO and steps the SAME GridBot used by the backtest (no backtest/live
divergence), logging fills + equity + an equity-time series.

Paper by construction (GridBot simulates fills, places no real orders).

CoinDCX public stream is Socket.IO v2.4.0 (wss://stream.coindcx.com), NOT raw
WebSocket — a raw `websockets` client 503s on the Engine.IO handshake. Spot LTP
channel is `{pair}@prices` emitting `price-change` events with field `p` = trade
price. (Earlier code used `@prices-futures` on a spot pair -> 503.)

If the feed is unavailable after retries, falls back to polling the latest 1m
candle every 60s (coarser, still live-forward).

Logs -> reports/grid_live.jsonl (human lines)
       reports/grid_live_series.jsonl (ts, px, eq, open — for divergence replay)
Summary -> reports/grid_live_summary.json
Then: python scripts/grid_live_replay.py  (compare live vs backtest on same path)

Usage: python scripts/grid_live.py [B-BTC_USDT] [RUN_S] [g] [K]
  RUN_S default 3600 (1h). g default 0.02, K default 20.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.config import settings
from app.data.downloader import download_ohlcv
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from grid_bot import FEE, TDS, GridBot  # noqa: E402

PAIR = "B-BTC_USDT"
PRICE_CHAN = "{pair}@prices"          # spot LTP channel (price-change event)
LOG_PATH = Path("reports/grid_live.jsonl")
SERIES_PATH = Path("reports/grid_live_series.jsonl")
SUMMARY_PATH = Path("reports/grid_live_summary.json")
GRID_BOT_JSON = Path("reports/grid_bot.json")  # deployed grid lives here (scripts/grid_bot.py)


def deployed_grid(default_g=0.008, default_K=10) -> tuple[float, int]:
    """Live follows the backtest's deployed grid so tuning stays in one place
    (scripts/grid_bot.py). CLI args still override."""
    if GRID_BOT_JSON.exists():
        try:
            j = json.loads(GRID_BOT_JSON.read_text())
            d = j.get("deployed") or {}
            if d.get("g") and d.get("K"):
                return float(d["g"]), int(d["K"])
        except (json.JSONDecodeError, KeyError):
            pass
    return default_g, default_K


def is_deployable() -> bool:
    """True only if grid_bot.json marks the edge as holding on current OOS.
    A no-edge backtest means a paper run is divergence validation only, not an
    expected-edge strategy."""
    if not GRID_BOT_JSON.exists():
        return True  # no backtest yet — can't refute, let it run
    try:
        return bool(json.loads(GRID_BOT_JSON.read_text()).get("deployable", True))
    except (json.JSONDecodeError, OSError):
        return True


def resume_from_series(bot: GridBot) -> int:
    """Rebuild bot state by replaying the recorded series through a fresh GridBot.
    The series is the single source of truth -> no checkpoint file to drift from,
    no GridBot serialization. O(n) per restart, trivial for overnight runs."""
    if not SERIES_PATH.exists() or SERIES_PATH.stat().st_size == 0:
        return 0
    rows = [json.loads(l) for l in SERIES_PATH.read_text().splitlines() if l.strip()]
    for r in rows:
        bot.step(r["px"])
    return len(rows)


def parse_price(payload) -> float | None:
    """price-change payload arrives as {"event":"price-change","data":"<json str>"}.
    The inner data string holds {"T":..., "p":"...", "pr":"spot"}."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            return None
    if isinstance(payload, dict):
        for k in ("p", "price", "last_price", "lastPrice", "trade_price"):
            v = payload.get(k)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
        for key in ("data", "trades", "trade"):
            d = payload.get(key)
            if d is not None:
                p = parse_price(d)
                if p is not None:
                    return p
    elif isinstance(payload, list) and payload:
        return parse_price(payload[0])
    return None


async def run_sio(bot: GridBot, pair: str, run_s: int, log, ser) -> int:
    """Socket.IO primary: subscribe to {pair}@prices, step on each price-change."""
    import socketio  # noqa: PLC0415

    chan = PRICE_CHAN.format(pair=pair)
    deadline = time.time() + run_s
    n_ticks = 0
    done = asyncio.Event()

    sio = socketio.AsyncClient()

    @sio.on("price-change")
    async def on_price(payload):
        nonlocal n_ticks
        if time.time() > deadline:
            done.set(); return
        p = parse_price(payload)
        if p is None:
            return
        n_ticks += 1
        eq, fills = bot.step(p)
        ser(datetime.now(timezone.utc), p, eq)
        for f in fills:
            log(f"fill {f['side']} @{f.get('entry', f.get('exit')):.2f} eq={eq:.1f}")
        if n_ticks % 100 == 0:
            log(f"tick {n_ticks} px={p:.2f} eq={eq:.1f} open={len(bot.open_buys)} anchor={bot.anchor:.2f}")

    @sio.event
    async def connect():
        await sio.emit("join", {"channelName": chan})
        log(f"sio joined {chan}")

    try:
        await sio.connect(settings.ws_url, transports=["websocket"],
                          socketio_path="/socket.io", wait_timeout=20)
    except Exception as e:  # noqa: BLE001
        log(f"sio connect failed: {str(e)[:80]}")
        return 0
    try:
        await asyncio.wait_for(done.wait(), timeout=max(deadline - time.time(), 0.1))
    except asyncio.TimeoutError:
        pass
    finally:
        await sio.disconnect()
    return n_ticks


async def run_poll(bot: GridBot, pair: str, run_s: int, log, ser) -> int:
    """Fallback: poll latest 1m candle close every 60s and step it."""
    from app.data.downloader import load_candles  # noqa: PLC0415
    log("WS unavailable -> candle-poll fallback (60s cadence)")
    seen = 0.0
    n = 0
    deadline = time.time() + run_s
    while time.time() < deadline:
        now = datetime.now(timezone.utc)
        await download_ohlcv(pair, "1m", now - pd.Timedelta(minutes=5), now)
        df = await load_candles(pair, "1m", now - pd.Timedelta(minutes=5), now)
        if df is not None and len(df):
            c = float(df["close"].iloc[-1])
            if c != seen:
                eq, fills = bot.step(c)
                seen = c
                n += 1
                ser(datetime.now(timezone.utc), c, eq)
                for f in fills:
                    log(f"fill {f['side']} @{f.get('entry', f.get('exit')):.2f} eq={eq:.1f}")
                log(f"poll {n} px={c:.2f} eq={eq:.1f} open={len(bot.open_buys)} anchor={bot.anchor:.2f}")
        await asyncio.sleep(60)
    return n


def main(pair=PAIR, run_s=3600, g=None, K=None):
    dg, dK = deployed_grid()
    if g is None:
        g = dg
    if K is None:
        K = dK
    LOG_PATH.parent.mkdir(exist_ok=True)
    # config-change guard: a series recorded under a different g/K can't be
    # safely resumed (replay would step the wrong grid) -> truncate and start
    # fresh. Mixing grids in one series would poison the divergence replay.
    if SUMMARY_PATH.exists():
        try:
            s = json.loads(SUMMARY_PATH.read_text())
            # g/K AND the fee/tds model define the grid; a series recorded under
            # a different cost model can't be safely resumed (replay would step
            # the wrong grid) -> truncate and start fresh. Strict == : a missing
            # fee/tds means an older cost model -> truncate.
            changed = (s.get("g") != g or s.get("K") != K
                       or s.get("fee") != FEE or s.get("tds") != TDS)
            if changed:
                print(f"config changed (was g={s.get('g')} K={s.get('K')} fee={s.get('fee')} "
                      f"tds={s.get('tds')}) -> truncating series+log, fresh start", flush=True)
                LOG_PATH.write_text("")
                SERIES_PATH.write_text("")
        except (json.JSONDecodeError, OSError):
            pass
    log_f = open(LOG_PATH, "a", encoding="utf-8")
    ser_f = open(SERIES_PATH, "a", encoding="utf-8")
    n_series = 0

    def log(msg):
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        line = f"{ts} {msg}"
        print(line, flush=True)
        log_f.write(line + "\n"); log_f.flush()

    def ser(ts, px, eq):
        nonlocal n_series
        ser_f.write(json.dumps({"ts": ts.isoformat(timespec="seconds"),
                                "px": round(px, 2), "eq": round(eq, 2)}) + "\n")
        ser_f.flush()
        n_series += 1

    bot = GridBot(g, K, FEE, capital=10000.0, tds=TDS)
    resumed = resume_from_series(bot)
    if not is_deployable():
        log("WARNING: grid_bot.json marks the edge as refuted on current OOS — "
            "running PAPER for divergence validation only, NOT an expected-edge strategy")
    log(f"grid_live start pair={pair} g={g} K={K} fee={FEE} tds={TDS} run={run_s}s"
        + (f" (resumed from {resumed} ticks)" if resumed else ""))

    async def go():
        for attempt in range(3):
            try:
                n = await run_sio(bot, pair, run_s, log, ser)
                if n > 0:
                    return n
            except Exception as e:  # noqa: BLE001
                log(f"sio attempt {attempt} failed: {str(e)[:60]}")
                await asyncio.sleep(2)
        log("sio feed unavailable after retries -> fallback")
        return await run_poll(bot, pair, run_s, log, ser)

    n = asyncio.run(go())
    eq = bot.equity
    pnl = eq - 10000.0
    total_series = resumed + n_series
    log(f"done: {n} samples | final equity {eq:.2f} | pnl {pnl:+.2f} | "
        f"open_buys {len(bot.open_buys)} | anchor {bot.anchor} | "
        f"series {total_series} ticks")
    json.dump({"pair": pair, "g": g, "K": K, "fee": FEE, "tds": TDS,
                "samples": total_series,
                "final_equity": round(eq, 2), "pnl": round(pnl, 2),
                "open_buys": len(bot.open_buys), "resumed": resumed,
                "series_path": str(SERIES_PATH), "series_n": total_series},
              open(SUMMARY_PATH, "w"), indent=2)
    log_f.close(); ser_f.close()
    print("-> reports/grid_live.jsonl + grid_live_series.jsonl + grid_live_summary.json")


if __name__ == "__main__":
    pair = sys.argv[1] if len(sys.argv) > 1 else PAIR
    run_s = int(sys.argv[2]) if len(sys.argv) > 2 else 3600
    g = float(sys.argv[3]) if len(sys.argv) > 3 else None
    K = int(sys.argv[4]) if len(sys.argv) > 4 else None
    main(pair, run_s, g, K)