# Phase 1 Paper-Trader Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the carry trader's stub paper feed to live CoinDCX data, add real paper-PnL accounting (funding accrual at 8h marks + basis MTM), and produce Oracle deploy artifacts + a paper-check verdict script so a 7-14d paper validation run gates Phase 2 small-real.

**Architecture:** Two feeds behind `--feed {rest,csv}` (default `rest`). REST dev feed reuses `coindcx_venue_recorder.sample()` (public, no auth). CSV Oracle feed extracted from the existing `_live_feed()`. Paper-PnL replaces the `_mark_equity` placeholder: funding accrued at 8h settlement marks + basis MTM → real equity driving DD/basis-stop. Paper ledger `reports/carry_paper.csv` is the success-criteria evidence. Oracle systemd unit runs `--feed csv` paper alongside the recorder; `venue_verify.py run` there gives the definitive Phase 0 verdict. `paper_check.py` emits the 5-criteria verdict.

**Tech Stack:** Python 3.12, asyncio, stdlib `csv`/`urllib` (via the recorder), dataclasses. `scripts/` self-checks via `__main__` `demo()` (NO pytest). `ruff` line-length 100.

**Spec:** `docs/superpowers/specs/2026-08-25-phase1-paper-trader-design.md` — the plan argues from the spec; executors read both.

## Global Constraints

- Paper mode only — NO real orders (`--live` untouched, still gated by Phase 0 venue gate + `trading_mode=="live"`). Paper `live=False`, `client=None`.
- Perp carries NO 1% TDS (TDS is spot-sell only; paper never sells). Spot-leg TDS not simulated (paper accrues funding only) — recorded as a caveat in §33.
- Two feeds, one `FeedSample(ts, fr, efr, basis_bps, spot_price, usdtinr)` contract (unchanged from sub-project 1).
- REST feed reuses `scripts/coindcx_venue_recorder.py::sample()` — public endpoints, no auth, no new fetch code. Do NOT re-implement the fetch.
- API keys in `.env` via `app.config.settings`, never logged. REST feed uses no auth.
- Fail-safe flatten+halt unchanged; 25% DD hard stop unchanged. In paper, "flatten" is a state transition (side→0, log), not an order.
- `ruff` line-length 100, Python 3.12. `scripts/` → `__main__` assert `demo()` (NO pytest). `app/` + `tests/` → pytest (`asyncio_mode=auto`). gh at `C:\Program Files\GitHub CLI\gh.exe`.
- The 6 existing demo OK lines (signal/faults/reconcile/sign/tilt/venue) must stay green (regression guard). New OK lines added: `carry_trader feed OK`, `carry_trader paper-pnl OK`.
- `TraderState` loader must be field-tolerant: old sub-project-1 state files (missing `accrued_funding`/`basis_mtm`/`last_mark_ts`/`entry_basis_bps`) must load with defaults, and unknown keys must be dropped (no TypeError/KeyError).
- 8h funding marks = 00:00/08:00/16:00 UTC (multiples of 28800s from the Unix epoch). Confirm on first Oracle run from `efr` transitions; the accrual logic keys on `ts - (ts % 28800)`.

---

### Task 1: `--feed {rest,csv}` arg + REST paper feed (reuse recorder) + csv_feed extraction

**Files:**
- Modify: `scripts/carry_trader.py` (top import, `_paper_feed`, `_live_feed`→`csv_feed`, `main()`, `demo`/`_demo_feed`)
- Consumes: `scripts/coindcx_venue_recorder.py::sample()` (returns `list[dict]` with keys `ts, sym, fr, efr, mp, ls, spot_inr, usdtinr, basis_bps`; BTC row has `sym=="BTC"`)
- Produces: `_paper_feed()` (REST) + `csv_feed()` (CSV) + `--feed` selection in `main()`. `run_loop` signature unchanged.

**Interfaces:**
- `FeedSample(ts:int, fr:float, efr:float, basis_bps:float, spot_price:float, usdtinr:float)` — unchanged.
- `_paper_feed() -> FeedSample | None` — REST, returns None on missing/empty BTC row or empty `fr`/`basis_bps`.
- `csv_feed() -> FeedSample | None` — reads last row of `reports/coindcx_venue.csv`, None if missing/empty.

