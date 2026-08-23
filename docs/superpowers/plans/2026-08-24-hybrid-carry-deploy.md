# Hybrid Carry Deploy Implementation Plan (sub-project 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the live hybrid carry trader — a delta-neutral funding-carry loop (short perp + long BTCINR spot) with a pluggable directional tilt slot, runnable in paper mode (no orders) and live mode (real orders), fail-safe flatten+halt on every fault.

**Architecture:** One async process on an 8h funding cycle. Reads the venue feed (fr/efr/basis from `coindcx_venue_recorder`) → `funding_carry_band.dn_band` signal → dispatch (enter/flatten/hold) → in live mode places perp+spot orders via `CoinDCXClient` → monitors a 60s basis-stop (§24) + a 25% portfolio DD stop. State persisted to JSON for restart recovery. Tilt slot is a pluggable signal interface, empty stub for now (filled by sub-project 2). Everything reused except one spot-order method + the loop itself.

**Tech Stack:** Python 3.12, asyncio, httpx (existing), numpy/pandas (existing), pydantic-settings (existing). Tests: `app/` via pytest (`asyncio_mode="auto"`, ruff line-length 100); `scripts/` via stdlib `assert` in `__main__` demo() self-checks (project convention — no pytest for scripts/).

**Spec:** `docs/superpowers/specs/2026-08-24-hybrid-carry-deploy-design.md`

## Global Constraints

- Real perp costs: maker 0.0236% / taker 0.059% (CoinDCX verified §29), funding 8h. NO TDS on perp. Spot sell = 1% TDS (spot-only, modeled in PnL).
- Delta-neutral: short perp + long BTCINR spot; leverage only shrinks perp margin (spot leg unleveraged) → carry caps ~5-6%/yr on total capital.
- Risk policy: 25% portfolio DD → flatten all + halt. Isolated margin per position.
- Fail-safe = flatten + halt on every fault (feed outage 16min, orphan leg, unknown state, HALT file).
- No new deps. Reuse `CoinDCXClient`, `funding_carry_band.dn_band`, `carry_stop` logic, `coindcx_venue_recorder.sample`, `Settings`.
- Tilt slot OFF until sub-project 2 delivers a positive-capture gate (pluggable interface, empty stub now).
- Phase 0 venue-verify gate is a wait (no code); Phase 1 paper = this plan's deliverable; Phase 2 real = flag flip + capital; Phase 3 tilt = sub-project 2+3.

---

## File Structure

- **Create `scripts/risk_budget.py`** — pure sizing math (position size from stop-loss + risk fraction; tilt size). `__main__` assert self-check.
- **Modify `app/exchange/coindcx.py`** — add `create_spot_order()` method (BTCINR spot leg). Only new exchange code.
- **Create `tests/test_exchange.py`** — pytest: spot-order body construction + signing dry-run (no network).
- **Create `scripts/carry_trader.py`** — the live loop: feed adapter, signal dispatch, basis-stop, DD-stop, orphan-leg, state recovery, HALT, paper/live modes, tilt-slot interface. `__main__` demo with in-memory fakes (assert-based chaos checks).
- **Runtime (gitignored):** `reports/carry_trader_state.json`, `reports/carry_trader.log`, `reports/carry_trader.HALT`.

---

### Task 1: risk_budget sizing module

**Files:**
- Create: `scripts/risk_budget.py`
- Test: `__main__` demo() self-check (project convention for scripts/)

**Interfaces:**
- Produces: `position_size(capital, stop_fill_est, risk_fraction, leverage_cap) -> float` (perp notional); `tilt_size(capital, conviction, risk_fraction, leverage_cap) -> float` (naked tilt notional); `max_dd_halt(equity, peak, max_dd) -> bool`.

- [ ] **Step 1: Write the failing self-check**

