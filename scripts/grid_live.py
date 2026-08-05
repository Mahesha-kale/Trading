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

import pandas as pd

from app.config import settings
from app.data.downloader import download_ohlcv
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from grid_bot import FEE, GridBot  # noqa: E402

PAIR = "B-BTC_USDT"
PRICE_CHAN = "{pair}@prices"          # spot LTP channel (price-change event)
SERIES_PATH = "reports/grid_live_series.jsonl"


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


def main(pair=PAIR, run_s=3600, g=0.02, K=20):
    lines = []
    series = []
    def log(msg):
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        line = f"{ts} {msg}"
        print(line, flush=True)
        lines.append(line)
    def ser(ts, px, eq):
        series.append({"ts": ts.isoformat(timespec="seconds"), "px": round(px, 2), "eq": round(eq, 2)})
    bot = GridBot(g, K, FEE, capital=10000.0)
    log(f"grid_live start pair={pair} g={g} K={K} fee={FEE} run={run_s}s")

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
    log(f"done: {n} samples | final equity {eq:.2f} | pnl {pnl:+.2f} | "
        f"open_buys {len(bot.open_buys)} | anchor {bot.anchor}")
    open("reports/grid_live.jsonl", "w").write("\n".join(lines) + "\n")
    with open(SERIES_PATH, "w") as f:
        for s in series:
            f.write(json.dumps(s) + "\n")
    json.dump({"pair": pair, "g": g, "K": K, "samples": n, "final_equity": round(eq, 2),
                "pnl": round(pnl, 2), "open_buys": len(bot.open_buys),
                "series_path": SERIES_PATH, "series_n": len(series)},
              open("reports/grid_live_summary.json", "w"), indent=2)
    print("-> reports/grid_live.jsonl + grid_live_series.jsonl + grid_live_summary.json")


if __name__ == "__main__":
    pair = sys.argv[1] if len(sys.argv) > 1 else PAIR
    run_s = int(sys.argv[2]) if len(sys.argv) > 2 else 3600
    g = float(sys.argv[3]) if len(sys.argv) > 3 else 0.02
    K = int(sys.argv[4]) if len(sys.argv) > 4 else 20
    main(pair, run_s, g, K)