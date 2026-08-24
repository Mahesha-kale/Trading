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

import csv
import statistics
from dataclasses import dataclass, field
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


def _load_venue_csv(sym: str = "BTC", path: Path = REPORTS / "coindcx_venue.csv") -> list[dict]:
    """Read recorder CSV, filter to sym. path defaults to the real recorder CSV;
    demo passes a tmp path so it never clobbers real recorder data."""
    if not path.exists():
        return []
    rows = [r for r in csv.DictReader(path.read_text().splitlines()) if r.get("sym") == sym]
    return rows


# --- probe 4: funding accrual (recorder CSV, 60s-polled) ---
async def funding_accrual(client, csv_path: Path | None = None) -> ProbeResult:
    rows = _load_venue_csv("BTC", csv_path or REPORTS / "coindcx_venue.csv")
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
            gaps.append(_gap_bps(conv, spot))
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
async def basis_proxy(client, csv_path: Path | None = None) -> ProbeResult:
    rows = _load_venue_csv("BTC", csv_path or REPORTS / "coindcx_venue.csv")
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
            return {"taker_fee": 0.002, "max_leverage": 5, "min_quantity": 0.001}
    r2b = asyncio.run(instrument_perp(BadFee()))
    assert not r2b.passed and "fee" in (r2b.error or ""), r2b
    r3 = asyncio.run(instrument_spot(FakeClient()))
    assert r3.passed and r3.detail["last_price"] > 0, r3
    # probe 4 & 6: funding_accrual + basis_proxy on a synthetic CSV in a tmp
    # dir — NEVER writes reports/coindcx_venue.csv (carry-in guard vs real recorder data).
    import tempfile
    tmp_csv = Path(tempfile.mkdtemp()) / "coindcx_venue.csv"
    # 8h+ of synthetic BTC rows (60s spacing -> 481 rows = 8h), basis_bps=5.0
    rows_txt = "ts,sym,fr,efr,mp,ls,spot_inr,usdtinr,basis_bps\n"
    t0 = 1_700_000_000
    for i in range(481):
        rows_txt += f"{t0 + i * 60},BTC,0.000064,0.000064,90000000,90000000,8100000,90,5.0\n"
    tmp_csv.write_text(rows_txt)
    r4 = asyncio.run(funding_accrual(FakeClient(), csv_path=tmp_csv))
    assert r4.passed and r4.detail["span_h"] >= 8, r4
    r6 = asyncio.run(basis_proxy(FakeClient(), csv_path=tmp_csv))
    assert r6.passed and r6.detail["median_abs_basis_bps"] == 5.0, r6
    # probe 5: fx_conversion gap math (no network -> test _gap_bps directly)
    assert abs(_gap_bps(90.05, 90.00) - 5.5556) < 0.01
    print("venue_verify probes 1-6 OK")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        print("run mode not implemented until Task 4")  # placeholder removed in Task 4
    else:
        demo()