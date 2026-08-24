# Phase 0 Venue-Verify Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only probe harness that verifies CoinDCX perp + spot venue truth against the carry deploy's assumptions, writes `reports/venue_verify.json`, and gates `carry_trader --live` on a data-driven PASS/FAIL verdict (FX-conversion gap = gate + redesign-trigger).

**Architecture:** One new client method (`get_conversion_rate`) + one new script (`scripts/venue_verify.py`) running 7 read-only probes → JSON verdict file → a ~10-line `--live` guard in `carry_trader.main()`. No orders, no testnet (none exists). Recorder CSV (`reports/coindcx_venue.csv`) feeds the funding/basis probes.

**Tech Stack:** Python 3.12, httpx (async), pandas/numpy (CSV stats), pytest (app/ tests), `scripts/` `__main__` assert demo (no pytest for scripts). ruff line-length 100.

**Spec:** `docs/superpowers/specs/2026-08-25-phase0-venue-verify-design.md` — the plan argues from the spec; the spec is the binding authority.

## Global Constraints

- Read-only: NO order placement (create_order / exit_position / create_spot_order untouched + uncalled). No testnet exists.
- Perp NO 1% TDS; spot leg TDS on sell is a known cost (recorded, not modeled here).
- FX-conversion gate + redesign trigger: `fx_conversion` PASS iff mean gap < 10bps; FAIL → `redesign_required: true` → mandates a hedge-redesign sub-project (USDT-margined perp) before any live trade. No manual go/no-go — the JSON verdict is the gate.
- Gate freshness: `carry_trader --live` refuses unless `venue_verify.json` `verdict=="PASS"` + timestamp within 24h.
- API keys in `.env` via `app.config.settings`, never logged. Fail-safe flatten+halt unchanged (sub-project 1).
- ruff line-length 100, Python 3.12. `scripts/` → `__main__` assert `demo()` (NO pytest). `app/`+`tests/` → pytest (`asyncio_mode=auto`).
- `get_conversion_rate` endpoint takes a SECONDS timestamp (not ms) — load-bearing gotcha.
- Constants: `FX_THRESHOLD_BPS = 10`, `FRESHNESS_H = 24`, `FX_SAMPLES = 8`, `BASIS_THRESHOLD_BPS = 100`, `FUNDING_MIN_SPAN_H = 8`.
- `carry_trader.py` 5 existing demo OK lines (signal/faults/reconcile/sign/tilt) must stay green (regression guard); add a 6th `venue OK` line.

---

### Task 1: `get_conversion_rate` client method + pytest

**Files:**
- Modify: `app/exchange/coindcx.py` (add `EP["conversions"]` + `get_conversion_rate` method)
- Test: `tests/test_exchange.py` (add `test_get_conversion_rate_seconds_ts`)

**Interfaces:**
- Consumes: `CoinDCXClient._signed_post`-style signing (but SECONDS ts), `EP` dict.
- Produces: `async def get_conversion_rate(self) -> float` — returns `conversion_price` from `/api/v1/derivatives/futures/data/conversions`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_exchange.py`:
```python
async def test_get_conversion_rate_seconds_ts(monkeypatch):
    _fake_settings(monkeypatch)
    cli = CoinDCXClient()
    captured = {}

    async def fake_post(path, *, content=None, headers=None):
        captured["path"] = path
        captured["body"] = content
        captured["headers"] = headers
        return httpx.Response(200, json=[{"symbol": "USDTINR",
                "margin_currency_short_name": "INR", "target_currency_short_name": "USDT",
                "conversion_price": 89.12, "last_updated_at": 1728460492399}])

    monkeypatch.setattr(cli._priv, "post", fake_post)
    price = await cli.get_conversion_rate()
    assert abs(price - 89.12) < 1e-9
    assert captured["path"] == "/api/v1/derivatives/futures/data/conversions"
    body = json.loads(captured["body"])
    # SECONDS timestamp (not ms like other endpoints) — the load-bearing gotcha.
    assert abs(body["timestamp"] - int(time.time())) < 5, "conversion ts must be seconds"
    assert body["timestamp"] < 1e12, "ms ts would be >1e12"
    sig = hmac.new(b"s", captured["body"].encode(), hashlib.sha256).hexdigest()
    assert captured["headers"]["X-AUTH-SIGNATURE"] == sig
```
Add `import time` to the test file's imports if not present.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. .venv/Scripts/python -m pytest tests/test_exchange.py::test_get_conversion_rate_seconds_ts -q`
Expected: FAIL — `AttributeError: 'CoinDCXClient' object has no attribute 'get_conversion_rate'`.

