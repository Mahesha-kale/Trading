"""Microstructure: real trade-side CVD from the CoinDCX Socket.IO feed.

FIX (2026-08-08): the §15 "503 feed-blocked" was a CODE bug, not infra. CoinDCX
streams are Socket.IO v2.4.0 (Engine.IO v3) — a raw `websockets` connect to the
bare host returns 503 (no Engine.IO handshake on that path). Connect to
`/socket.io/?EIO=3&transport=websocket`, do the SIO handshake, `join` the pair,
and `new-trade` events arrive with REAL trade side:

    42["new-trade",{"event":"new-trade","data":"{\"T\":ms,\"p\":price,\"q\":qty,
                                                    \"m\":isBuyerMaker,...}"}]

`m` (isBuyerMaker) gives the TRUE aggressor side: m=false -> buyer is taker -> BUY;
m=true -> seller is taker -> SELL. So CVD = sum(+q buy, -q sell) from real order
flow, NOT the §15 Lee-Ready price proxy. Also get depth-update / depth-snapshot.

Live-forward: NOT backtestable (no tick history). This records trades to disk
for a later forward-test of CVD as a short-horizon signal. Per the plan: record
>=1 week, then forward-test. This script is the recorder; run it long (no RUN_S
arg = until Ctrl-C) to accumulate ticks.

Usage: python scripts/microstructure.py [B-BTC_USDT] [RUN_S]
       RUN_S omitted -> run until interrupted (recording mode)
"""
from __future__ import annotations

import asyncio
import csv
import json
import sys
import time
from collections import deque
from pathlib import Path

import websockets
from app.config import settings

PAIR = "B-BTC_USDT"
WINDOW = 200          # ticks in rolling CVD/imbalance window
PRINT_EVERY = 200     # status line every N trades
SIO_PATH = "/socket.io/?EIO=3&transport=websocket"


def sio_url() -> str:
    base = settings.ws_url.rstrip("/")
    if not base.startswith("ws"):
        base = base.replace("http", "ws", 1)
    return f"{base}{SIO_PATH}"


def parse_sio(raw: str):
    """Decode a Socket.IO v2 (EIO=3) frame. Returns (event, payload) or None.
    42[event, payload] -> the event tuple. Handles 0 open / 2 ping / 40 connect."""
    if not raw or raw[0] != "4":
        return None
    sub = raw[1]
    if sub == "0":       # Engine.IO OPEN handled by caller; ignore here
        return None
    if sub == "2":       # server ping
        return ("__ping__", None)
    if sub == "1" or sub == "3":
        return None
    if sub == "2" or sub == "3":
        return None
    if raw[:2] == "40":  # connect ack
        return ("__connect__", None)
    if raw[:2] == "42":  # event
        try:
            arr = json.loads(raw[2:])
            return (arr[0], arr[1] if len(arr) > 1 else None)
        except (json.JSONDecodeError, IndexError):
            return None
    return None


def parse_trade(payload) -> dict | None:
    """new-trade payload: {event, data} where data is a JSON STRING."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    return data


def side_from_trade(t: dict) -> int:
    # m == true -> buyer is maker -> aggressor SOLD -> -1. m == false -> +1.
    return -1 if t.get("m") else 1


async def main(pair=PAIR, run_s=None):
    url = sio_url()
    out = Path(f"reports/ticks_{pair.replace('-','_').replace('@','_')}.csv")
    new_file = not out.exists()
    f = open(out, "a", newline="", buffering=1)  # line-buffered, append
    w = csv.writer(f)
    if new_file:
        w.writerow(["ts_ms", "price", "qty", "side", "symbol"])
    ticks = deque(maxlen=WINDOW)
    cvd = 0.0
    n = 0
    start = time.time()
    deadline = (start + run_s) if run_s else None
    print(f"recording {pair} -> {out} (run {'until-interrupt' if run_s is None else f'{run_s}s'})", flush=True)
    # Reconnect loop: the server drops connections intermittently (clean 1005,
    # ~per-IP limits / restarts). A multi-day recorder must rejoin and continue.
    while True:
        if deadline and time.time() > deadline:
            break
        try:
            async with websockets.connect(url, ping_interval=None) as ws:
                await asyncio.wait_for(ws.recv(), timeout=10)   # 0 Engine.IO open
                # CoinDCX server sends '40' (SIO connect) spontaneously — do NOT
                # send our own '40' (a duplicate connect makes it drop us on join).
                await asyncio.wait_for(ws.recv(), timeout=10)   # 40 server connect
                await ws.send('42' + json.dumps(["join", {"channelName": pair}]))
                last_ping = time.time()
                print(f"  connected+joined (total recorded so far: {n})", flush=True)
                while True:
                    if deadline and time.time() > deadline:
                        break
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    except asyncio.TimeoutError:
                        if time.time() - last_ping > 20:    # client ping keepalive
                            await ws.send("2"); last_ping = time.time()
                        continue
                    if raw == "2":                          # server ping -> pong
                        await ws.send("3"); continue
                    ev = parse_sio(raw)
                    if not ev:
                        continue
                    event, payload = ev
                    if event == "__ping__":
                        await ws.send("3"); continue
                    if event != "new-trade":
                        continue
                    t = parse_trade(payload)
                    if not t:
                        continue
                    try:
                        ts = int(t["T"]); px = float(t["p"]); q = float(t["q"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    sd = side_from_trade(t)
                    signed = sd * q
                    cvd += signed
                    ticks.append(signed)
                    n += 1
                    w.writerow([ts, px, q, sd, t.get("s", "")])
                    if n % PRINT_EVERY == 0:
                        imb = sum(ticks) / max(len(ticks), 1)
                        print(f"  t={n:6} px={px:.2f} cvd={cvd:+.1f} "
                              f"win_cvd={sum(ticks):+.3f} imbalance={imb:+.3f} "
                              f"(buys={sum(1 for x in ticks if x>0)} "
                              f"sells={sum(1 for x in ticks if x<0)})", flush=True)
        except (websockets.ConnectionClosed, asyncio.TimeoutError, OSError) as e:
            print(f"  drop: {str(e)[:60]} -> reconnect in 2s", flush=True)
            await asyncio.sleep(2)
    f.close()
    imb = sum(ticks) / max(len(ticks), 1)
    print(f"\nrecorded {n} trades -> {out} | final cvd={cvd:+.1f} imbalance={imb:+.3f}")
    print("edge validation: forward-test CVD as a short-horizon signal over the "
          "recorded ticks (not backtestable). Run >=1 week for a usable sample.")


if __name__ == "__main__":
    pair = sys.argv[1] if len(sys.argv) > 1 else PAIR
    run_s = int(sys.argv[2]) if len(sys.argv) > 2 else None
    try:
        asyncio.run(main(pair, run_s))
    except KeyboardInterrupt:
        print("\ninterrupted", flush=True)