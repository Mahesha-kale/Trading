"""Live hybrid carry trader (sub-project 1). Paper mode logs; live mode orders via CoinDCXClient.
8h cycle, 60s basis-stop, 25% DD halt, fail-safe flatten+halt. See spec §... (design doc)."""
from __future__ import annotations

import asyncio
import json
import logging
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


async def run_loop(cfg: dict, client=None, feed=None, state_path=None, live=False) -> None:
    """Main loop. cfg: {band, capital, stop_fill_est, risk_fraction, leverage_cap, max_dd, basis_stop_bps, pair, spot_pair}.
    client/feed injectable for tests. live=False = paper (log only)."""
    state_path = state_path or (REPORTS / "carry_trader_state.json")
    state = _load_state(state_path)
    halt_file = REPORTS / "carry_trader.HALT"
    log.info("carry_trader start live=%s band=%s", live, state.band)
    while not state.halted:
        if halt_file.exists():
            await _flatten_all(state, client, live, cfg)
            state.halted = True; _save_state(state_path, state)
            log.warning("HALT file -> flatten + halt"); break
        s = await feed()  # FeedSample or None
        if s is None:
            state = await _on_feed_outage(state, client, live, cfg)
            _save_state(state_path, state); continue
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
        _save_state(state_path, state)
        await asyncio.sleep(cfg.get("poll_s", 60))


def _load_state(path) -> TraderState:
    p = Path(path)
    if p.exists():
        d = json.loads(p.read_text())
        return TraderState(**d)
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
        # perp first, then spot hedge (orphan-leg handled Task 4)
        await client.create_order({"side":"sell","pair":cfg["pair"],"order_type":"market_order","total_quantity":qty,"leverage":cfg["leverage_cap"],"position_margin_type":"isolated"})
        await client.create_spot_order(side="buy", pair=cfg["spot_pair"], order_type="market_order", quantity=qty)
    else:
        qty = 0.0
    st.side = -1; st.qty = qty; st.entry_perp = s.spot_price; st.entry_spot = s.spot_price
    log.info("ENTER_SHORT qty=%s fr=%s", st.qty, s.fr)


async def _flatten_all(st, client, live, cfg):
    if st.side == 0: return
    if live and client is not None and st.qty > 0:
        await client.exit_position(st)  # adjust to real exit API in Task 6
        await client.create_spot_order(side="sell", pair=cfg["spot_pair"],order_type="market_order", quantity=st.qty)
    st.side = 0; log.info("FLATTEN qty=%s", st.qty); st.qty = 0.0


async def _on_feed_outage(st, client, live, cfg):
    # Task 4 implements the 16min rule; stub returns state
    return st


def demo() -> None:
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


if __name__ == "__main__":
    demo()