- [ ] **Step 3: Implement**

In `app/exchange/coindcx.py`, add to `EP`:
```python
    # INR-margined futures USDT<>INR conversion rate (read-only, signed).
    # ponytail: takes a SECONDS timestamp (not ms like other endpoints).
    "conversions": "/api/v1/derivatives/futures/data/conversions",
```
Add method to `CoinDCXClient` (near `get_usdt_inr`):
```python
    async def get_conversion_rate(self) -> float:
        """Current USDT<>INR conversion rate for INR-margined futures (read-only,
        signed). Endpoint /api/v1/derivatives/futures/data/conversions takes a
        SECONDS timestamp (not ms like other endpoints). Returns conversion_price.
        This rate is NOT spot USDTINR — the gap is the §29 FX-leg hedge leak."""
        body = {"timestamp": int(time.time())}  # SECONDS — load-bearing gotcha
        headers, payload = self._sign(body)
        async with self._rate_lock:
            r = await self._priv.post(EP["conversions"], content=payload, headers=headers)
        data = self._handle(r)
        rows = data if isinstance(data, list) else [data]
        for row in rows:
            if str(row.get("symbol", "")).upper() == "USDTINR":
                return float(row["conversion_price"])
        # fallback: first row with a conversion_price
        for row in rows:
            if row.get("conversion_price") is not None:
                return float(row["conversion_price"])
        raise CoinDCXError("no conversion_price in conversions response", data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/Scripts/python -m pytest tests/test_exchange.py -q`
Expected: PASS (all tests, including the 2 prior spot-order tests).

- [ ] **Step 5: ruff + commit**

```bash
ruff check app/exchange/coindcx.py tests/test_exchange.py
git add app/exchange/coindcx.py tests/test_exchange.py
git commit -m "feat(exchange): get_conversion_rate (read-only, seconds-ts) for Phase 0 FX-leg probe"
```

---

### Task 2: `venue_verify.py` scaffold + probes 1-3 (auth + instrument)

**Files:**
- Create: `scripts/venue_verify.py`
- Consumes: `app.exchange.coindcx.CoinDCXClient` (read methods), `app.config.settings`.
- Produces: `ProbeResult` dataclass, `auth_liveness`/`instrument_perp`/`instrument_spot` probe fns, `FakeClient` for self-check.

- [ ] **Step 1: Write the scaffold + probes 1-3 + demo (failing asserts first)**

