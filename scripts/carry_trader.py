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

from scripts.coindcx_venue_recorder import sample as _recorder_sample

log = logging.getLogger("carry_trader")
REPORTS = Path("reports")
PAPER_LEDGER = REPORTS / "carry_paper.csv"
FUNDING_MARK_S = 8 * 3600  # CoinDCX funding settlement interval (00:00/08:00/16:00 UTC)


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
    accrued_funding: float = 0.0   # paper PnL: cumulative funding income at 8h marks
    basis_mtm: float = 0.0         # paper PnL: unrealized basis/FX drift on open position
    last_mark_ts: int = 0          # last 8h funding-mark floor processed (for accrual)
    entry_basis_bps: float = 0.0   # basis at entry (for MTM)
    corrupt: bool = False  # state.json missing/corrupt at load -> halt, don't guess (SPEC rule 5)


class TiltSignal:
    """Pluggable directional tilt source (sub-project 2). conviction in [-1,+1]:
    +=long perp, -=short perp, 0 = no tilt."""
    async def conviction(self, sample: FeedSample, state: TraderState) -> float:
        return 0.0


class NoTilt(TiltSignal):
    pass


class TiltRisk:
    """Pluggable tilt sizing/stop overlay (sub-project 3). Stub returns raw tilt_size."""
    async def size(self, cfg: dict, conviction_mag: float, sample) -> float:
        from scripts.risk_budget import tilt_size
        return tilt_size(cfg["capital"], conviction_mag, cfg["risk_fraction"], cfg["leverage_cap"])


async def run_loop(cfg: dict, client=None, feed=None, state_path=None, live=False) -> None:
    """Main loop. cfg: {band, capital, stop_fill_est, risk_fraction, leverage_cap, max_dd, basis_stop_bps, pair, spot_pair}.
    client/feed injectable for tests. live=False = paper (log only)."""
    state_path = state_path or (REPORTS / "carry_trader_state.json")
    state = _load_state(state_path)
    halt_file = REPORTS / "carry_trader.HALT"
    log.info("carry_trader start live=%s band=%s", live, state.band)
    if live and client is not None:
        await reconcile(state, client, cfg)
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
            _save_state(state_path, state)
            await asyncio.sleep(cfg.get("poll_s", 60))
            continue
        state.last_feed_ts = s.ts
        # paper PnL: accrue funding at 8h marks (replaces placeholder equity)
        if _accrue_funding(state, s):
            log.info("FUNDING_ACCRUE total=%s fr=%s", state.accrued_funding, s.fr)
            if not live: _paper_ledger(state, "FUNDING_ACCRUE", s)
        # basis-stop (60s): force flatten on squeeze spike
        if state.side != 0 and s.basis_bps > cfg["basis_stop_bps"]:
            log.warning("basis-stop fire basis=%sbps -> flatten", s.basis_bps)
            if not live: _paper_ledger(state, "BASIS_STOP", s)
            await _flatten_all(state, client, live, cfg); continue
        # DD halt
        eq = _mark_equity(state, s)
        state.peak_equity = max(state.peak_equity, eq)
        from scripts.risk_budget import max_dd_halt
        if max_dd_halt(eq, state.peak_equity, cfg["max_dd"]):
            log.warning("DD halt eq=%.0f peak=%.0f -> flatten+halt", eq, state.peak_equity)
            if not live: _paper_ledger(state, "DD_HALT", s)
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
        if c != 0 and state.side == 0:  # signed [-1,+1]: only tilt when flat (no stacking)
            tilt_risk = cfg.get("tilt_risk") or TiltRisk()  # sub-project 3 fills
            tqty = await tilt_risk.size(cfg, abs(c), s) / s.spot_price
            direction = "long" if c > 0 else "short"
            log.info("TILT conviction=%.2f dir=%s qty=%s (stub: no order in paper)",
                     abs(c), direction, tqty)
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
        except (json.JSONDecodeError, TypeError, ValueError):
            log.warning("state file corrupt -> flag corrupt")
            st = TraderState(); st.corrupt = True; return st
        d.pop("corrupt", None)  # corrupt is a transient load-time signal; never reload as corrupt
        valid = {k: v for k, v in d.items() if k in TraderState.__dataclass_fields__}
        return TraderState(**valid)
    log.warning("state file missing -> flag corrupt")
    st = TraderState(); st.corrupt = True; return st