- [ ] **Step 1: Write the failing demo**

Add a top-level import (after the existing `from pathlib import Path` at line 10, before `import numpy as np`):

```python
from scripts.coindcx_venue_recorder import sample as _recorder_sample
```

Add the `_demo_feed` coroutine (after `_demo_venue_gate`, before `_demo_sign`):

```python
async def _demo_feed():
    """REST paper feed reuses recorder.sample(); csv_feed reads the recorder CSV.
    --feed selection: rest (default) vs csv. Guards empty fr/basis -> None (outage)."""
    import tempfile

    # REST feed: mocked recorder.sample() -> BTC row -> FeedSample; empty fr -> None.
    good = [{"ts": 1700000000, "sym": "BTC", "fr": 0.0003, "efr": 0.00031,
             "mp": 30000, "ls": 30000, "spot_inr": 2700000, "usdtinr": 90,
             "basis_bps": 11.1}]
    import scripts.carry_trader as ct
    orig = ct._recorder_sample
    ct._recorder_sample = lambda: good
    try:
        s = await _paper_feed()
        assert s is not None and abs(s.fr - 0.0003) < 1e-12 and s.spot_price == 2700000, s
        # empty fr -> outage (None)
        ct._recorder_sample = lambda: [{"ts": 1, "sym": "BTC", "fr": None, "efr": None,
                                        "mp": 1, "ls": 1, "spot_inr": "", "usdtinr": "",
                                        "basis_bps": ""}]
        assert await _paper_feed() is None, "empty fr should be outage"
        # BTC row absent -> None
        ct._recorder_sample = lambda: [{"ts": 1, "sym": "ETH", "fr": 0.0002, "efr": 0.0002,
                                        "mp": 1, "ls": 1, "spot_inr": 1, "usdtinr": 1,
                                        "basis_bps": 0}]
        assert await _paper_feed() is None, "no BTC row -> None"
    finally:
        ct._recorder_sample = orig

    # csv_feed: write a tmp CSV, read last row -> FeedSample; missing -> None.
    td = Path(tempfile.mkdtemp())
    csvp = td / "coindcx_venue.csv"
    csvp.write_text("ts,sym,fr,efr,mp,ls,spot_inr,usdtinr,basis_bps\n"
                    "1700000060,BTC,0.0004,0.0004,30000,30000,2700000,90,11.0\n")
    s2 = csv_feed(path=csvp)
    assert s2 is not None and abs(s2.fr - 0.0004) < 1e-12 and s2.basis_bps == 11.0, s2
    assert csv_feed(path=td / "nope.csv") is None, "missing CSV -> None"
    print("carry_trader feed OK")
```

Add the call in `demo()` (after `asyncio.run(_demo_venue_gate())`):

```python
    asyncio.run(_demo_feed())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py`
Expected: FAIL — `_paper_feed` still the stub (`await asyncio.sleep(0)` returns None → `s is not None` assertion fails), `csv_feed` undefined (NameError).

- [ ] **Step 3: Implement**

Replace the stub `_paper_feed` (lines 383-384) with the REST feed:

```python
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
```

Rename `_live_feed` → `csv_feed` with an optional `path` arg (the demo passes a tmp path; production defaults to the recorder CSV). Replace the `_live_feed` block (lines 387-399) with:

```python
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
```

Update `main()` — add the `--feed` arg and selection. In the `ap.add_argument` block (after `--leverage`, before `args = ap.parse_args()`):

```python
    ap.add_argument("--feed", choices=["rest", "csv"], default="rest",
                    help="paper feed source: rest (dev, public REST) or csv (Oracle, recorder CSV)")
```

Replace the feed-selection block (lines 438-440, the `feed_fn = _live_feed` and `else: feed_fn = _paper_feed`) with:

```python
        client = CoinDCXClient()
        feed_fn = csv_feed  # --live forces csv (live runs on Oracle where the CSV exists)
    else:
        feed_fn = _paper_feed if args.feed == "rest" else csv_feed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py`
Expected: PASS — all 7 OK lines incl. `carry_trader feed OK`.

- [ ] **Step 5: ruff + commit**