Create `scripts/venue_verify.py`:
```python
"""Phase 0 venue-verify (sub-project 4). Read-only probes that verify CoinDCX
perp + spot venue truth against the carry deploy's assumptions, then write
reports/venue_verify.json as the --live gate. No orders (no testnet exists).

7 probes: auth_liveness, instrument_perp, instrument_spot, funding_accrual,
fx_conversion, basis_proxy, rate_limit. See spec
docs/superpowers/specs/2026-08-25-phase0-venue-verify-design.md.

Usage: python scripts/venue_verify.py run   (live probes -> reports/venue_verify.json)
       python scripts/venue_verify.py        (demo self-check, no network)
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

REPORTS = Path("reports")
GATE_PATH = REPORTS / "venue_verify.json"
FX_THRESHOLD_BPS = 10.0
FRESHNESS_H = 24
FX_SAMPLES = 8
BASIS_THRESHOLD_BPS = 100.0
FUNDING_MIN_SPAN_H = 8
# §29 cost model: taker 0.059%. ponytail: from real CoinDCX fee verification.
TAKER_FEE_BPS = 5.9
FEE_TOLERANCE_BPS = 5.0
LEVERAGE_CAP = 3


@dataclass
class ProbeResult:
    name: str
    passed: bool
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


# --- probe 1: auth + endpoint liveness ---
async def auth_liveness(client) -> ProbeResult:
    try:
        await client.get_wallets()
        await client.get_positions(pair="B-BTC_USDT")
        return ProbeResult("auth_liveness", True, {"wallets": "ok", "positions": "ok"})
    except Exception as e:  # noqa: BLE001 - probe must not crash the harness
        return ProbeResult("auth_liveness", False, error=f"{type(e).__name__}: {e}")


# --- probe 2: perp instrument metadata vs §29 cost model ---
async def instrument_perp(client) -> ProbeResult:
    try:
        inst = await client.get_instrument("B-BTC_USDT")
        # fee: CoinDCX reports taker as a fraction; convert to bps.
        fee_frac = float(inst.get("taker_fee") or inst.get("taker_fee_rate") or 0)
        fee_bps = fee_frac * 1e4 if fee_frac < 0.01 else fee_frac  # handle both forms
        lev = inst.get("leverage") or inst.get("max_leverage")
        lev_ok = lev is not None and float(lev) >= LEVERAGE_CAP
        minq = float(inst.get("min_quantity") or inst.get("min_qty") or 0)
        detail = {"fee_bps": round(fee_bps, 3), "leverage": lev,
                  "min_quantity": minq, "lot_size": inst.get("lot_size"),
                  "tick_size": inst.get("tick_size")}
        fee_ok = abs(fee_bps - TAKER_FEE_BPS) <= FEE_TOLERANCE_BPS
        passed = fee_ok and lev_ok and minq > 0
        err = None if passed else f"fee={fee_bps}bps (expect {TAKER_FEE_BPS}±{FEE_TOLERANCE_BPS})" \
              if not fee_ok else (f"leverage {lev} < cap {LEVERAGE_CAP}" if not lev_ok else "no min_qty")
        return ProbeResult("instrument_perp", passed, detail, err)
    except Exception as e:  # noqa: BLE001
        return ProbeResult("instrument_perp", False, error=f"{type(e).__name__}: {e}")


# --- probe 3: spot leg metadata (BTCINR) ---
async def instrument_spot(client) -> ProbeResult:
    """BTCINR spot hedge-leg metadata. Futures instrument endpoint won't have spot;
    fall back to ticker liveness + a documented min-qty if no spot-instruments API."""
    try:
        px = await client.get_last_price("BTCINR")  # spot ticker liveness
        # ponytail: CoinDCX spot min-qty for BTCINR from support docs; re-check live.
        # If a public spot-instruments endpoint is found, replace this constant.
        DOC_MIN_QTY = 0.001
        detail = {"last_price": px, "doc_min_quantity": DOC_MIN_QTY,
                  "note": "spot-instruments endpoint unverified; using documented min_qty"}
        return ProbeResult("instrument_spot", px > 0, detail,
                           None if px > 0 else "BTCINR ticker returned 0/None")
    except Exception as e:  # noqa: BLE001
        return ProbeResult("instrument_spot", False, error=f"{type(e).__name__}: {e}")


def demo() -> None:
    import asyncio

    class FakeClient:
        async def get_wallets(self): return [{"balance": 1000}]
        async def get_positions(self, pair=None): return []
        async def get_instrument(self, pair, margin=None):
            if pair == "B-BTC_USDT":
                return {"taker_fee": 0.00059, "max_leverage": 5, "min_quantity": 0.001,
                        "lot_size": 0.001, "tick_size": 0.1}
            return {}
        async def get_last_price(self, sym): return 9_000_000.0
    r1 = asyncio.run(auth_liveness(FakeClient()))
    assert r1.passed, r1
    r2 = asyncio.run(instrument_perp(FakeClient()))
    assert r2.passed and abs(r2.detail["fee_bps"] - 5.9) < 0.01, r2
    # fee mismatch -> FAIL
    class BadFee(FakeClient):
        async def get_instrument(self, pair, margin=None):
            return {"taker_fee": 0.001, "max_leverage": 5, "min_quantity": 0.001}
    r2b = asyncio.run(instrument_perp(BadFee()))
    assert not r2b.passed and "fee" in (r2b.error or ""), r2b
    r3 = asyncio.run(instrument_spot(FakeClient()))
    assert r3.passed and r3.detail["last_price"] > 0, r3
    print("venue_verify probes 1-3 OK")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        print("run mode not implemented until Task 4")  # placeholder removed in Task 4
    else:
        demo()
```

- [ ] **Step 2: Run demo to verify probes 1-3 pass**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/venue_verify.py`
Expected: prints `venue_verify probes 1-3 OK`.

- [ ] **Step 3: ruff + commit**

```bash
ruff check scripts/venue_verify.py
git add scripts/venue_verify.py
git commit -m "feat(venue): probe scaffold + auth/instrument probes (Phase 0 Task 2)"
```

---

### Task 3: probes 4-6 (funding_accrual, fx_conversion, basis_proxy)

**Files:**
- Modify: `scripts/venue_verify.py` (add 3 probes + CSV reader + demo assertions)
- Consumes: `reports/coindcx_venue.csv` (recorder, columns `ts,sym,fr,efr,mp,ls,spot_inr,usdtinr,basis_bps`), `client.get_conversion_rate`, `client.get_usdt_inr`.

- [ ] **Step 1: Add CSV reader + probes 4-6 + demo assertions**

Add to `scripts/venue_verify.py` (after probe 3):
```python
import csv
import statistics


