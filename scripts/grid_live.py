"""Live paper runner for the spot grid bot (#1). Streams live CoinDCX price ticks
(WS) and steps the SAME GridBot used by the backtest (no backtest/live divergence),
logging fills + equity. This is the forward validation: does tick-by-tick live
equity match the 15m-close-simmed equity from §14?

Paper by construction (GridBot simulates fills, places no real orders). To go to
real paper orders later, wrap GridBot.step's fills in the REST order client.

WS is primary; if the feed is unavailable (HTTP 503 / handshake timeouts seen at
build time), falls back to polling the latest 1m candle every 60s and stepping
its close — coarser but still live-forward data.

Usage: python scripts/grid_live.py [B-BTC_USDT] [RUN_S] [g] [K]
  RUN_S default 600 (10 min). g default 0.02, K default 20.
Logs -> reports/grid_live.jsonl ; final summary -> reports/grid_live_summary.json
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import websockets

from app.config import settings
from app.data.downloader import download_ohlcv
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from grid_bot import FEE, GridBot  # noqa: E402

PAIR = "B-BTC_USDT"
PRICE_CHAN = "{pair}@prices-futures"


def parse_price(msg: dict) -> float | None:
    for k in ("price", "p", "last_price", "lastPrice", "trade_price"):
        v = msg.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    for key in ("data", "trades", "trade"):
        d = msg.get(key)
        if isinstance(d, dict):
            return parse_price(d)
        if isinstance(d, list) and d:
            return parse_price(d[0])
    return None


async def run_ws(bot: GridBot, pair: str, run_s: int, log) -> int:
    chan = PRICE_CHAN.format(pair=pair)
    deadline = time.time() + run_s
    n_ticks = 0
    async with websockets.connect(settings.ws_url, ping_interval=20, ping_timeout=20) as ws:
        await ws.send(json.dumps({"method": "subscribe", "channels": [chan]}))
        log(f"ws subscribed {chan}")
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(deadline - time.time(), 1))
            except asyncio.TimeoutError:
                break
            p = parse_price(json.loads(raw))
            if p is None:
                continue
            n_ticks += 1
            eq, fills = bot.step(p)
            for f in fills:
                log(f"fill {f['side']} @{f.get('entry', f.get('exit')):.2f} eq={eq:.1f}")
            if n_ticks % 100 == 0:
                log(f"tick {n_ticks} px={p:.2f} eq={eq:.1f} open={len(bot.open_buys)} anchor={bot.anchor:.2f}")
    return n_ticks


async def run_poll(bot: GridBot, pair: str, run_s: int, log) -> int:
    """Fallback: poll latest 1m candle close every 60s and step it."""
    from app.data.downloader import load_candles
    log("WS unavailable -> candle-poll fallback (60s cadence)")
    seen = 0
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
                for f in fills:
                    log(f"fill {f['side']} @{f.get('entry', f.get('exit')):.2f} eq={eq:.1f}")
                log(f"poll {n} px={c:.2f} eq={eq:.1f} open={len(bot.open_buys)} anchor={bot.anchor:.2f}")
        await asyncio.sleep(60)
    return n


def main(pair=PAIR, run_s=600, g=0.02, K=20):
    lines = []
    def log(msg):
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        line = f"{ts} {msg}"
        print(line, flush=True)
        lines.append(line)
    bot = GridBot(g, K, FEE, capital=10000.0)
    log(f"grid_live start pair={pair} g={g} K={K} fee={FEE} run={run_s}s")

    async def go():
        for attempt in range(3):
            try:
                n = await run_ws(bot, pair, run_s, log)
                if n > 0:
                    return n
            except Exception as e:  # noqa: BLE001
                log(f"ws attempt {attempt} failed: {str(e)[:60]}")
                await asyncio.sleep(2)
        log("ws feed unavailable after retries -> fallback")
        return await run_poll(bot, pair, run_s, log)

    n = asyncio.run(go())
    eq = bot.equity
    pnl = eq - 10000.0
    log(f"done: {n} samples | final equity {eq:.2f} | pnl {pnl:+.2f} | "
        f"open_buys {len(bot.open_buys)} | anchor {bot.anchor}")
    open("reports/grid_live.jsonl", "w").write("\n".join(lines) + "\n")
    json.dump({"pair": pair, "g": g, "K": K, "samples": n, "final_equity": round(eq, 2),
                "pnl": round(pnl, 2), "open_buys": len(bot.open_buys)},
              open("reports/grid_live_summary.json", "w"), indent=2)
    print("-> reports/grid_live.jsonl + grid_live_summary.json")


if __name__ == "__main__":
    pair = sys.argv[1] if len(sys.argv) > 1 else PAIR
    run_s = int(sys.argv[2]) if len(sys.argv) > 2 else 600
    g = float(sys.argv[3]) if len(sys.argv) > 3 else 0.02
    K = int(sys.argv[4]) if len(sys.argv) > 4 else 20
    main(pair, run_s, g, K)