```bash
.venv/Scripts/python -m ruff check scripts/carry_trader.py
git add scripts/carry_trader.py
git commit -m "feat(carry): --feed {rest,csv} paper feed (reuse recorder.sample()) + csv_feed"
```

---

### Task 2: TraderState extension + field-tolerant loader

**Files:**
- Modify: `scripts/carry_trader.py` (`TraderState`, `_load_state`, `demo`/`_demo_feed`)
- Produces: `TraderState` with `accrued_funding`, `basis_mtm`, `last_mark_ts`, `entry_basis_bps`; `_load_state` field-tolerant.

**Interfaces:**
- `TraderState` new fields (all default 0.0/0 so old state loads): `accrued_funding: float = 0.0`, `basis_mtm: float = 0.0`, `last_mark_ts: int = 0`, `entry_basis_bps: float = 0.0`.
- `_load_state(path) -> TraderState` — drops unknown keys, defaults missing (no TypeError on extra/missing).

- [ ] **Step 1: Write the failing demo**

Extend `_demo_feed` (append before `print("carry_trader feed OK")`):

```python
    # field-tolerant loader: old state (missing new fields) + unknown keys -> loads with defaults.
    import tempfile
    td2 = Path(tempfile.mkdtemp())
    old = td2 / "old_state.json"
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
    bad = td2 / "bad_state.json"
    bad.write_text("{not json")
    stb = _load_state(bad)
    assert stb.corrupt is True, "corrupt JSON -> corrupt flag"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py`
Expected: FAIL — `TraderState(**d)` raises `TypeError: __init__() got an unexpected keyword argument 'future_unknown_key'`.

- [ ] **Step 3: Implement**

Add the new fields to `TraderState` (after `last_feed_ts: int = 0`):

```python
    accrued_funding: float = 0.0   # paper PnL: cumulative funding income at 8h marks
    basis_mtm: float = 0.0         # paper PnL: unrealized basis/FX drift on open position
    last_mark_ts: int = 0          # last 8h funding-mark floor processed (for accrual)
    entry_basis_bps: float = 0.0   # basis at entry (for MTM)
```

Make `_load_state` field-tolerant — replace the `TraderState(**d)` line (line 136) with:

```python
        valid = {k: v for k, v in d.items() if k in TraderState.__dataclass_fields__}
        return TraderState(**valid)
```

(The `d.pop("corrupt", None)` above it stays; `TraderState.__dataclass_fields__` filters unknown keys; missing keys use dataclass defaults.)

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py`
Expected: PASS — all 7 OK lines; loader tolerant.

- [ ] **Step 5: ruff + commit**

```bash
.venv/Scripts/python -m ruff check scripts/carry_trader.py
git add scripts/carry_trader.py
git commit -m "feat(carry): TraderState paper-PnL fields + field-tolerant state loader"
```

---

### Task 3: Paper-PnL accounting — 8h funding accrual + basis MTM + real `_mark_equity`

**Files:**
- Modify: `scripts/carry_trader.py` (`_mark_equity`, `_enter_short`, `run_loop`, new `_accrue_funding`/`_basis_mtm`, `demo`/`_demo_paper_pnl`)
- Produces: `_accrue_funding(st, s) -> bool`, `_basis_mtm(st, s) -> float`, real `_mark_equity`; run_loop accrues at 8h marks.

**Interfaces:**
- `FUNDING_MARK_S = 8 * 3600` module constant.
- `_accrue_funding(st: TraderState, s: FeedSample) -> bool` — if `st.side == -1` and the 8h mark floor advanced (`s.ts - s.ts % FUNDING_MARK_S > st.last_mark_ts` and `st.last_mark_ts != 0`), accrue `st.accrued_funding += st.qty * s.fr * st.entry_spot`, update `st.last_mark_ts`, return True. First sample (`last_mark_ts == 0`) just seeds `st.last_mark_ts` (no accrue). Returns False otherwise.
- `_basis_mtm(st, s) -> float` — `st.qty * ((s.basis_bps - st.entry_basis_bps) / 1e4) * st.entry_spot` (INR; 0 if side==0).
- `_mark_equity(st, s) -> float` — `st.peak_equity + st.accrued_funding + _basis_mtm(st, s)` if `st.side != 0` else `st.peak_equity`.

- [ ] **Step 1: Write the failing demo**

Add a new coroutine after `_demo_feed`:

```python
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
    # equity = peak + accrued + basis_mtm = 100_000 + 270 + 450
    assert abs(_mark_equity(st, s_mark) - 100_450.0) < 1e-6, _mark_equity(st, s_mark)

    # flat -> equity is peak only
    flat = TraderState(side=0, peak_equity=100_000.0)
    assert _mark_equity(flat, s_mark) == 100_000.0
    print("carry_trader paper-pnl OK")