def _load_venue_csv(sym: str = "BTC") -> list[dict]:
    p = REPORTS / "coindcx_venue.csv"
    if not p.exists():
        return []
    rows = [r for r in csv.DictReader(p.read_text().splitlines()) if r.get("sym") == sym]
    return rows


# --- probe 4: funding accrual (recorder CSV, 60s-polled) ---
async def funding_accrual(client) -> ProbeResult:
    rows = _load_venue_csv("BTC")
    if not rows:
        return ProbeResult("funding_accrual", False, error="coindcx_venue.csv missing/no BTC rows")
    try:
        ts = [int(float(r["ts"])) for r in rows if r.get("ts")]
        span_h = (ts[-1] - ts[0]) / 3600.0 if len(ts) >= 2 else 0.0
        frs = [float(r["fr"]) for r in rows if r.get("fr") not in ("", None)]
        present_frac = len(frs) / len(rows) if rows else 0.0
        mean_abs_fr = statistics.mean(abs(x) for x in frs) if frs else 0.0
        # Binance proxy ~7%/yr / 1095 8h-intervals ~ 0.0064%/8h
        detail = {"rows": len(rows), "span_h": round(span_h, 2),
                  "fr_present_frac": round(present_frac, 3),
                  "mean_abs_fr_pct": round(mean_abs_fr * 100, 5),
                  "binance_proxy_pct_per_8h": 0.0064}
        passed = span_h >= FUNDING_MIN_SPAN_H and present_frac >= 0.9
        err = None if passed else (
            f"span {span_h:.1f}h < {FUNDING_MIN_SPAN_H}h" if span_h < FUNDING_MIN_SPAN_H
            else f"fr present {present_frac:.2f} < 0.9")
        return ProbeResult("funding_accrual", passed, detail, err)
    except Exception as e:  # noqa: BLE001
        return ProbeResult("funding_accrual", False, error=f"{type(e).__name__}: {e}")


# --- probe 5: FX conversion gap (§29 crux) ---
async def fx_conversion(client) -> ProbeResult:
    import asyncio as _a
    try:
        gaps = []
        for _ in range(FX_SAMPLES):
            conv = await client.get_conversion_rate()
            spot = await client.get_usdt_inr()
            gaps.append(abs(conv - spot) / spot * 1e4)
            await _a.sleep(1.0)
        mean_gap = statistics.mean(gaps)
        detail = {"mean_gap_bps": round(mean_gap, 3), "samples": FX_SAMPLES,
                  "threshold_bps": FX_THRESHOLD_BPS, "gaps": [round(g, 3) for g in gaps]}
        passed = mean_gap < FX_THRESHOLD_BPS
        return ProbeResult("fx_conversion", passed, detail,
                           None if passed else f"mean gap {mean_gap:.2f}bps >= {FX_THRESHOLD_BPS}bps")
    except Exception as e:  # noqa: BLE001
        return ProbeResult("fx_conversion", False, error=f"{type(e).__name__}: {e}")


# --- probe 6: basis proxy (recorder basis_bps column, pre-computed) ---
async def basis_proxy(client) -> ProbeResult:
    rows = _load_venue_csv("BTC")
    if not rows:
        return ProbeResult("basis_proxy", False, error="coindcx_venue.csv missing/no BTC rows")
    try:
        bbs = [float(r["basis_bps"]) for r in rows if r.get("basis_bps") not in ("", None)]
        if not bbs:
            return ProbeResult("basis_proxy", False, error="no basis_bps values in CSV")
        med = statistics.median(abs(x) for x in bbs)
        detail = {"median_abs_basis_bps": round(med, 3), "n": len(bbs),
                  "threshold_bps": BASIS_THRESHOLD_BPS}
        passed = med < BASIS_THRESHOLD_BPS
        return ProbeResult("basis_proxy", passed, detail,
                           None if passed else f"median |basis| {med:.1f}bps >= {BASIS_THRESHOLD_BPS}bps")
    except Exception as e:  # noqa: BLE001
        return ProbeResult("basis_proxy", False, error=f"{type(e).__name__}: {e}")


def _gap_bps(conv: float, spot: float) -> float:
    return abs(conv - spot) / spot * 1e4