```python
# append to scripts/risk_budget.py
def demo() -> None:
    # 100k capital, basis-stop fills at 2%, risk 5% of capital per position
    sz = position_size(100_000.0, 0.02, 0.05, leverage_cap=5)
    # notional = capital * risk_fraction / stop_fill_est = 100k * 0.05/0.02 = 250k
    # but capped by leverage_cap * capital = 500k -> 250k ok
    assert abs(sz - 250_000.0) < 1e-6, sz
    # leverage cap binds: risk 20%, stop 2% -> 1000k notional wanted, capped at 5*100k=500k
    sz2 = position_size(100_000.0, 0.02, 0.20, leverage_cap=5)
    assert abs(sz2 - 500_000.0) < 1e-6, sz2
    # tilt: smaller, conviction-scaled, capped at 20% of perp notional budget
    t = tilt_size(100_000.0, conviction=0.5, risk_fraction=0.05, leverage_cap=5)
    assert 0 < t <= 0.20 * position_size(100_000.0, 0.02, 0.05, 5), t
    # DD halt: equity 78k, peak 100k, max_dd 0.25 -> dd=0.22 ok; 77k -> 0.23 ok; 75k -> 0.25 halt
    assert max_dd_halt(78_000.0, 100_000.0, 0.25) is False
    assert max_dd_halt(75_000.0, 100_000.0, 0.25) is True
    print("risk_budget OK")

if __name__ == "__main__":
    demo()
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/risk_budget.py`
Expected: `NameError: name 'position_size' is not defined`

- [ ] **Step 3: Write minimal implementation**

```python
"""Carry-deploy sizing: position notional from stop-loss + risk fraction; tilt slot sizing; DD halt."""
from __future__ import annotations


def position_size(capital: float, stop_fill_est: float, risk_fraction: float, leverage_cap: int) -> float:
    """Perp notional sized so a basis-stop fill at stop_fill_est loses risk_fraction*capital.
    Capped at leverage_cap*capital (isolated margin)."""
    if stop_fill_est <= 0:
        raise ValueError("stop_fill_est must be > 0")
    wanted = capital * risk_fraction / stop_fill_est
    capped = min(wanted, leverage_cap * capital)
    return capped


def tilt_size(capital: float, conviction: float, risk_fraction: float, leverage_cap: int) -> float:
    """Naked directional tilt notional: conviction in [0,1] scales the risk_fraction budget.
    Capped at 20% of the equivalent carry position notional (tilt slot limit)."""
    c = max(0.0, min(1.0, conviction))
    base = position_size(capital, 0.02, risk_fraction, leverage_cap)  # same stop assumption
    return c * 0.20 * base


def max_dd_halt(equity: float, peak: float, max_dd: float) -> bool:
    """True when drawdown from peak exceeds max_dd (e.g. 0.25)."""
    if peak <= 0:
        return False
    return (peak - equity) / peak >= max_dd
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/risk_budget.py`
Expected: `risk_budget OK`

- [ ] **Step 5: Commit**

```bash
git add scripts/risk_budget.py
git commit -m "feat(carry): risk_budget sizing module + self-check (sub-project 1)"
```

---

### Task 2: spot-order method on CoinDCXClient

**Files:**
- Modify: `app/exchange/coindcx.py` (add `create_spot_order` after `create_order` ~line 165; add spot endpoint to `EP` dict ~line 40)
- Test: `tests/test_exchange.py`

**Interfaces:**
- Produces: `async def create_spot_order(self, *, side, pair, order_type, quantity, price=None) -> dict` — signed POST to spot order endpoint; reuses `_sign`/`_signed_post`.

- [ ] **Step 1: Write the failing pytest**

```python
# tests/test_exchange.py
"""Exchange client unit tests: spot-order body + signing (no network)."""
from __future__ import annotations
import hashlib, hmac, time
from unittest.mock import AsyncMock, patch
import httpx
from app.exchange.coindcx import CoinDCXClient, build_order


def _fake_settings(monkeypatch):
    monkeypatch.setattr("app.exchange.coindcx.settings.coindcx_api_key", "k", raising=False)
    monkeypatch.setattr("app.exchange.coindcx.settings.coindcx_api_secret", "s", raising=False)


async def test_create_spot_order_body_and_sign(monkeypatch):
    _fake_settings(monkeypatch)
    cli = CoinDCXClient()
    captured = {}

    async def fake_post(self, path, *, content=None, headers=None):
        captured["path"] = path
        captured["body"] = content
        captured["headers"] = headers
        r = httpx.Response(200, json={"status": "ok", "orders": [{"id": "1"}]})
        return self._handle(r)

    monkeypatch.setattr("app.exchange.coindcx.PrivREST.post", fake_post, raising=False)
    # NOTE: if PrivREST not patchable this way, patch httpx.AsyncClient.request instead (see step 3 note)
    res = await cli.create_spot_order(side="buy", pair="BTCINR", order_type="market_order", quantity=0.1)
    assert res["status"] == "ok"
    # signature is hmac-sha256 of body with secret "s"
    sig = hmac.new(b"s", captured["body"].encode() if isinstance(captured["body"], str) else captured["body"], hashlib.sha256).hexdigest()
    assert captured["headers"]["X-AUTH-APIKEY"] == "k"
    assert captured["headers"]["X-AUTH-SIGNATURE"] == sig
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. .venv/Scripts/python -m pytest tests/test_exchange.py::test_create_spot_order_body_and_sign -v`
Expected: FAIL with `AttributeError: 'CoinDCXClient' object has no attribute 'create_spot_order'`