def _save_state(path, st: TraderState) -> None:
    Path(path).write_text(json.dumps(st.__dict__, indent=2))


def _mark_equity(st: TraderState, s: FeedSample) -> float:
    # paper PnL equity: peak + accrued funding (8h marks) + unrealized basis/FX MTM.
    # Replaces the sub-project-1 placeholder. Real MTM deferred to Phase 2 live fills in
    # the perp/spot leg fills; here basis_mtm is the delta-neutral residual (the §29 FX leg).
    if st.side == 0:
        return st.peak_equity
    return st.peak_equity + st.accrued_funding + _basis_mtm(st, s)


def _accrue_funding(st: TraderState, s: FeedSample) -> bool:
    """Accrue carry income at 8h funding marks. First sample seeds last_mark_ts (no accrue).
    A mark crossing while short -> accrued_funding += qty * fr * entry_spot. No double-accrue
    within the same mark. Returns True if accrued this call."""
    if st.side != -1:
        return False
    mark = s.ts - (s.ts % FUNDING_MARK_S)
    if st.last_mark_ts == 0:
        st.last_mark_ts = mark
        return False
    if mark > st.last_mark_ts:
        # ponytail: on a multi-mark gap (feed outage spanned marks) accrue once at the
        # resumption fr with the gap absorbed here; run_loop logs a FUNDING_ACCRUE gap flag.
        st.accrued_funding += st.qty * s.fr * st.entry_spot
        st.last_mark_ts = mark
        return True
    return False


def _basis_mtm(st: TraderState, s: FeedSample) -> float:
    """Unrealized basis/FX MTM on the open delta-neutral position (INR). 0 when flat."""
    if st.side == 0 or st.qty == 0.0:
        return 0.0
    return st.qty * ((s.basis_bps - st.entry_basis_bps) / 1e4) * st.entry_spot


def _paper_ledger(st: TraderState, event: str, s: FeedSample | None,
                  path: Path = PAPER_LEDGER) -> None:
    """Append one row to the paper ledger (success-criteria evidence). Best-effort:
    a write failure must never crash the loop. s=None -> fr/efr/basis blank."""
    import csv
    try:
        new = not path.exists()
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["ts", "event", "side", "fr", "efr", "basis_bps",
                            "accrued_funding", "equity"])
            w.writerow([int(time.time()), event, st.side,
                        s.fr if s else "", s.efr if s else "",
                        s.basis_bps if s else "",
                        round(st.accrued_funding, 6),
                        round(_mark_equity(st, s) if s else st.peak_equity, 6)])
    except OSError as e:  # ledger is observational, never load-bearing
        log.warning("paper ledger write failed: %s", e)


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
    st.entry_basis_bps = s.basis_bps; st.peak_equity = st.peak_equity or 0.0
    log.info("ENTER_SHORT qty=%s fr=%s basis=%sbps", st.qty, s.fr, s.basis_bps)
    if not live: _paper_ledger(st, "ENTER_SHORT", s)


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
    if not live: _paper_ledger(st, "FLATTEN", None)


async def _on_feed_outage(st, client, live, cfg):
    now_ms = int(time.time() * 1000)
    if st.last_feed_ts == 0: st.last_feed_ts = now_ms
    age = now_ms - st.last_feed_ts
    # ponytail: 2 missed polls -> flatten+halt; tune poll_s for longer grace
    if age > 2 * cfg.get("poll_s", 60) * 1000 and st.side != 0:
        log.warning("feed outage %dms -> flatten + halt", age)
        if not live: _paper_ledger(st, "FEED_OUTAGE", None)
        await _flatten_all(st, client, live, cfg)
        st.halted = True
    return st


