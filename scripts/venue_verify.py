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
    print("venue_verify probes 1-3 OK")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        print("run mode not implemented until Task 4")  # placeholder removed in Task 4
    else:
        demo()