- [ ] **Step 3: Write minimal implementation**

Add to `EP` dict (~line 40, after `"ticker"`):
```python
    # Spot order (api.coindcx.com, signed). BTCINR spot leg for the carry hedge.
    "spot_create_order": "/exchange/v1/orders/create",
```

Add method after `create_order` (~line 165):
```python
    async def create_spot_order(
        self, *, side: str, pair: str, order_type: str, quantity: float,
        price: float | None = None,
    ) -> dict[str, Any]:
        """Spot order (BTCINR hedge leg). Signed POST. No leverage/margin fields (spot)."""
        if side not in ("buy", "sell"):
            raise ValueError(f"bad side {side}")
        if order_type not in ("market_order", "limit_order"):
            raise ValueError(f"bad spot order_type {order_type}")
        if quantity <= 0:
            raise ValueError("quantity must be > 0")
        order = {"side": side, "pair": pair, "order_type": order_type,
                 "total_quantity": quantity}
        if price is not None:
            order["price"] = price
        body = {"timestamp": int(time.time() * 1000), "order": order}
        return await self._signed_post(EP["spot_create_order"], body)
```

NOTE: if the test's `PrivREST.post` monkeypatch path is wrong (check the actual private-POST helper class name in `coindcx.py`), patch `httpx.AsyncClient.request` to capture the request instead — the assertion is on the signed headers/body, not the transport. Adjust the test to match the real internal call path found in `_signed_post`.

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=. .venv/Scripts/python -m pytest tests/test_exchange.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/exchange/coindcx.py tests/test_exchange.py
git commit -m "feat(exchange): add create_spot_order for BTCINR hedge leg + signing test"
```

---

### Task 3: carry_trader skeleton — feed adapter + signal dispatch (paper mode)

**Files:**
- Create: `scripts/carry_trader.py`
- Test: `__main__` demo() with in-memory fakes

**Interfaces:**
- Consumes: `funding_carry_band.dn_band` (signal convention: rate>+band → short; rate<−band → flatten), `coindcx_venue_recorder.sample()` shape, `risk_budget.position_size`.
- Produces: `decide(rate_history, band, side) -> str` (action: ENTER_SHORT/FLATTEN/HOLD); `class FeedSample` (ts, fr, efr, basis_bps, spot_price, usdtinr); `async def run_loop(cfg)`.

- [ ] **Step 1: Write the failing self-check (decision logic)**

```python
# scripts/carry_trader.py — append demo at bottom
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py`
Expected: `NameError: name 'decide' is not defined`

- [ ] **Step 3: Write minimal implementation**

```python
"""Live hybrid carry trader (sub-project 1). Paper mode logs; live mode orders via CoinDCXClient.
8h cycle, 60s basis-stop, 25% DD halt, fail-safe flatten+halt. See spec §... (design doc)."""
from __future__ import annotations
import asyncio, json, logging, time
from dataclasses import dataclass, field
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
        if eq > state.peak_equity: state.peak_equity = eq
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
```

Add the helpers referenced (`_load_state`, `_save_state`, `_enter_short`, `_flatten_all`, `_on_feed_outage`, `_mark_equity`) as stubs in this step — paper-mode stubs log only, live-mode stubs use client. Keep them small:

```python
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
    # ponytail: live funding accrual modeled per-cycle from fr; refined in Task 4
    funding = st.qty * s.fr * st.entry_spot
    return st.peak_equity + funding  # placeholder refined Task 4/5