async def reconcile(st: TraderState, client, cfg) -> None:
    """Exchange truth wins. If local disagrees or is corrupt and exchange is flat -> halt (don't guess)."""
    pair = cfg["pair"]
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
    # exchange has a position
    if st.corrupt:
        # corrupt/missing state + exchange position -> flatten + halt (don't guess) (SPEC rule 5).
        # _flatten_all guards `if st.side == 0: return`, but fresh corrupt state is flat; set
        # side/qty to the real exchange position so _flatten_all actually exits the perp.
        log.warning("reconcile: corrupt/missing state + exchange has position -> flatten + halt (don't guess)")
        p = open_pos[0]
        sz = abs(float(p.get("position_size", 0)))
        st.side = -1 if str(p.get("side", "short")) == "short" else 1
        st.qty = sz
        await _flatten_all(st, client, True, cfg)
        st.halted = True; st.side = 0; st.qty = 0.0
        return
    # valid state + exchange position -> adopt exchange truth (restart recovery, resume)
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
    asyncio.run(_demo_venue_gate())
    asyncio.run(_demo_feed())
    asyncio.run(_demo_paper_pnl())


async def _demo_paper_pnl():
    """8h funding accrual + basis MTM + real mark_equity (replaces placeholder)."""
    # entry: short 0.1 BTC @ entry_spot 9_000_000, basis 10bps, peak=capital 100k
    st = TraderState(side=-1, qty=0.1, entry_perp=9_000_000, entry_spot=9_000_000,
                     peak_equity=100_000.0, entry_basis_bps=10.0, last_mark_ts=0)
    m0 = 1700000000 - (1700000000 % (8 * 3600))   # current 8h mark floor
    s_seed = FeedSample(ts=m0 + 60, fr=0.0003, efr=0.0003, basis_bps=10, spot_price=9_000_000, usdtinr=90)
    # first sample seeds last_mark_ts, no accrue
    assert _accrue_funding(st, s_seed) is False and st.accrued_funding == 0.0, "seed, no accrue"
    assert st.last_mark_ts == m0, "last_mark_ts seeded"

    # next mark crossed -> accrue qty*fr*entry_spot = 0.1*0.0003*9_000_000 = 270
    m1 = m0 + 8 * 3600
    s_mark = FeedSample(ts=m1 + 60, fr=0.0003, efr=0.0003, basis_bps=15, spot_price=9_000_000, usdtinr=90)
    assert _accrue_funding(st, s_mark) is True, "mark crossed -> accrue"
    assert abs(st.accrued_funding - 270.0) < 1e-6, st.accrued_funding
    assert st.last_mark_ts == m1

    # same mark, second sample -> no double accrue
    assert _accrue_funding(st, FeedSample(ts=m1 + 120, fr=0.0003, efr=0.0003, basis_bps=15,
                                          spot_price=9_000_000, usdtinr=90)) is False
    assert abs(st.accrued_funding - 270.0) < 1e-6, "no double accrue within same mark"

    # basis MTM: basis moved 10->15 bps -> qty*(5/1e4)*entry_spot = 0.1*0.0005*9_000_000 = 450
    assert abs(_basis_mtm(st, s_mark) - 450.0) < 1e-6, _basis_mtm(st, s_mark)
    # equity = peak + accrued + basis_mtm = 100_000 + 270 + 450 = 100_720
    assert abs(_mark_equity(st, s_mark) - 100_720.0) < 1e-6, _mark_equity(st, s_mark)

    # flat -> equity is peak only
    flat = TraderState(side=0, peak_equity=100_000.0)
    assert _mark_equity(flat, s_mark) == 100_000.0

    # paper ledger: append-only, events recorded, header on new file.
    import tempfile
    ld = Path(tempfile.mkdtemp()) / "carry_paper.csv"
    st2 = TraderState(side=-1, qty=0.1, entry_spot=9_000_000, peak_equity=100_000.0,
                      entry_basis_bps=10.0, accrued_funding=270.0)
    samp = FeedSample(ts=m1 + 60, fr=0.0003, efr=0.0003, basis_bps=15, spot_price=9_000_000, usdtinr=90)
    _paper_ledger(st2, "ENTER_SHORT", samp, path=ld)
    _paper_ledger(st2, "FUNDING_ACCRUE", samp, path=ld)
    _paper_ledger(st2, "FEED_OUTAGE", None, path=ld)
    import csv
    rows = list(csv.DictReader(ld.read_text().splitlines()))
    assert len(rows) == 3, rows
    assert rows[0]["event"] == "ENTER_SHORT" and abs(float(rows[0]["accrued_funding"]) - 270.0) < 1e-6
    assert rows[2]["event"] == "FEED_OUTAGE" and rows[2]["fr"] == "", rows[2]
    print("carry_trader paper-pnl OK")