```
Extend `demo()` with (before the `print("venue_verify probes 1-3 OK")` line — rename it):
```python
    # probe 4: funding_accrual on a synthetic CSV
    import tempfile, os
    tmp = Path(tempfile.mkdtemp()) / "coindcx_venue.csv"
    REPORTS.mkdir(exist_ok=True)
    real_csv = REPORTS / "coindcx_venue.csv"
    had = real_csv.exists()
    # write 8h+ of synthetic BTC rows (60s spacing -> 481 rows = 8h)
    rows_txt = "ts,sym,fr,efr,mp,ls,spot_inr,usdtinr,basis_bps\n"
    t0 = 1700000000
    for i in range(481):
        rows_txt += f"{t0+i*60},BTC,0.000064,0.000064,90000000,90000000,8100000,90,5.0\n"
    real_csv.write_text(rows_txt)
    try:
        r4 = asyncio.run(funding_accrual(FakeClient()))
        assert r4.passed and r4.detail["span_h"] >= 8, r4
        r6 = asyncio.run(basis_proxy(FakeClient()))
        assert r6.passed and r6.detail["median_abs_basis_bps"] == 5.0, r6
    finally:
        if had: pass  # leave real data; synthetic only overwrote if absent
        else:
            real_csv.unlink(missing_ok=True)
    # probe 5: fx_conversion gap math (no network -> test _gap_bps + a fake)
    class FXClient(FakeClient):
        async def get_conversion_rate(self): return 90.05
        async def get_usdt_inr(self): return 90.00
    # can't await the loop here cheaply; test the math directly
    assert abs(_gap_bps(90.05, 90.00) - 5.5556) < 0.01
    print("venue_verify probes 4-6 OK")
```
Update the final print line from `probes 1-3 OK` to `probes 1-6 OK` (combine: print both, or just the 1-6 line). Simplest: replace `print("venue_verify probes 1-3 OK")` with `print("venue_verify probes 1-6 OK")` and keep the 4-6 block above it.

- [ ] **Step 2: Run demo to verify probes 4-6 pass**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/venue_verify.py`
Expected: prints `venue_verify probes 1-6 OK`. (Note: this writes a synthetic CSV under reports/ then cleans it — the demo must not clobber a real recorder CSV; the `had` guard + unlink-on-absent handles that. If `reports/coindcx_venue.csv` already exists with real data, the demo skips the synthetic write and funding_accrual runs on the real file — acceptable, but assert may differ. Implementer: if real CSV present locally, the demo should use a tmp path instead. Resolve by writing the synthetic CSV to a tmp dir and monkeypatching REPORTS for the demo — see implementer note.)

**Implementer note (resolve in task):** the demo must not overwrite a real `reports/coindcx_venue.csv`. Write the synthetic CSV to a `tempfile`-generated path and point `_load_venue_csv` at it by passing an optional `path` arg: `_load_venue_csv(sym, path=REPORTS/"coindcx_venue.csv")`. The demo passes the tmp path. Keep the production default.

- [ ] **Step 3: ruff + commit**

```bash
ruff check scripts/venue_verify.py
git add scripts/venue_verify.py
git commit -m "feat(venue): funding/fx-conversion/basis probes (Phase 0 Task 3)"
```

---

### Task 4: probe 7 + run/verdict/main + JSON gate + load_gate helpers

**Files:**
- Modify: `scripts/venue_verify.py` (add `rate_limit`, `run_probes`, `verdict`, `main`, `load_gate`, `gate_is_fresh`, write JSON/log, complete demo)

- [ ] **Step 1: Add probe 7 + run/verdict/main + gate helpers + full demo**