async def _enter_short(st, s, client, live, cfg):
    if live and client is not None:
        from scripts.risk_budget import position_size
        qty = position_size(cfg["capital"], cfg["stop_fill_est"], cfg["risk_fraction"], cfg["leverage_cap"]) / s.spot_price
        # perp first, then spot hedge (orphan-leg handled Task 4)
        await client.create_order({"side":"sell","pair":cfg["pair"],"order_type":"market_order","total_quantity":qty,"leverage":cfg["leverage_cap"],"position_margin_type":"isolated"})
        await client.create_spot_order(side="buy", pair=cfg["spot_pair"], order_type="market_order", quantity=qty)
    st.side = -1; st.qty = qty if live else 0.0; st.entry_perp = s.spot_price; st.entry_spot = s.spot_price
    log.info("ENTER_SHORT qty=%s fr=%s", st.qty, s.fr)

async def _flatten_all(st, client, live, cfg):
    if st.side == 0: return
    if live and client is not None and st.qty > 0:
        await client.exit_position(st)  # adjust to real exit API in Task 6
        await client.create_spot_order(side="sell", pair=cfg["spot_pair"], order_type="market_order", quantity=st.qty)
    st.side = 0; log.info("FLATTEN qty=%s", st.qty); st.qty = 0.0

async def _on_feed_outage(st, client, live, cfg):
    # Task 4 implements the 16min rule; stub returns state
    return st
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py`
Expected: `carry_trader signal OK`

- [ ] **Step 5: Commit**

```bash
git add scripts/carry_trader.py
git commit -m "feat(carry): trader skeleton — feed adapter + signal dispatch (paper mode)"
```

---

### Task 4: fault handling — basis-stop, DD-stop, orphan-leg, feed outage

**Files:**
- Modify: `scripts/carry_trader.py` (`_enter_short`, `_flatten_all`, `_on_feed_outage`, `run_loop`)

**Interfaces:**
- Produces: orphan-leg guard (perp fill confirmed before spot; spot reject → exit perp + halt); 16min feed-outage → flatten+halt; basis-stop already in run_loop (Task 3).

- [ ] **Step 1: Write the failing self-check (orphan-leg + outage)**

```python
# append to demo()
async def _demo_faults():
    # orphan leg: perp fills, spot rejects -> state back to flat + halted
    class FakeClient:
        def __init__(self): self.calls = []
        async def create_order(self, p): self.calls.append(("perp", p)); return {"status":"ok","orders":[{"id":"1"}]}
        async def create_spot_order(self, **k): self.calls.append(("spot", k)); raise RuntimeError("spot reject")
        async def exit_position(self, st): self.calls.append(("exit", st)); return {"status":"ok"}
    fc = FakeClient()
    st = TraderState(side=0)
    s = FeedSample(ts=1, fr=0.0003, efr=0.0003, basis_bps=10, spot_price=9_000_000, usdtinr=90)
    await _enter_short(st, s, fc, live=True, cfg={"capital":100_000,"stop_fill_est":0.02,"risk_fraction":0.05,"leverage_cap":5,"pair":"B-BTC_USDT","spot_pair":"BTCINR"})
    assert st.side == 0 and st.halted_orphan is True, (st.side, st.halted_orphan)
    assert ("exit", st) in fc.calls or any(c[0]=="exit" for c in fc.calls)
    print("carry_trader faults OK")