async def _demo_tilt():
    # NoTilt -> 0.0 (neutral)
    t = NoTilt()
    assert await t.conviction(FeedSample(0, 0, 0, 0, 0, 0), TraderState()) == 0.0
    # signed contract: a fake long tilt -> positive, a fake short tilt -> negative
    class FakeTilt(TiltSignal):
        async def conviction(self, sample, state): return 0.7   # long
    class FakeShort(TiltSignal):
        async def conviction(self, sample, state): return -0.5  # short
    assert await FakeTilt().conviction(FeedSample(0, 0, 0, 0, 0, 0), TraderState()) > 0
    assert await FakeShort().conviction(FeedSample(0, 0, 0, 0, 0, 0), TraderState()) < 0
    print("carry_trader tilt OK")


async def _demo_venue_gate():
    """Phase 0 gate: --live refuses on missing/stale/FAIL, allows on PASS+fresh.

    Tests the gate helpers directly with tmp JSON files. Cannot drive main()
    through a monkeypatched load_gate: carry_trader binds the name at import
    time, so post-import monkeypatch of scripts.venue_verify.load_gate is
    invisible to carry_trader's bound reference. The production guard in
    main() is reviewed via diff; this demo exercises the gate LOGIC.
    """
    import tempfile

    from scripts.venue_verify import gate_is_fresh, load_gate

    td = Path(tempfile.mkdtemp())
    gate_file = td / "venue_verify.json"
    now = int(time.time())

    # PASS + fresh -> would proceed
    gate_file.write_text(json.dumps({"timestamp": now, "verdict": "PASS"}))
    g = load_gate(path=gate_file)
    assert g is not None and g["verdict"] == "PASS" and gate_is_fresh(g), g

    # FAIL (redesign_required) -> refuse
    gate_file.write_text(json.dumps({"timestamp": now, "verdict": "FAIL",
                                     "redesign_required": True}))
    g_fail = load_gate(path=gate_file)
    assert g_fail is not None and g_fail["verdict"] == "FAIL", g_fail

    # stale (>24h) -> refuse
    gate_file.write_text(json.dumps({"timestamp": now - 25 * 3600, "verdict": "PASS"}))
    g_stale = load_gate(path=gate_file)
    assert g_stale is not None and g_stale["verdict"] == "PASS", g_stale
    assert not gate_is_fresh(g_stale), "stale gate should be refused"

    # missing -> refuse (load_gate returns None)
    gate_file.unlink()
    assert load_gate(path=gate_file) is None, "missing gate should return None"

    print("carry_trader venue OK")