```

Add the call in `demo()` (after `asyncio.run(_demo_feed())`):

```python
    asyncio.run(_demo_paper_pnl())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py`
Expected: FAIL — `_accrue_funding`/`_basis_mtm` undefined (NameError); `_mark_equity` still the placeholder (`peak + funding proxy` ≠ 100_450).

- [ ] **Step 3: Implement**

Add the module constant near the top (after `REPORTS = Path("reports")`):

```python
FUNDING_MARK_S = 8 * 3600  # CoinDCX funding settlement interval (00:00/08:00/16:00 UTC)
```

Add `_accrue_funding` + `_basis_mtm` (after `_mark_equity`):

```python
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
```

Replace `_mark_equity` (lines 145-150) with:

```python
def _mark_equity(st: TraderState, s: FeedSample) -> float:
    # paper PnL equity: peak + accrued funding (8h marks) + unrealized basis/FX MTM.
    # Replaces the sub-project-1 placeholder. Real MTM deferred to Phase 2 live fills in
    # the perp/spot leg fills; here basis_mtm is the delta-neutral residual (the §29 FX leg).
    if st.side == 0:
        return st.peak_equity
    return st.peak_equity + st.accrued_funding + _basis_mtm(st, s)
```

In `_enter_short`, set `entry_basis_bps` + `peak_equity` at entry. In the paper branch (the `else: st.qty = 0.0` block, lines 173-174) and after the live branch sets `st.qty`, the shared lines 175-176 set side/entry. Update the shared tail (lines 174-176) to:

```python
    st.side = -1; st.entry_perp = s.spot_price; st.entry_spot = s.spot_price
    st.entry_basis_bps = s.basis_bps; st.peak_equity = st.peak_equity or 0.0
    log.info("ENTER_SHORT qty=%s fr=%s basis=%sbps", st.qty, s.fr, s.basis_bps)
```

(Leave `peak_equity` to grow via `run_loop`'s `max(peak_equity, eq)`; `entry_basis_bps` is the load-bearing addition. `peak_equity or 0.0` keeps the existing default-0 behavior — do NOT reset an existing peak on a re-entry.)

In `run_loop`, accrue funding each poll after the feed sample is confirmed non-None and before the DD check. After `state.last_feed_ts = s.ts` (line 92) and before the basis-stop (line 94), insert:

```python
        # paper PnL: accrue funding at 8h marks (replaces placeholder equity)
        if _accrue_funding(state, s):
            log.info("FUNDING_ACCRUE total=%s fr=%s", state.accrued_funding, s.fr)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py`
Expected: PASS — all 8 OK lines incl. `carry_trader paper-pnl OK`.

- [ ] **Step 5: ruff + commit**

```bash
.venv/Scripts/python -m ruff check scripts/carry_trader.py
git add scripts/carry_trader.py
git commit -m "feat(carry): paper-PnL accrual at 8h marks + basis MTM + real equity"
```

---

### Task 4: Paper ledger `reports/carry_paper.csv` + event logging in run_loop

**Files:**
- Modify: `scripts/carry_trader.py` (new `_paper_ledger`, wire into `run_loop`/`_enter_short`/`_flatten_all`/`_on_feed_outage`, `demo`/`_demo_paper_pnl`)
- Produces: `_paper_ledger(st, event, s, path)` append-only CSV; events `ENTER_SHORT`, `FUNDING_ACCRUE`, `BASIS_STOP`, `FLATTEN`, `DD_HALT`, `FEED_OUTAGE`.

**Interfaces:**
- `PAPER_LEDGER = REPORTS / "carry_paper.csv"` module constant.
- `_paper_ledger(st, event, s, path=PAPER_LEDGER) -> None` — appends `ts, event, side, fr, efr, basis_bps, accrued_funding, equity`. Writes a header if the file is new. `s` may be None (FEED_OUTAGE) → fr/efr/basis blank. Never raises (best-effort; ledger write failure must not crash the loop).

- [ ] **Step 1: Write the failing demo**

Extend `_demo_paper_pnl` (append before `print("carry_trader paper-pnl OK")`):

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py`
Expected: FAIL — `_paper_ledger` undefined (NameError).