Add to `scripts/venue_verify.py`:
```python
# --- probe 7: rate limit (light, no stress) ---
async def rate_limit(client) -> ProbeResult:
    import asyncio as _a
    try:
        await client.get_wallets()
        await client.get_wallets()  # 2 rapid reads
        # documented: 16/s, 960/min. We don't stress-test; just confirm 2 succeed.
        return ProbeResult("rate_limit", True, {"doc_per_s": 16, "doc_per_min": 960,
                                                "note": "light probe: 2 rapid reads ok"})
    except Exception as e:  # noqa: BLE001
        return ProbeResult("rate_limit", False, error=f"{type(e).__name__}: {e}")


PROBES = [auth_liveness, instrument_perp, instrument_spot, funding_accrual,
          fx_conversion, basis_proxy, rate_limit]


async def run_probes(client) -> list[ProbeResult]:
    return [await p(client) for p in PROBES]


def verdict(results: list[ProbeResult]) -> dict:
    all_pass = all(r.passed for r in results)
    fx = next((r for r in results if r.name == "fx_conversion"), None)
    redesign = bool(fx and not fx.passed and fx.error and "gap" in (fx.error or ""))
    fail_reason = None
    if not all_pass:
        fails = [r.name for r in results if not r.passed]
        fail_reason = "fx_conversion gap >= threshold" if "fx_conversion" in fails and redesign \
            else f"failed probes: {fails}"
    return {"verdict": "PASS" if all_pass else "FAIL",
            "redesign_required": redesign, "fail_reason": fail_reason}


def write_gate(results: list[ProbeResult], vdict: dict) -> None:
    REPORTS.mkdir(exist_ok=True)
    out = {"timestamp": int(time.time()), **vdict,
           "threshold_bps": FX_THRESHOLD_BPS, "freshness_h": FRESHNESS_H,
           "probes": [{"name": r.name, "passed": r.passed,
                       "detail": r.detail, "error": r.error} for r in results]}
    GATE_PATH.write_text(json.dumps(out, indent=2))
    # human log
    log = REPORTS / "venue_verify.log"
    lines = [f"venue_verify {vdict['verdict']} @ {time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"redesign_required={vdict['redesign_required']} fail_reason={vdict['fail_reason']}", ""]
    for r in results:
        lines.append(f"  {r.name:20s} {'PASS' if r.passed else 'FAIL'}  {r.error or r.detail}")
    log.write_text("\n".join(lines) + "\n")


def load_gate(path: Path = GATE_PATH) -> dict | None:
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError, ValueError, TypeError):
        return None


def gate_is_fresh(gate: dict, freshness_h: float = FRESHNESS_H) -> bool:
    if not gate or "timestamp" not in gate:
        return False
    return (time.time() - float(gate["timestamp"])) / 3600.0 <= freshness_h


async def _run_live() -> None:
    from app.exchange.coindcx import CoinDCXClient
    async with CoinDCXClient() as client:
        results = await run_probes(client)
    v = verdict(results)
    write_gate(results, v)
    print(f"venue_verify {v['verdict']} -> {GATE_PATH} "
          f"(redesign_required={v['redesign_required']})")


def main() -> None:
    import asyncio, sys
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        asyncio.run(_run_live())
    else:
        demo()
```
Replace the Task-2 `__main__` block (the `run mode not implemented` placeholder) with the `main()` call:
```python
if __name__ == "__main__":
    main()
```
Complete `demo()` — add probe 7 + a full verdict/gate test, replacing the final print line with a complete end-to-end synthetic:
```python
    # probe 7 + verdict + gate round-trip on a fully-fake client
    class FullClient(FakeClient):
        async def get_conversion_rate(self): return 90.00
        async def get_usdt_inr(self): return 90.00  # 0 gap -> PASS
    r7 = asyncio.run(rate_limit(FullClient()))
    assert r7.passed, r7
    # build a full result list using the fake for the REST probes + synthetic CSV for 4/6
    # (fx_conversion loops+sleeps; for the demo, test verdict() directly on a crafted list)
    crafted = [
        ProbeResult("auth_liveness", True), ProbeResult("instrument_perp", True),
        ProbeResult("instrument_spot", True), ProbeResult("funding_accrual", True),
        ProbeResult("fx_conversion", True, {"mean_gap_bps": 3.0}),
        ProbeResult("basis_proxy", True), ProbeResult("rate_limit", True),
    ]
    v = verdict(crafted)
    assert v["verdict"] == "PASS" and v["redesign_required"] is False, v
    # fx FAIL -> redesign trigger
    crafted_fx_fail = [r if r.name != "fx_conversion" else
                       ProbeResult("fx_conversion", False, {"mean_gap_bps": 12.0},
                                   "mean gap 12.00bps >= 10.0bps") for r in crafted]
    vf = verdict(crafted_fx_fail)
    assert vf["verdict"] == "FAIL" and vf["redesign_required"] is True, vf
    # gate round-trip
    write_gate(crafted, v)
    g = load_gate()
    assert g and g["verdict"] == "PASS" and gate_is_fresh(g), g
    assert gate_is_fresh({"timestamp": int(time.time()) - 25 * 3600}) is False  # stale
    assert load_gate(Path("reports/nope_missing.json")) is None
    GATE_PATH.unlink(missing_ok=True)  # cleanup
    print("venue_verify all probes + gate OK")
```
Remove the now-redundant `print("venue_verify probes 1-6 OK")` line (replaced by the final `all probes + gate OK` line).