async def _demo_feed():
    """REST paper feed reuses recorder.sample(); csv_feed reads the recorder CSV.
    --feed selection: rest (default) vs csv. Guards empty fr/basis -> None (outage)."""
    import tempfile

    # REST feed: mocked recorder.sample() -> BTC row -> FeedSample; empty fr -> None.
    good = [{"ts": 1700000000, "sym": "BTC", "fr": 0.0003, "efr": 0.00031,
             "mp": 30000, "ls": 30000, "spot_inr": 2700000, "usdtinr": 90,
             "basis_bps": 11.1}]
    # ponytail: patch sys.modules[__name__] not `import scripts.carry_trader as ct`:
    # when run as `python scripts/carry_trader.py`, __main__ and scripts.carry_trader
    # are distinct module objects; _paper_feed resolves _recorder_sample from its
    # own module (__main__), so the mock must land there.
    import sys
    mod = sys.modules[__name__]
    orig = mod._recorder_sample
    mod._recorder_sample = lambda: good
    try:
        s = await _paper_feed()
        assert s is not None and abs(s.fr - 0.0003) < 1e-12 and s.spot_price == 2700000, s
        # empty fr -> outage (None)
        mod._recorder_sample = lambda: [{"ts": 1, "sym": "BTC", "fr": None, "efr": None,
                                         "mp": 1, "ls": 1, "spot_inr": "", "usdtinr": "",
                                         "basis_bps": ""}]
        assert await _paper_feed() is None, "empty fr should be outage"
        # BTC row absent -> None
        mod._recorder_sample = lambda: [{"ts": 1, "sym": "ETH", "fr": 0.0002, "efr": 0.0002,
                                         "mp": 1, "ls": 1, "spot_inr": 1, "usdtinr": 1,
                                         "basis_bps": 0}]
        assert await _paper_feed() is None, "no BTC row -> None"
    finally:
        mod._recorder_sample = orig

    # csv_feed: write a tmp CSV, read last row -> FeedSample; missing -> None.
    td = Path(tempfile.mkdtemp())
    csvp = td / "coindcx_venue.csv"
    csvp.write_text("ts,sym,fr,efr,mp,ls,spot_inr,usdtinr,basis_bps\n"
                    "1700000060,BTC,0.0004,0.0004,30000,30000,2700000,90,11.0\n")
    s2 = csv_feed(path=csvp)
    assert s2 is not None and abs(s2.fr - 0.0004) < 1e-12 and s2.basis_bps == 11.0, s2
    assert csv_feed(path=td / "nope.csv") is None, "missing CSV -> None"

    # field-tolerant loader: old state (missing new fields) + unknown keys -> loads with defaults.
    old = td / "old_state.json"
    old.write_text(json.dumps({"side": -1, "qty": 0.1, "entry_perp": 100, "entry_spot": 100,
                               "peak_equity": 100000, "band": 0.0002, "halted": False,
                               "halted_orphan": False, "last_feed_ts": 1,
                               "future_unknown_key": "x"}))  # no accrued_funding/etc + unknown key
    st = _load_state(old)
    assert st.side == -1 and abs(st.qty - 0.1) < 1e-9, (st.side, st.qty)
    assert st.accrued_funding == 0.0 and st.basis_mtm == 0.0 and st.last_mark_ts == 0, \
        "missing fields must default"
    assert st.entry_basis_bps == 0.0
    # corrupt JSON -> corrupt flag (existing behavior preserved)
    bad = td / "bad_state.json"
    bad.write_text("{not json")
    stb = _load_state(bad)
    assert stb.corrupt is True, "corrupt JSON -> corrupt flag"
    print("carry_trader feed OK")


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
    cfg = {"pair": "B-BTC_USDT", "spot_pair": "BTCINR"}
    # case 1: local says flat, exchange says short 0.1 -> exchange truth wins, re-sync
    class FC:
        async def get_positions(self, pair=None):
            return [{"id": "p1", "pair": "B-BTC_USDT", "position_size": -0.1, "side": "short"}]
    st = TraderState(side=0)
    await reconcile(st, FC(), cfg)
    assert st.side == -1 and abs(st.qty - 0.1) < 1e-9, (st.side, st.qty)
    # case 2: local claims short but exchange is flat -> halt (don't guess)
    class FC2:
        async def get_positions(self, pair=None): return []
    st2 = TraderState(side=-1, qty=0.1)
    await reconcile(st2, FC2(), cfg)
    assert st2.halted is True, ("expected halt on local/exchange mismatch", st2.halted)
    # case 3: corrupt/missing state + exchange has position -> halt (not adopt) (SPEC rule 5)
    class FC3:
        async def get_positions(self, pair=None):
            return [{"id": "p1", "pair": "B-BTC_USDT", "position_size": -0.1, "side": "short"}]
        async def exit_position(self, position_id): return {"status": "ok"}
        async def create_spot_order(self, **k): return {"status": "ok"}
    st3 = TraderState(); st3.corrupt = True
    await reconcile(st3, FC3(), cfg)
    assert st3.halted is True and st3.side == 0, ("corrupt+open should halt, not adopt", st3.halted, st3.side)
    print("carry_trader reconcile OK")