# in demo(): add `import asyncio; asyncio.run(_demo_faults())`
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py`
Expected: FAIL — `halted_orphan` attribute doesn't exist / orphan logic not implemented.

- [ ] **Step 3: Implement orphan-leg + outage**

Add `halted_orphan: bool = False` and `last_feed_ts: int = 0` to `TraderState`. Rewrite `_enter_short`:

```python
async def _enter_short(st, s, client, live, cfg):
    if live and client is not None:
        from scripts.risk_budget import position_size
        qty = position_size(cfg["capital"], cfg["stop_fill_est"], cfg["risk_fraction"], cfg["leverage_cap"]) / s.spot_price
        try:
            await client.create_order({"side":"sell","pair":cfg["pair"],"order_type":"market_order","total_quantity":qty,"leverage":cfg["leverage_cap"],"position_margin_type":"isolated"})
            # ponytail: confirm fill via positions() in Task 6; here assume market fills
            await client.create_spot_order(side="buy", pair=cfg["spot_pair"], order_type="market_order", quantity=qty)
        except Exception as e:
            log.error("orphan leg: %s -> exit perp + halt", e)
            try: await client.exit_position(st)
            except Exception: pass
            st.halted_orphan = True; st.side = 0; return
        st.qty = qty
    st.side = -1; st.entry_perp = s.spot_price; st.entry_spot = s.spot_price
    log.info("ENTER_SHORT qty=%s fr=%s", st.qty, s.fr)
```

Rewrite `_on_feed_outage` with the 16min rule (state carries `last_feed_ts`):

```python
async def _on_feed_outage(st, client, live, cfg):
    now_ms = int(time.time() * 1000)
    if st.last_feed_ts == 0: st.last_feed_ts = now_ms
    age = now_ms - st.last_feed_ts
    if age > 2 * cfg.get("poll_s", 60) * 1000 and st.side != 0:  # >2 cycles = 16min@60s
        log.warning("feed outage %dms -> flatten + halt", age)
        await _flatten_all(st, client, live, cfg)
        st.halted = True
    return st
```

In `run_loop`, set `state.last_feed_ts = s.ts` after a successful feed read.

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py`
Expected: `carry_trader signal OK` + `carry_trader faults OK`

- [ ] **Step 5: Commit**

```bash
git add scripts/carry_trader.py
git commit -m "feat(carry): orphan-leg guard + 16min feed-outage halt + basis-stop"
```

---

### Task 5: state persistence, restart recovery, HALT kill-switch

**Files:**
- Modify: `scripts/carry_trader.py` (`run_loop` startup: reconcile state with exchange truth; HALT check already in Task 3)