- [ ] **Step 3: Implement**

Add the module constant (after `PAPER_LEDGER`... near `REPORTS`):

```python
PAPER_LEDGER = REPORTS / "carry_paper.csv"
```

Add `_paper_ledger` (after `_basis_mtm`):

```python
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
    except OSError as e:  # noqa: BLE001 - ledger is observational, never load-bearing
        log.warning("paper ledger write failed: %s", e)
```

Wire into `run_loop`:
- ENTER_SHORT: in `_enter_short`, after `log.info("ENTER_SHORT ...")`, add `if not live: _paper_ledger(st, "ENTER_SHORT", s)`. (Live mode writes real order events elsewhere; Phase 1 is paper-only — guard with `not live` so live isn't double-logging. Actually keep it simple: ledger is paper-only.)
- FUNDING_ACCRUE: in `run_loop`, change the accrual log to also ledger:
  ```python
        if _accrue_funding(state, s):
            log.info("FUNDING_ACCRUE total=%s fr=%s", state.accrued_funding, s.fr)
            _paper_ledger(state, "FUNDING_ACCRUE", s)
  ```
- BASIS_STOP: in `run_loop` basis-stop block (line 95-96), after the `log.warning("basis-stop fire...")`, add `_paper_ledger(state, "BASIS_STOP", s)` before `_flatten_all`.
- FLATTEN: in `_flatten_all`, after `st.side = 0` (line 202), add `if not live: _paper_ledger(st, "FLATTEN", None)`. (Pass the pre-flatten sample? `_flatten_all` has no `s` param — keep `None` for the FLATTEN row; the equity is peak only after side reset. Acceptable: the row records the event + accrued_funding total.)
- DD_HALT: in `run_loop` DD-halt block (line 102-104), after the `log.warning("DD halt...")`, add `_paper_ledger(state, "DD_HALT", s)` before flatten.
- FEED_OUTAGE: in `_on_feed_outage`, after the `log.warning("feed outage...")` (line 211), add `_paper_ledger(st, "FEED_OUTAGE", None)`. (Only on the sustained-outage flatten path; a single missed poll is not ledgered.)

(For the `_flatten_all`/`_on_feed_outage`/`_enter_short` ledger calls, pass `live` through — they already receive `live` as a param. Guard paper-only with `if not live`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py`
Expected: PASS — all 8 OK lines; ledger assertions hold.

- [ ] **Step 5: ruff + commit**

```bash
.venv/Scripts/python -m ruff check scripts/carry_trader.py
git add scripts/carry_trader.py
git commit -m "feat(carry): paper ledger reports/carry_paper.csv + event logging"
```

---

### Task 5: `scripts/paper_check.py` — 5-criteria verdict

**Files:**
- Create: `scripts/paper_check.py` (`__main__` `demo()` self-check, NO pytest)
- Consumes: `reports/carry_paper.csv` + `reports/carry_trader_state.json`
- Produces: `verdict(ledger_rows, state, window_d) -> dict` — the 5 criteria.

**Interfaces:**
- `CRITERIA`: zero faults (no `halted_orphan`/DD_HALT/reconcile-halt events → actually ledger has no reconcile event; criterion 1 = no `DD_HALT` and no `halted_orphan` flag in state and no `BASIS_STOP` is acceptable but flagged); feed ≥95% non-outage; ≥1 ENTER_SHORT + ≥1 FLATTEN; accrued_funding ≥ 0 + annualized within order-of-magnitude of 7%/yr; state survives restart (corrupt flag false).
- `verdict(rows, state, capital, window_d) -> dict` returns `{"pass": bool, "criteria": {1..5: bool}, "detail": str}`.

- [ ] **Step 1: Write the failing demo**

Create `scripts/paper_check.py`:

```python
"""Phase 1 paper-trader success-criteria verdict (sub-project 5).

Reads reports/carry_paper.csv + reports/carry_trader_state.json and emits the
5-criteria verdict that gates Phase 2 small-real. See spec §"Success criteria".

Usage: python scripts/paper_check.py [ledger_csv] [state_json] [capital] [window_d]
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

REPORTS = Path("reports")
CARRY_YR_TARGET = 0.07  # §20 proxy ~7%/yr (sanity, not proof)

CRITERIA = [
    "zero_faults", "feed_live", "signal_fired", "funding_nonneg", "state_clean",
]


def _read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return list(csv.DictReader(path.read_text().splitlines()))


def _read_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def verdict(rows: list[dict], state: dict, capital: float, window_d: float) -> dict:
    events = [r.get("event", "") for r in rows]
    # 1. zero faults: no DD_HALT, no halted_orphan in state, no corrupt
    c1 = ("DD_HALT" not in events) and (not state.get("halted_orphan")) and (not state.get("corrupt"))
    # 2. feed live: FEED_OUTAGE < 5% of rows
    n = len(rows) or 1
    c2 = (events.count("FEED_OUTAGE") / n) < 0.05
    # 3. signal fired: >=1 ENTER_SHORT and >=1 FLATTEN
    c3 = events.count("ENTER_SHORT") >= 1 and events.count("FLATTEN") >= 1
    # 4. funding non-negative + annualized within order-of-magnitude of 7%/yr
    accrued = state.get("accrued_funding", 0.0)
    yr = max(window_d / 365.0, 1e-9)
    ann = (accrued / capital) / yr if capital else 0.0
    c4 = accrued >= 0 and ann <= CARRY_YR_TARGET * 10  # within 10x of 7%/yr (order of magnitude)
    # 5. state clean: not halted (a planned end-of-window stop is fine; an unplanned halt fails c1)
    c5 = not state.get("halted", False)
    crit = {CRITERIA[i]: c for i, c in enumerate([c1, c2, c3, c4, c5])}
    return {"pass": all(crit.values()), "criteria": crit,
            "detail": f"accrued={accrued} ann={ann:.4f} events={len(rows)}"}


def demo() -> None:
    import tempfile
    td = Path(tempfile.mkdtemp())
    # pass case: 10 rows, an ENTER_SHORT + FLATTEN, no faults, accrued positive, state clean
    lp = td / "carry_paper.csv"
    lp.write_text("ts,event,side,fr,efr,basis_bps,accrued_funding,equity\n"
                  "1,ENTER_SHORT,-1,0.0003,0.0003,10,0,100000\n"
                  "2,FUNDING_ACCRUE,-1,0.0003,0.0003,10,270,100270\n"
                  "3,FLATTEN,0,,,0,270,100270\n")
    sp = td / "state.json"
    sp.write_text(json.dumps({"accrued_funding": 270.0, "halted": False, "halted_orphan": False, "corrupt": False}))
    v = verdict(_read_ledger(lp), _read_state(sp), capital=100_000.0, window_d=14.0)
    assert v["pass"] is True, v
    assert all(v["criteria"].values()), v
    # fail case: a DD_HALT -> criterion 1 fails
    lp.write_text("ts,event,side,fr,efr,basis_bps,accrued_funding,equity\n"
                  "1,ENTER_SHORT,-1,0.0003,0.0003,10,0,100000\n"
                  "2,DD_HALT,0,,,0,-5000,75000\n")
    sp.write_text(json.dumps({"accrued_funding": -5000.0, "halted": True, "halted_orphan": False, "corrupt": False}))
    vf = verdict(_read_ledger(lp), _read_state(sp), capital=100_000.0, window_d=14.0)
    assert vf["pass"] is False and vf["criteria"]["zero_faults"] is False, vf
    print("paper_check OK")


def main() -> None:
    import sys
    ledger = Path(sys.argv[1]) if len(sys.argv) > 1 else (REPORTS / "carry_paper.csv")
    state = Path(sys.argv[2]) if len(sys.argv) > 2 else (REPORTS / "carry_trader_state.json")
    capital = float(sys.argv[3]) if len(sys.argv) > 3 else 100_000.0
    window_d = float(sys.argv[4]) if len(sys.argv) > 4 else 14.0
    v = verdict(_read_ledger(ledger), _read_state(state), capital, window_d)
    print(json.dumps(v, indent=2))
    print("PASS" if v["pass"] else "FAIL")


if __name__ == "__main__":
    demo()
```

- [ ] **Step 2: Run test to verify it fails then passes**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/paper_check.py`
Expected: `paper_check OK` (this is a new file — step 1 writes the demo AND the impl together since the verdict logic is the deliverable; run to confirm the assertions hold).

- [ ] **Step 3: ruff + commit**

```bash
.venv/Scripts/python -m ruff check scripts/paper_check.py
git add scripts/paper_check.py
git commit -m "feat(paper): paper_check.py 5-criteria verdict for Phase 2 gate"
```

---

### Task 6: Oracle deploy artifacts (systemd unit + README)

**Files:**
- Create: `deploy/carry-paper.service` (systemd unit)
- Create: `deploy/README.md` (deploy steps)
- No code; no self-check (config + docs).

- [ ] **Step 1: Write the systemd unit**

`deploy/carry-paper.service`:

```ini
[Unit]
Description=CoinDCX carry paper-trader (Phase 1, --feed csv, no orders)
After=network-online.target coindcx-venue-recorder.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/trading
Environment=PYTHONPATH=/opt/trading
ExecStart=/opt/trading/.venv/bin/python scripts/carry_trader.py --feed csv --pair B-BTC_USDT --spot-pair BTCINR --leverage 3
Restart=always
RestartSec=15
StandardOutput=append:/var/log/carry-paper.log
StandardError=append:/var/log/carry-paper.log

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Write the README**

`deploy/README.md`:

```markdown
# Phase 1 paper-trader deploy (Oracle Cloud)

Runs the carry trader in PAPER mode (`--feed csv`, no `--live`, no orders) alongside the recorder.

## Prerequisites on the Oracle host
1. Repo cloned at `/opt/trading` with `.venv` + `.env` (API keys).
2. `coindcx_venue_recorder` already running as systemd, writing `reports/coindcx_venue.csv` 24/7 (since 2026-08-07).

## Deploy
```bash
sudo cp deploy/carry-paper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now carry-paper.service
sudo journalctl -u carry-paper.service -f   # or tail /var/log/carry-paper.log
```

## Definitive Phase 0 venue verdict (one-shot, same host — CSV present)
```bash
cd /opt/trading
.venv/bin/python scripts/venue_verify.py run
cat reports/venue_verify.json   # verdict: PASS -> Phase 0 done, --live unlocked for Phase 2
                                 # fx_conversion FAIL -> redesign_required, hedge-redesign mandated
```

## Success criteria (7-14d)
```bash
.venv/bin/python scripts/paper_check.py reports/carry_paper.csv reports/carry_trader_state.json 100000 14
```
PASS on all 5 criteria -> Phase 2 small-real unlocked. See spec §"Success criteria".

## Notes
- Paper mode places NO orders. `--live` is NOT set; the Phase 0 gate does not block paper.
- State persists across restarts (`reports/carry_trader_state.json`); `Restart=always` resumes.
- Recorder MUST run first (the unit `After=` it, but confirm `reports/coindcx_venue.csv` is growing).
```

- [ ] **Step 3: Commit**

```bash
git add deploy/carry-paper.service deploy/README.md
git commit -m "feat(deploy): Oracle systemd unit + README for Phase 1 paper-trader"
```

---

### Task 7: §33 appendix + final verify

**Files:**
- Modify: `docs/strategies_report.md` (append §33 after §32)
- Verification only (no code).

- [ ] **Step 1: Append §33**

Append §33: the Phase 1 paper-trader sub-project — two-feed design (`--feed {rest,csv}`, REST reuses `recorder.sample()`, CSV extracted from `_live_feed`), paper-PnL accounting (8h funding accrual + basis MTM replacing the placeholder equity), paper ledger `reports/carry_paper.csv`, Oracle systemd deploy + definitive `venue_verify.py run`, 5-criteria success gate (`paper_check.py`), no-orders paper constraint. Match §30/§31/§32 tone (sectioned `### 33.x` + conclusion). Status: "awaiting Oracle deploy + first 7-14d run" (no paper run executed in this environment). Cross-refs `[[funding-carry-band]]` (§20), `[[post-conclusion-followups]]` (§29), `[[microstructure-feed-unblocked]]` (recorder), `[[regime-gate-tilt-sweep]]` (§31 NoTilt).

- [ ] **Step 2: Final verify (all self-checks)**

```bash
PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py
PYTHONPATH=. .venv/Scripts/python scripts/paper_check.py
PYTHONPATH=. .venv/Scripts/python scripts/venue_verify.py
PYTHONPATH=. .venv/Scripts/python scripts/regime_gate_wf.py
PYTHONPATH=. .venv/Scripts/python scripts/regime_gates.py
PYTHONPATH=. .venv/Scripts/python scripts/tilt_signal.py
PYTHONPATH=. .venv/Scripts/python scripts/risk_budget.py
PYTHONPATH=. .venv/Scripts/python -m pytest tests/test_exchange.py -q
.venv/Scripts/python -m ruff check scripts/carry_trader.py scripts/paper_check.py scripts/venue_verify.py
```
Expected: `carry_trader` 8 OK lines (signal/faults/reconcile/sign/tilt/venue/feed/paper-pnl); `paper_check OK`; `venue_verify all probes + gate OK`; others unchanged OK; pytest 4/4; ruff clean.

- [ ] **Step 3: Commit**

```bash
git add docs/strategies_report.md
git commit -m "docs(research): §33 Phase 1 paper-trader (sub-project 5)"
```

---

## Self-Review

**1. Spec coverage:**
- Two feeds (`--feed {rest,csv}`) → Task 1. ✓
- REST reuses `recorder.sample()` → Task 1. ✓
- CSV extracted from `_live_feed` → Task 1 (`csv_feed`). ✓
- Paper-PnL (8h accrual + basis MTM, replaces placeholder) → Task 3. ✓
- Paper ledger → Task 4. ✓
- Oracle systemd + `venue_verify.py run` → Task 6. ✓
- 5-criteria verdict + `paper_check.py` → Task 5. ✓
- §33 appendix → Task 7. ✓
- Field-tolerant loader (open question) → Task 2. ✓
- 8h mark schedule (open question) → Task 3 (`FUNDING_MARK_S`, confirm-on-first-run noted). ✓
- No orders / `--live` untouched → no task touches the live order path; `--live` still forces csv + gate (Task 1). ✓
- Error handling (feed outage → None, mark gap, corrupt state, DD halt, venue FAIL) → Tasks 1/3/4 + existing `_on_feed_outage`/reconcile. ✓

**2. Placeholder scan:** Task 6 systemd paths are concrete (`/opt/trading` — the recorder's documented host path). Task 7 §33 content is described by required elements, not TBD. No "add error handling" without code. ✓

**3. Type consistency:** `FeedSample(ts, fr, efr, basis_bps, spot_price, usdtinr)` unchanged. `TraderState` new fields (`accrued_funding`, `basis_mtm`, `last_mark_ts`, `entry_basis_bps`) used consistently in Tasks 2/3/4. `_accrue_funding(st, s) -> bool`, `_basis_mtm(st, s) -> float`, `_paper_ledger(st, event, s, path)`, `csv_feed(path) -> FeedSample|None` — signatures stable across tasks. `verdict(rows, state, capital, window_d) -> dict` Task 5. ✓

**4. Demo regression guard:** The 6 existing OK lines (signal/faults/reconcile/sign/tilt/venue) are untouched; `_demo_feed` + `_demo_paper_pnl` added. `_demo_faults` calls `_enter_short` — Task 3 adds `entry_basis_bps`/`peak_equity or 0.0` to the shared entry tail; the orphan path resets `side=0` before any equity check, so the existing `st.side==0 and st.halted_orphan` assertion holds. ✓ (verify in Task 3 review.)

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-25-phase1-paper-trader.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?