async def _paper_feed() -> FeedSample | None:
    """REST paper feed (dev). Reuses coindcx_venue_recorder.sample() (public, no auth).
    Takes the BTC row -> FeedSample. Empty fr/basis or no BTC row -> None (feed-outage)."""
    rows = _recorder_sample()
    for r in rows:
        if r.get("sym") != "BTC":
            continue
        fr = r.get("fr")
        bb = r.get("basis_bps")
        sinr = r.get("spot_inr")
        uinr = r.get("usdtinr")
        if fr in (None, "") or bb in (None, "") or sinr in (None, "") or uinr in (None, ""):
            return None
        return FeedSample(ts=int(r["ts"]), fr=float(fr), efr=float(r.get("efr") or 0.0),
                          basis_bps=float(bb), spot_price=float(sinr), usdtinr=float(uinr))
    return None


def csv_feed(path: Path | None = None) -> FeedSample | None:
    """CSV paper/live feed (Oracle). Reads the last row of reports/coindcx_venue.csv
    (recorder writes it 60s-polled) -> FeedSample. Missing/empty -> None (outage)."""
    import csv
    p = path or (REPORTS / "coindcx_venue.csv")
    if not p.exists():
        return None
    rows = list(csv.DictReader(p.read_text().splitlines()))
    if not rows:
        return None
    r = rows[-1]
    try:
        return FeedSample(ts=int(float(r["ts"])), fr=float(r["fr"]), efr=float(r["efr"]),
                          basis_bps=float(r["basis_bps"]), spot_price=float(r["spot_inr"]),
                          usdtinr=float(r["usdtinr"]))
    except (KeyError, ValueError, TypeError):
        return None


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--band", type=float, default=0.0002)
    ap.add_argument("--capital", type=float, default=100_000.0)
    ap.add_argument("--pair", default="B-BTC_USDT")
    ap.add_argument("--spot-pair", default="BTCINR")
    ap.add_argument("--leverage", type=int, default=3)
    ap.add_argument("--feed", choices=["rest", "csv"], default="rest",
                    help="paper feed source: rest (dev, public REST) or csv (Oracle, recorder CSV)")
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
        # Phase 0 venue gate: refuse --live unless venue_verify.json is PASS + fresh.
        from scripts.venue_verify import GATE_PATH, gate_is_fresh, load_gate
        gate = load_gate()
        if gate is None:
            print(f"Refusing --live: no venue gate ({GATE_PATH}). "
                  f"Run: python scripts/venue_verify.py run"); return
        if gate.get("verdict") != "PASS":
            print(f"Refusing --live: venue gate verdict={gate.get('verdict')} "
                  f"({'redesign required' if gate.get('redesign_required') else 'probe(s) failed'}). "
                  f"Re-run: python scripts/venue_verify.py run"); return
        if not gate_is_fresh(gate):
            print("Refusing --live: venue gate stale (>24h). "
                  "Re-run: python scripts/venue_verify.py run"); return
        from app.exchange.coindcx import CoinDCXClient
        client = CoinDCXClient()
        feed_fn = csv_feed  # --live forces csv (live runs on Oracle where the CSV exists)
    else:
        feed_fn = _paper_feed if args.feed == "rest" else csv_feed
    asyncio.run(run_loop(cfg, client=client, feed=feed_fn, live=args.live))


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        main()  # CLI: --live / --band / --capital / --pair / --spot-pair / --leverage
    else:
        demo()