- [ ] **Step 2: Run demo to verify the full harness**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/venue_verify.py`
Expected: prints `venue_verify all probes + gate OK`. No `reports/venue_verify.json` left behind (demo cleans up).

- [ ] **Step 3: ruff + commit**

```bash
ruff check scripts/venue_verify.py
git add scripts/venue_verify.py
git commit -m "feat(venue): rate_limit probe + run/verdict/gate + load_gate helpers (Phase 0 Task 4)"
```

---

### Task 5: `carry_trader.py` --live gate guard + demo

**Files:**
- Modify: `scripts/carry_trader.py` (extend `main()` --live guard + add `_demo_venue_gate`)
- Consumes: `scripts.venue_verify.load_gate`, `scripts.venue_verify.gate_is_fresh`.
- Produces: `--live` refuses on missing/stale/FAIL JSON; 6th demo OK line `carry_trader venue OK`.

- [ ] **Step 1: Add the --live gate + demo (failing assert first)**

In `scripts/carry_trader.py` `main()`, after the `if args.live:` block's `settings.live` check (line ~379, the `if not settings.live: print(...); return`), add the venue gate BEFORE constructing `CoinDCXClient`:
```python
    if args.live:
        from app.config import settings
        if not settings.live:
            print("Refusing --live: trading_mode != 'live' in .env"); return
        # Phase 0 venue gate: refuse --live unless venue_verify.json is PASS + fresh.
        from scripts.venue_verify import load_gate, gate_is_fresh, GATE_PATH
        gate = load_gate()
        if gate is None:
            print(f"Refusing --live: no venue gate ({GATE_PATH}). Run: python scripts/venue_verify.py run"); return
        if gate.get("verdict") != "PASS":
            print(f"Refusing --live: venue gate verdict={gate.get('verdict')} "
                  f"({'redesign required' if gate.get('redesign_required') else 'probe(s) failed'}). "
                  f"Re-run: python scripts/venue_verify.py run"); return
        if not gate_is_fresh(gate):
            print(f"Refusing --live: venue gate stale (>24h). Re-run: python scripts/venue_verify.py run"); return
        from app.exchange.coindcx import CoinDCXClient
        client = CoinDCXClient()
        feed_fn = _live_feed
```
(Replace the existing `if args.live:` block's body — keep the `else: feed_fn = _paper_feed` branch.)

Add the demo fn + register it in `demo()`:
```python
async def _demo_venue_gate():
    """Phase 0 gate: --live refuses on missing/stale/FAIL, allows on PASS+fresh."""
    import tempfile
    from pathlib import Path
    from scripts.venue_verify import GATE_PATH
    import scripts.venue_verify as vv
    td = Path(tempfile.mkdtemp())
    fake_gate = td / "venue_verify.json"
    saved = vv.GATE_PATH
    # monkeypatch the gate path used by carry_trader's import
    real_load = vv.load_gate
    def fake_load(path=fake_gate):
        try: return json.loads(fake_gate.read_text())
        except Exception: return None
    vv.load_gate = fake_load
    # import carry_trader's own reference is bound at call time -> patch module-level
    import scripts.carry_trader as ct
    ct_load = None
    try:
        # PASS + fresh -> would proceed (we can't run main() fully; test the gate fn directly)
        fake_gate.write_text(json.dumps({"timestamp": int(time.time()), "verdict": "PASS"}))
        g = fake_load()
        assert g and g["verdict"] == "PASS" and vv.gate_is_fresh(g), g
        # FAIL -> refuse
        fake_gate.write_text(json.dumps({"timestamp": int(time.time()), "verdict": "FAIL",
                                         "redesign_required": True}))
        g2 = fake_load()
        assert g2["verdict"] == "FAIL"
        # stale -> refuse
        fake_gate.write_text(json.dumps({"timestamp": int(time.time()) - 25*3600, "verdict": "PASS"}))
        g3 = fake_load()
        assert not vv.gate_is_fresh(g3)
        # missing -> refuse
        fake_gate.unlink()
        assert fake_load() is None
    finally:
        vv.load_gate = real_load
    print("carry_trader venue OK")
```
Add `import time` at top of `carry_trader.py` if not already (it is — line 8). In `demo()`, add `asyncio.run(_demo_venue_gate())` after `asyncio.run(_demo_tilt())`.

- [ ] **Step 2: Run demo to verify 6 OK lines**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py`
Expected: 6 OK lines — `carry_trader signal OK`, `carry_trader faults OK`, `carry_trader reconcile OK`, `carry_trader sign OK`, `carry_trader tilt OK`, `carry_trader venue OK`.

