"""Live hybrid carry trader (sub-project 1). Paper mode logs; live mode orders via CoinDCXClient.
8h cycle, 60s basis-stop, 25% DD halt, fail-safe flatten+halt. See spec §... (design doc)."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger("carry_trader")
REPORTS = Path("reports")


def decide(rate_history: np.ndarray, band: float, side: int) -> str:
    """side: 0 flat, -1 short, +1 long. Carry harvests positive funding (short when rate>+band)."""
    r = float(rate_history[-1])
    if side == 0:
        return "ENTER_SHORT" if r > band else "HOLD"
    if side == -1:
        return "FLATTEN" if r < -band else "HOLD"
    return "HOLD"  # no long side in one-sided carry


@dataclass
class FeedSample:
    ts: int
    fr: float           # current funding rate
    efr: float          # next funding rate
    basis_bps: float    # perp mark vs synthetic spot
    spot_price: float   # BTCINR spot
    usdtinr: float


@dataclass
class TraderState:
    side: int = 0           # 0 flat, -1 short
    qty: float = 0.0
    entry_perp: float = 0.0
    entry_spot: float = 0.0
    peak_equity: float = 0.0
    band: float = 0.0002
    halted: bool = False
    halted_orphan: bool = False
    last_feed_ts: int = 0


class TiltSignal:
    """Pluggable directional tilt source (sub-project 2). conviction in [0,1]; 0 = no tilt."""
    async def conviction(self, sample: FeedSample, state: TraderState) -> float:
        return 0.0


class NoTilt(TiltSignal):
    pass


async def run_loop(cfg: dict, client=None, feed=None, state_path=None, live=False) -> None:
    """Main loop. cfg: {band, capital, stop_fill_est, risk_fraction, leverage_cap, max_dd, basis_stop_bps, pair, spot_pair}.
    client/feed injectable for tests. live=False = paper (log only)."""
    state_path = state_path or (REPORTS / "carry_trader_state.json")
    state = _load_state(state_path)
    halt_file = REPORTS / "carry_trader.HALT"
    log.info("carry_trader start live=%s band=%s", live, state.band)
    if live and client is not None:
        await reconcile(state, client, cfg["pair"])
        if state.halted:
            _save_state(state_path, state); return
    while not state.halted:
        if halt_file.exists():
            await _flatten_all(state, client, live, cfg)
            state.halted = True; _save_state(state_path, state)
            log.warning("HALT file -> flatten + halt"); break
        s = await feed()  # FeedSample or None
        if s is None:
            state = await _on_feed_outage(state, client, live, cfg)
            _save_state(state_path, state); continue
        state.last_feed_ts = s.ts
        # basis-stop (60s): force flatten on squeeze spike
        if state.side != 0 and s.basis_bps > cfg["basis_stop_bps"]:
            log.warning("basis-stop fire basis=%sbps -> flatten", s.basis_bps)
            await _flatten_all(state, client, live, cfg); continue
        # DD halt
        eq = _mark_equity(state, s)
        state.peak_equity = max(state.peak_equity, eq)
        from scripts.risk_budget import max_dd_halt
        if max_dd_halt(eq, state.peak_equity, cfg["max_dd"]):
            log.warning("DD halt eq=%.0f peak=%.0f -> flatten+halt", eq, state.peak_equity)
            await _flatten_all(state, client, live, cfg); state.halted = True
            _save_state(state_path, state); break
        # signal
        action = decide(np.array([s.fr]), state.band, state.side)
        if action == "ENTER_SHORT":
            await _enter_short(state, s, client, live, cfg)
        elif action == "FLATTEN":
            await _flatten_all(state, client, live, cfg)
        # tilt: pluggable directional overlay (sub-project 2 supplies real impl)
        tilt = cfg.get("tilt") or NoTilt()
        c = await tilt.conviction(s, state)
        if c > 0 and state.side == 0:  # only tilt when flat (no stacking on carry)
            from scripts.risk_budget import tilt_size
            tqty = tilt_size(cfg["capital"], c, cfg["risk_fraction"], cfg["leverage_cap"]) / s.spot_price
            log.info("TILT conviction=%.2f qty=%s (stub: no order in paper)", c, tqty)
            if live and client is not None:
                # sub-project 2+3 supplies sign + overlay
                pass
        _save_state(state_path, state)
        await asyncio.sleep(cfg.get("poll_s", 60))


def _load_state(path) -> TraderState:
    p = Path(path)
    if p.exists():
        try:
            d = json.loads(p.read_text())
            return TraderState(**d)
        except (json.JSONDecodeError, TypeError, ValueError):
            log.warning("state file corrupt/empty -> fresh state"); return TraderState()
    return TraderState()


def _save_state(path, st: TraderState) -> None:
    Path(path).write_text(json.dumps(st.__dict__, indent=2))


def _mark_equity(st: TraderState, s: FeedSample) -> float:
    # delta-neutral: perp PnL + spot PnL cancel on price; income = funding accrued (proxy via fr*qty)
    if st.side == 0: return st.peak_equity
    # ponytail: placeholder equity (peak + funding proxy); real MTM deferred to Phase 2 live
    funding = st.qty * s.fr * st.entry_spot
    return st.peak_equity + funding


async def _enter_short(st, s, client, live, cfg):
    if live and client is not None:
        from scripts.risk_budget import position_size
        qty = position_size(cfg["capital"], cfg["stop_fill_est"], cfg["risk_fraction"], cfg["leverage_cap"]) / s.spot_price
        try:
            await client.create_order({"side":"sell","pair":cfg["pair"],"order_type":"market_order","total_quantity":qty,"leverage":cfg["leverage_cap"],"position_margin_type":"isolated"})
            # ponytail: confirm fill via get_positions() in Task 6; here assume market fills
            await client.create_spot_order(side="buy", pair=cfg["spot_pair"], order_type="market_order", quantity=qty)
        except Exception as e:  # noqa: BLE001 - fault boundary: any leg failure must orphan-guard
            log.error("orphan leg: %s -> exit perp + halt", e)
            try:
                poss = await client.get_positions(pair=cfg["pair"])
                op = [p for p in poss if abs(float(p.get("position_size", 0) or 0)) > 0]
                if op:
                    await client.exit_position(str(op[0]["id"]))
            except Exception:  # noqa: BLE001, S110 - already halting; cleanup failure is secondary
                pass
            # carry-forward fix: orphan leg must HALT the loop (SPEC error-handling #1), not just flag
            st.halted = True; st.halted_orphan = True; st.side = 0; return
        st.qty = qty
    else:
        st.qty = 0.0
    st.side = -1; st.entry_perp = s.spot_price; st.entry_spot = s.spot_price
    log.info("ENTER_SHORT qty=%s fr=%s", st.qty, s.fr)


async def _flatten_all(st, client, live, cfg):
    if st.side == 0: return
    if live and client is not None and st.qty > 0:
        # Real CoinDCXClient.get_positions() returns normalized dicts with
        # id/position_size/side/pair. exit_position takes a position_id STRING.
        # ponytail: if no open position found, log + skip (don't crash) — exchange
        # may have already flattened via manual intervention or stop-loss.
        try:
            poss = await client.get_positions(pair=cfg["pair"])
        except Exception as e:  # noqa: BLE001 - fault boundary: flatten best-effort
            log.error("flatten: get_positions failed -> skip perp exit: %s", e)
            poss = []
        open_pos = [p for p in poss if abs(float(p.get("position_size", 0) or 0)) > 0]
        if not open_pos:
            log.warning("flatten: no open position for %s -> skip perp exit", cfg["pair"])
        else:
            pos_id = open_pos[0].get("id")
            if pos_id:
                await client.exit_position(str(pos_id))
            else:
                log.warning("flatten: open position has no id -> skip perp exit")
        await client.create_spot_order(side="sell", pair=cfg["spot_pair"],
                                        order_type="market_order", quantity=st.qty)
    st.side = 0; log.info("FLATTEN qty=%s", st.qty); st.qty = 0.0


async def _on_feed_outage(st, client, live, cfg):
    now_ms = int(time.time() * 1000)
    if st.last_feed_ts == 0: st.last_feed_ts = now_ms
    age = now_ms - st.last_feed_ts
    # ponytail: 2 missed polls -> flatten+halt; tune poll_s for longer grace
    if age > 2 * cfg.get("poll_s", 60) * 1000 and st.side != 0:
        log.warning("feed outage %dms -> flatten + halt", age)
        await _flatten_all(st, client, live, cfg)
        st.halted = True
    return st


async def reconcile(st: TraderState, client, pair: str) -> None:
    """Exchange truth wins. If local disagrees or is corrupt and exchange is flat -> halt (don't guess)."""
    try:
        poss = await client.get_positions(pair=pair)
    except Exception as e:  # noqa: BLE001 - fault boundary: can't reach exchange -> halt
        log.error("reconcile: get_positions failed -> halt: %s", e); st.halted = True; return
    open_pos = [p for p in poss if abs(float(p.get("position_size", 0) or 0)) > 0]
    if not open_pos:
        if st.side != 0:
            log.warning("reconcile: local side=%s but exchange flat -> halt (don't guess)", st.side)
            st.halted = True; st.side = 0; st.qty = 0.0
        return
    # exchange has a position -> adopt exchange truth
    p = open_pos[0]
    sz = abs(float(p.get("position_size", 0)))
    st.side = -1 if str(p.get("side", "short")) == "short" else 1
    st.qty = sz
    log.info("reconcile: exchange has %s qty=%s -> adopted", st.side, sz)


def demo() -> None:
    import asyncio

    import numpy as np
    # side 0 (flat), rate > band -> ENTER_SHORT
    assert decide(np.array([0.0003]), band=0.0002, side=0) == "ENTER_SHORT"
    # side 0, rate in deadband -> HOLD
    assert decide(np.array([0.0001]), band=0.0002, side=0) == "HOLD"
    # holding short (side=-1), rate < -band -> FLATTEN
    assert decide(np.array([-0.0003]), band=0.0002, side=-1) == "FLATTEN"
    # holding short, rate in deadband -> HOLD
    assert decide(np.array([0.0001]), band=0.0002, side=-1) == "HOLD"
    print("carry_trader signal OK")
    asyncio.run(_demo_faults())
    asyncio.run(_demo_reconcile())
    asyncio.run(_demo_sign())
    asyncio.run(_demo_tilt())


async def _demo_tilt():
    t = NoTilt()
    assert await t.conviction(FeedSample(0, 0, 0, 0, 0, 0), TraderState()) == 0.0
    print("carry_trader tilt OK")


async def _demo_sign():
    # regression guard on build_order: perp body has the side/leverage we asked for.
    from app.exchange.coindcx import build_order
    perp = build_order(side="sell", pair="B-BTC_USDT", order_type="market_order",
                       quantity=0.01, leverage=3)
    assert perp["side"] == "sell" and perp["leverage"] == 3, perp
    print("carry_trader sign OK")


async def _demo_faults():
    # orphan leg: perp fills, spot rejects -> state back to flat + halted
    class FakeClient:
        def __init__(self): self.calls = []
        async def create_order(self, p): self.calls.append(("perp", p)); return {"status":"ok","orders":[{"id":"1"}]}
        async def create_spot_order(self, **k): self.calls.append(("spot", k)); raise RuntimeError("spot reject")
        async def get_positions(self, pair=None):
            return [{"id": "p1", "pair": "B-BTC_USDT", "position_size": -0.1, "side": "short"}]
        async def exit_position(self, position_id): self.calls.append(("exit", position_id)); return {"status":"ok"}
    fc = FakeClient()
    st = TraderState(side=0)
    s = FeedSample(ts=1, fr=0.0003, efr=0.0003, basis_bps=10, spot_price=9_000_000, usdtinr=90)
    await _enter_short(st, s, fc, live=True, cfg={"capital":100_000,"stop_fill_est":0.02,"risk_fraction":0.05,"leverage_cap":5,"pair":"B-BTC_USDT","spot_pair":"BTCINR"})
    assert st.side == 0 and st.halted_orphan is True, (st.side, st.halted_orphan)
    # carry-forward fix: orphan leg must also HALT the loop (SPEC error-handling #1)
    assert st.halted is True, ("orphan did not halt", st.halted)
    # orphan cleanup must have exited the perp position by its real id string
    assert any(c[0] == "exit" and c[1] == "p1" for c in fc.calls), fc.calls
    print("carry_trader faults OK")


async def _demo_reconcile():
    # case 1: local says flat, exchange says short 0.1 -> exchange truth wins, re-sync
    class FC:
        async def get_positions(self, pair=None):
            return [{"id": "p1", "pair": "B-BTC_USDT", "position_size": -0.1, "side": "short"}]
    st = TraderState(side=0)
    await reconcile(st, FC(), "B-BTC_USDT")
    assert st.side == -1 and abs(st.qty - 0.1) < 1e-9, (st.side, st.qty)
    # case 2: local claims short but exchange is flat -> halt (don't guess)
    class FC2:
        async def get_positions(self, pair=None): return []
    st2 = TraderState(side=-1, qty=0.1)
    await reconcile(st2, FC2(), "B-BTC_USDT")
    assert st2.halted is True, ("expected halt on local/exchange mismatch", st2.halted)
    print("carry_trader reconcile OK")


async def _paper_feed():
    await asyncio.sleep(0)  # Task 7 / deploy wires real paper feed


async def _live_feed():
    # read latest row from reports/coindcx_venue.csv (recorder writes it) -> FeedSample
    import csv
    p = REPORTS / "coindcx_venue.csv"
    if not p.exists():
        return None
    rows = list(csv.DictReader(p.read_text().splitlines()))
    if not rows:
        return None
    r = rows[-1]
    return FeedSample(ts=int(float(r["ts"])), fr=float(r["fr"]), efr=float(r["efr"]),
                      basis_bps=float(r["basis_bps"]), spot_price=float(r["spot_inr"]),
                      usdtinr=float(r["usdtinr"]))


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--band", type=float, default=0.0002)
    ap.add_argument("--capital", type=float, default=100_000.0)
    ap.add_argument("--pair", default="B-BTC_USDT")
    ap.add_argument("--spot-pair", default="BTCINR")
    ap.add_argument("--leverage", type=int, default=3)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = {"band": args.band, "capital": args.capital, "stop_fill_est": 0.02,
           "risk_fraction": 0.05, "leverage_cap": args.leverage, "max_dd": 0.25,
           "basis_stop_bps": 100.0, "pair": args.pair, "spot_pair": args.spot_pair,
           "poll_s": 60}
    client = None
    feed_fn = None
    if args.live:
        from app.config import settings
        if not settings.live:
            print("Refusing --live: trading_mode != 'live' in .env"); return
        from app.exchange.coindcx import CoinDCXClient
        client = CoinDCXClient()
        feed_fn = _live_feed
    else:
        feed_fn = _paper_feed
    asyncio.run(run_loop(cfg, client=client, feed=feed_fn, live=args.live))


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        main()  # CLI: --live / --band / --capital / --pair / --spot-pair / --leverage
    else:
        demo()