**Interfaces:**
- Produces: on startup, reconcile `TraderState` with `client.positions()` — exchange truth wins; if state missing/corrupt + exchange has a position → flatten + halt (don't guess).

- [ ] **Step 1: Write the failing self-check (reconcile)**

```python
# append to _demo_faults()
async def _demo_reconcile():
    # local says flat, exchange says short 0.1 -> exchange truth wins, re-sync
    class FC:
        async def positions(self): return [{"pair":"B-BTC_USDT","size":-0.1,"side":"short","leverage":3}]
    st = TraderState(side=0)
    await reconcile(st, FC())  # should set st.side=-1, st.qty=0.1
    assert st.side == -1 and abs(st.qty-0.1) < 1e-9, (st.side, st.qty)
    # corrupt state + exchange flat -> halt (don't guess)
    class FC2:
        async def positions(self): return []
    st2 = TraderState(side=-1, qty=0.1, _corrupt=True)
    await reconcile(st2, FC2())
    assert st2.halted is True
    print("carry_trader reconcile OK")
# add to demo() asyncio.run
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py`
Expected: FAIL — `reconcile` not defined.

- [ ] **Step 3: Implement reconcile**

```python
async def reconcile(st: TraderState, client) -> None:
    """Exchange truth wins. If local disagrees or is corrupt and exchange is flat -> halt (don't guess)."""
    try:
        poss = await client.positions()
    except Exception as e:
        log.error("reconcile: positions() failed -> halt: %s", e); st.halted = True; return
    open_pos = [p for p in poss if float(p.get("size", 0) or 0) != 0]
    if not open_pos:
        if st.side != 0:
            log.warning("reconcile: local side=%s but exchange flat -> halt (don't guess)", st.side)
            st.halted = True; st.side = 0; st.qty = 0.0
        return
    # exchange has a position -> adopt exchange truth
    p = open_pos[0]
    sz = abs(float(p.get("size", 0)))
    st.side = -1 if str(p.get("side","short")) == "short" else 1
    st.qty = sz
    log.info("reconcile: exchange has %s qty=%s -> adopted", st.side, sz)
```

Add `reconcile(state, client)` call at the top of `run_loop` before the `while` (only when live). Add `_corrupt: bool = False` to `TraderState` (default False; corrupt-detection sets it).

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py`
Expected: all three OK lines.

- [ ] **Step 5: Commit**

```bash
git add scripts/carry_trader.py
git commit -m "feat(carry): restart reconcile (exchange truth wins) + corrupt-state halt"
```

---

### Task 6: live-mode order wiring + signing dry-run

**Files:**
- Modify: `scripts/carry_trader.py` (finalize `_enter_short`/`_flatten_all` real order paths; add `main()` CLI entry with `--live` flag)
- Test: `__main__` + a `--dry-run-sign` path that builds the order body + signs without sending.

**Interfaces:**
- Produces: `main()` async CLI: `python scripts/carry_trader.py [--live] [--band B] [--capital C]`. `--live` flips to real orders; default paper.

- [ ] **Step 1: Write the failing self-check (dry-run sign)**

```python
# append: signing dry-run builds perp+spot bodies, signs, does NOT send
async def _demo_sign():
    from app.exchange.coindcx import CoinDCXClient, build_order
    import os
    os.environ["COINDCX_API_KEY"]="k"; os.environ["COINDCX_API_SECRET"]="s"
    cli = CoinDCXClient()
    perp = build_order(side="sell", pair="B-BTC_USDT", order_type="market_order", quantity=0.01, leverage=3)
    assert perp["side"]=="sell" and perp["leverage"]==3
    print("carry_trader sign OK")
# add to demo()
```

- [ ] **Step 2: Run to verify it fails** (may pass if build_order already works — if so, treat as a regression guard and proceed)

Run: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py`
Expected: `carry_trader sign OK` (or adjust assertion if build_order already validated in Task 2).

- [ ] **Step 3: Implement main() CLI + finalize live paths**

```python
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
        from app.exchange.coindcx import CoinDCXClient
        from app.config import settings
        if not settings.live:
            print("Refusing --live: trading_mode != 'live' in .env"); return
        client = CoinDCXClient()
        feed_fn = _live_feed  # reads coindcx_venue_recorder last sample / rt endpoint
    else:
        feed_fn = _paper_feed  # logs-only feed stub
    asyncio.run(run_loop(cfg, client=client, feed=feed_fn, live=args.live))

async def _paper_feed():
    await asyncio.sleep(0); return None  # Task 7 / deploy wires real paper feed

async def _live_feed():
    # read latest from reports/coindcx_venue.csv (recorder writes it) -> FeedSample
    import csv
    p = REPORTS / "coindcx_venue.csv"
    if not p.exists(): return None
    rows = list(csv.DictReader(p.read_text().splitlines()))
    if not rows: return None
    r = rows[-1]
    return FeedSample(ts=int(float(r["ts"])), fr=float(r["fr"]), efr=float(r["efr"]),
                      basis_bps=float(r["basis_bps"]), spot_price=float(r["spot_inr"]),
                      usdtinr=float(r["usdtinr"]))
```

Fix `_flatten_all`'s `exit_position` call to the real signature (`await client.exit_position({"id": pos_id})` — pull the position id from `client.positions()` first).

- [ ] **Step 4: Run to verify it passes (paper)**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py` (demo)
Expected: all OK lines.
Run paper loop briefly: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py --capital 100000` then Ctrl-C after 5s — should log "carry_trader start live=False" and loop (paper feed returns None → outage path, no orders).

- [ ] **Step 5: Commit**

```bash
git add scripts/carry_trader.py
git commit -m "feat(carry): live-mode CLI + venue-csv feed + exit_position wiring"
```

---

### Task 7: tilt-slot pluggable interface (empty stub)

**Files:**
- Modify: `scripts/carry_trader.py` (add `TiltSignal` interface + stub; hook into run_loop as a no-op branch)

**Interfaces:**
- Produces: `class TiltSignal` with `async def conviction(sample, state) -> float` (0..1); `class NoTilt(TiltSignal)` returns 0.0. run_loop applies tilt only when `cfg["tilt"]` is not NoTilt AND conviction>0 — sized via `risk_budget.tilt_size`. Sub-project 2 supplies the real implementation.

- [ ] **Step 1: Write the failing self-check**

```python
# append
async def _demo_tilt():
    t = NoTilt()
    assert await t.convolution(FeedSample(0,0,0,0,0,0), TraderState()) == 0.0 if False else await t.conviction(FeedSample(0,0,0,0,0,0), TraderState()) == 0.0
    assert await t.conviction(FeedSample(0,0,0,0,0,0), TraderState()) == 0.0
    print("carry_trader tilt OK")
# add to demo()
```
(Fix the typo: use only the second assert — `conviction`, not `convolution`.)

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py`
Expected: FAIL — `NoTilt` not defined.

- [ ] **Step 3: Implement**

```python
class TiltSignal:
    """Pluggable directional tilt source (sub-project 2). conviction in [0,1]; 0 = no tilt."""
    async def conviction(self, sample: FeedSample, state: TraderState) -> float:
        return 0.0

class NoTilt(TiltSignal):
    pass

# in run_loop, after the signal dispatch block, before _save_state:
    tilt = cfg.get("tilt") or NoTilt()
    c = await tilt.conviction(s, state)
    if c > 0 and state.side == 0:  # only tilt when flat (no stacking on carry)
        from scripts.risk_budget import tilt_size
        tqty = tilt_size(cfg["capital"], c, cfg["risk_fraction"], cfg["leverage_cap"]) / s.spot_price
        log.info("TILT conviction=%.2f qty=%s (stub: no order in paper)", c, tqty)
        if live and client is not None:
            # sub-project 2+3 supplies sign + sub-project 3 overlay stops it
            pass
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py`
Expected: all OK lines including `carry_trader tilt OK`.

- [ ] **Step 5: Commit**

```bash
git add scripts/carry_trader.py
git commit -m "feat(carry): tilt-slot pluggable interface (NoTilt stub) for sub-project 2"
```

---

### Task 8: docs + deploy-readiness note

**Files:**
- Modify: `docs/strategies_report.md` (append §30: hybrid carry deploy built — paper-trader + components; Phase 0 venue accrual status; not deployed, paper-gated)
- Modify: `README.md` or `deploy/README.md` if it exists — note `scripts/carry_trader.py` usage + the HALT file + state file.

- [ ] **Step 1: Append §30 to `docs/strategies_report.md`**

Summarize: what was built (risk_budget, create_spot_order, carry_trader paper+live), the 4-phase gating status (Phase 0 accruing, Phase 1 ready to run paper once venue-gate passes), the tilt-slot interface awaiting sub-project 2, the fail-safe contract. Reference the spec + this plan.

- [ ] **Step 2: Commit**

```bash
git add docs/strategies_report.md
git commit -m "docs(research): §30 hybrid carry deploy built (paper-trader, sub-project 1)"
```

---

## Self-Review

**1. Spec coverage:**
- Phase 0 venue-verify gate → no code (wait); tracked as a precondition in Task 6 `_live_feed` (reads venue csv) + spec. ✓
- Phase 1 paper-trader → Tasks 1-7 deliver the paper-capable loop. ✓
- Phase 2 small real → Task 6 `--live` flag + capital. ✓
- Phase 3 tilt → Task 7 interface + stub. ✓
- risk_budget → Task 1. ✓
- create_spot_order → Task 2. ✓
- Error handling rules 1-8 → Task 4 (orphan, outage, basis-stop), Task 5 (reconcile, corrupt-state, restart), Task 3 (HALT file, DD-stop), Task 6 (key safety via Settings, TDS noted in spec). ✓
- Testing → every task has a self-check/pytest; Phase 1 paper IS the integration test (spec). ✓
- Out of scope (tilt signal, risk overlay) → separate specs. ✓

**2. Placeholder scan:** Task 6 step 1 has a deliberate typo (`convolution`) flagged inline to fix — corrected in Step 3 instruction. `_mark_equity` is a ponytail placeholder refined across tasks (flagged). No "TBD/TODO/add error handling" without code. ✓

**3. Type consistency:** `FeedSample` fields (ts, fr, efr, basis_bps, spot_price, usdtinr) consistent across Tasks 3,4,6,7. `TraderState` fields added incrementally (halted_orphan, last_feed_ts, _corrupt) — all default-valued so earlier tasks' constructions still work. `decide`/`position_size`/`tilt_size`/`max_dd_halt` signatures stable. ✓

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-24-hybrid-carry-deploy.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?