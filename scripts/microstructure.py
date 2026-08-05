"""Microstructure signal from the live WS price feed (tick-rule CVD proxy).

CoinDCX exposes no public per-trade print feed (REST or WS) — only candles,
ticker, and a price-change WS channel. True CVD needs trade prints + size, which
we don't have. So this uses the classic Lee-Ready TICK RULE: classify each price
tick as a buy (uptick) or sell (downtick), repeat last on no-change, and
accumulate Cumulative Volume Delta over a rolling window. It is a *proxy* for
order-flow imbalance inferred from price alone (no trade volume), standard in
microstructure when trade-side data is unavailable.

This is a live-forward signal collector, NOT backtestable (no tick history). It
proves the feed + signal pipeline runs; validating its edge needs weeks of
recorded ticks + a separate forward test.

Runs ~RUN_S seconds, prints rolling CVD + imbalance every PRINT_EVERY ticks.
Usage: python scripts/microstructure.py [B-BTC_USDT] [RUN_S]
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import deque

import websockets

from app.config import settings

PAIR = "B-BTC_USDT"
RUN_S = 40
PRINT_EVERY = 50
WINDOW = 200  # ticks in rolling CVD/imbalance window


def parse_price(msg: dict) -> float | None:
    """Extract a price from a prices-futures message. Defensively try common
    fields since the exact payload shape is undocumented in our client."""
    for k in ("price", "p", "last_price", "lastPrice", "trade_price"):
        v = msg.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    # nested under 'data' or 'trades'
    for key in ("data", "trades", "trade"):
        d = msg.get(key)
        if isinstance(d, dict):
            return parse_price(d)
        if isinstance(d, list) and d:
            return parse_price(d[0])
    return None


async def main(pair=PAIR, run_s=RUN_S):
    ticks = deque(maxlen=WINDOW)  # +1 buy-uptick, -1 sell-downtick
    last = None
    cvd = 0.0
    n = 0
    chan = f"{pair}@prices-futures"
    print(f"connecting {settings.ws_url} channel={chan} (run {run_s}s)", flush=True)
    async with websockets.connect(settings.ws_url, ping_interval=20, ping_timeout=20) as ws:
        await ws.send(json.dumps({"method": "subscribe", "channels": [chan]}))
        deadline = time.time() + run_s
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=run_s)
            except asyncio.TimeoutError:
                break
            msg = json.loads(raw)
            p = parse_price(msg)
            if p is None:
                continue
            # Lee-Ready tick rule
            if last is None:
                side = 0
            elif p > last:
                side = 1
            elif p < last:
                side = -1
            else:
                side = 0
            last = p
            n += 1
            cvd += side
            ticks.append(side)
            if n % PRINT_EVERY == 0:
                imb = sum(ticks) / max(len(ticks), 1)  # imbalance in [-1,1]
                print(f"  t={n:5} px={p:.2f} cvd={cvd:+.0f} "
                      f"win_cvd={sum(ticks):+d} imbalance={imb:+.2f} "
                      f"(buys={sum(1 for t in ticks if t>0)} "
                      f"sells={sum(1 for t in ticks if t<0)})", flush=True)
    print(f"\ncollected {n} price ticks in {run_s}s ({n/run_s:.1f}/s)")
    print(f"final CVD={cvd:+.0f} window imbalance={sum(ticks)/max(len(ticks),1):+.2f}")
    if n == 0:
        print("WARN: no price ticks parsed — prices-futures payload shape may differ; "
              "inspect a raw message to adjust parse_price()")
    else:
        print("pipeline OK: feed + tick rule + CVD running. "
              "edge validation needs recorded-tick forward test (not backtestable).")


if __name__ == "__main__":
    pair = sys.argv[1] if len(sys.argv) > 1 else PAIR
    run_s = int(sys.argv[2]) if len(sys.argv) > 2 else RUN_S
    asyncio.run(main(pair, run_s))