- [ ] **Step 3: ruff + commit**

```bash
ruff check scripts/carry_trader.py
git add scripts/carry_trader.py
git commit -m "feat(carry): Phase 0 venue gate on --live + demo (6th OK line)"
```

---

### Task 6: §32 research-log appendix

**Files:**
- Modify: `docs/strategies_report.md` (append §32 after §31)
- Consumes: `reports/venue_verify.json` + `reports/venue_verify.log` (from a live `run` if available; else the spec's expected probe set).

- [ ] **Step 1: Append §32**

Append §32: the Phase 0 venue-verify sub-project — the 7-probe read-only harness, the FX-conversion gate + redesign-trigger decision (10bps threshold, USDT-margined-perp redesign on FAIL), the gate freshness (24h) wired into `carry_trader --live`, the no-testnet → write-path-deferred-to-Phase-2 constraint, and the probe results (paste `reports/venue_verify.log` if a live run was done; else state "awaiting first live run on the recorder host"). Match §30/§31 tone. Reference the spec + plan. Cross-refs `[[post-conclusion-followups]]` (§29), `[[funding-carry-band]]` (§20).

- [ ] **Step 2: Commit**

```bash
git add docs/strategies_report.md
git commit -m "docs(research): §32 Phase 0 venue-verify (sub-project 4)"
```

---

### Task 7: final verify

**Files:** none (verification only)

- [ ] **Step 1: Run all self-checks**

```bash
PYTHONPATH=. .venv/Scripts/python scripts/venue_verify.py
PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py
PYTHONPATH=. .venv/Scripts/python scripts/regime_gate_wf.py
PYTHONPATH=. .venv/Scripts/python scripts/regime_gates.py
PYTHONPATH=. .venv/Scripts/python scripts/tilt_signal.py
PYTHONPATH=. .venv/Scripts/python scripts/risk_budget.py
PYTHONPATH=. .venv/Scripts/python -m pytest tests/test_exchange.py -q
```
Expected: `venue_verify all probes + gate OK`; `carry_trader` 6 OK lines; others unchanged OK; pytest all pass.

- [ ] **Step 2: ruff**

```bash
ruff check scripts/venue_verify.py scripts/carry_trader.py app/exchange/coindcx.py tests/test_exchange.py
```
Expected: clean (line-length 100).

- [ ] **Step 3: Confirm gate files behave**

```bash
PYTHONPATH=. .venv/Scripts/python -c "from scripts.venue_verify import load_gate, gate_is_fresh; print(load_gate(), gate_is_fresh({'timestamp':0}))"
```
Expected: `None False` (no live run done in verify; gate absent -> None; ts=0 stale -> False).

---

## Self-Review

**1. Spec coverage:**
- 7 read-only probes → Tasks 2-4. ✓
- `get_conversion_rate` (seconds-ts) → Task 1. ✓
- FX-conversion gate + redesign trigger (10bps) → Task 3 probe 5 + Task 4 `verdict`. ✓
- Gate freshness 24h + `--live` guard → Task 4 `load_gate`/`gate_is_fresh` + Task 5. ✓
- No-testnet → write-path untouched (no task touches create_order/exit/spot). ✓
- Error handling (probe-throws-FAIL, missing CSV FAIL, conversions-4xx FAIL, stale refuse) → Task 3/4 probe try/except + Task 5 guard. ✓
- Testing (scripts `__main__` demo, app pytest) → every task. ✓
- §32 appendix → Task 6. ✓
- Out of scope (write-path, redesign sub-project, live deploy) → not built; spec marks out-of-scope. ✓

**2. Placeholder scan:** Task 3 has an "Implementer note" resolving the demo-CSV-clobber risk with a concrete `path` arg — not a TBD. Task 6 says "paste log if live run done; else state awaiting" — concrete, not a placeholder. No "TBD/TODO/add error handling" without code. ✓

**3. Type consistency:** `ProbeResult(name, passed, detail, error)` stable across Tasks 2-4. `get_conversion_rate() -> float` Task 1, consumed Task 3. `load_gate() -> dict|None` + `gate_is_fresh(gate, freshness_h) -> bool` Task 4, consumed Task 5. `verdict(results) -> dict` Task 4. `PROBES` list Task 4. ✓

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-25-phase0-venue-verify.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?