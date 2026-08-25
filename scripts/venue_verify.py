"""Phase 0 venue-verify (sub-project 4). Read-only probes that verify CoinDCX
perp + spot venue truth against the carry deploy's assumptions, then write
reports/venue_verify.json as the --live gate. No orders (no testnet exists).

--margin usdt (redesign): 6 venue probes (auth, perp, spot[BTCUSDT], funding,
basis, rate) + usdt_wallet (USDT-path "no FX leak" equivalent). fx_conversion
is an INR-path probe, NOT run for USDT (USDT margin has no INR conversion).
--margin inr (legacy): the 7 above incl fx_conversion (§29 crux).
See spec docs/superpowers/specs/2026-08-25-usdt-carry-redesign-design.md (comp 3).

Usage: python scripts/venue_verify.py run --margin usdt  (live -> reports/venue_verify.json)
       python scripts/venue_verify.py                    (demo self-check, no network)
"""
from __future__ import annotations

import csv
import json
import statistics
import time
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
        # fee: CoinDCX reports taker as a fraction (0.00059) or percent (0.059);
        # convert to bps. <0.01 = fraction (×1e4); else = percent (×1e2). Both
        # give 5.9 bps for the §29 0.059% taker fee.
        fee_frac = float(inst.get("taker_fee") or inst.get("taker_fee_rate") or 0)
        fee_bps = fee_frac * 1e4 if fee_frac < 0.01 else fee_frac * 1e2  # handle both forms
        lev = inst.get("leverage") or inst.get("max_leverage")
        # CoinDCX instrument endpoint does NOT expose leverage (null) — it is set
        # per-position via update_leverage. Null = not exposed here, not a venue
        # failure; only fail if a value is returned and it's below our cap.
        lev_ok = lev is None or float(lev) >= LEVERAGE_CAP
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


# --- probe 3: spot leg liveness (BTCUSDT for USDT redesign; BTCINR legacy) ---
async def instrument_spot(client, spot_pair: str = "BTCUSDT") -> ProbeResult:
    """Spot hedge-leg liveness for `spot_pair`. Spot fee is doc-derived (~0.169%
    +GST, §29 BTCINR-derived) — CoinDCX exposes no public spot-fee endpoint, so
    this verifies ticker liveness + records the doc fee; true fee confirmation is
    a forward Phase-2-fill caveat (component 4)."""
    try:
        px = await client.get_last_price(spot_pair)
        DOC_SPOT_FEE_PCT = 0.169  # §29 BTCINR-derived; verify BTCUSDT via real fill in Phase 2
        detail = {"last_price": px, "spot_pair": spot_pair,
                  "doc_spot_fee_pct": DOC_SPOT_FEE_PCT,
                  "note": "spot fee doc-derived; confirm via real fill in Phase 2"}
        return ProbeResult("instrument_spot", px > 0, detail,
                           None if px > 0 else f"{spot_pair} ticker returned 0/None")
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


# --- probe 5b: USDT futures wallet live + funded (USDT-path "no FX leak" equivalent) ---
async def usdt_wallet(client) -> ProbeResult:
    """USDT-margin path has no INR conversion, so the fx_conversion leak is N/A.
    The USDT-path equivalent of 'no FX leak' is a live, funded USDT futures
    margin wallet. PASS = a USDT wallet exists with balance > 0. FAIL = absent or
    zero — funding the USDT margin wallet is an account/UI action (not API-doable);
    a FAIL here is the expected blocker pending the user funding it, not a bug."""
    try:
        wallets = await client.get_wallets()
        rows = wallets if isinstance(wallets, list) else [wallets]
        usdt = None
        for w in rows:
            # CoinDCX derivatives wallets use `currency_short_name` (not currency/asset).
            cur = str(w.get("currency_short_name") or w.get("currency")
                       or w.get("asset") or "").upper()
            if cur == "USDT":
                usdt = w
                break
        if usdt is None:
            return ProbeResult("usdt_wallet", False, {"usdt_wallet": None},
                               "no USDT wallet — fund USDT futures margin via account UI (not API)")
        bal = float(usdt.get("balance") or 0)
        passed = bal > 0
        return ProbeResult("usdt_wallet", passed,
                           {"usdt_balance": bal, "locked": usdt.get("locked_balance")},
                           None if passed else
                           "USDT wallet balance=0 — fund it via account UI (not API)")
    except Exception as e:  # noqa: BLE001
        return ProbeResult("usdt_wallet", False, error=f"{type(e).__name__}: {e}")


# --- probe 7: rate limit (light, no stress) ---
async def rate_limit(client) -> ProbeResult:
    try:
        await client.get_wallets()
        await client.get_wallets()  # 2 rapid reads
        # documented: 16/s, 960/min. We don't stress-test; just confirm 2 succeed.
        return ProbeResult("rate_limit", True, {"doc_per_s": 16, "doc_per_min": 960,
                                                "note": "light probe: 2 rapid reads ok"})
    except Exception as e:  # noqa: BLE001
        return ProbeResult("rate_limit", False, error=f"{type(e).__name__}: {e}")


def _probes(margin: str = "usdt"):
    """Probe set per margin path. USDT: 6 venue probes + usdt_wallet (fx_conversion
    is an INR-path probe, not run for USDT — USDT margin has no INR conversion).
    INR: the legacy 7 (fx_conversion gating). instrument_spot's spot_pair follows
    the margin path (BTCUSDT / BTCINR)."""
    import functools
    spot = "BTCUSDT" if margin == "usdt" else "BTCINR"
    spot_probe = functools.partial(instrument_spot, spot_pair=spot)
    base = [auth_liveness, instrument_perp, spot_probe,
            funding_accrual, basis_proxy, rate_limit]
    if margin == "usdt":
        return base + [usdt_wallet]
    return [auth_liveness, instrument_perp, spot_probe,
            funding_accrual, fx_conversion, basis_proxy, rate_limit]


async def run_probes(client, margin: str = "usdt") -> list[ProbeResult]:
    return [await p(client) for p in _probes(margin)]


def verdict(results: list[ProbeResult], margin: str = "usdt") -> dict:
    if margin == "usdt":
        # USDT path: no INR conversion -> no FX leg -> redesign_required always
        # False. fx_conversion is not in the USDT probe set; gate = all run probes.
        all_pass = all(r.passed for r in results)
        fails = [r.name for r in results if not r.passed]
        return {"verdict": "PASS" if all_pass else "FAIL",
                "redesign_required": False, "margin": "usdt",
                "fail_reason": None if all_pass else f"failed probes: {fails}"}
    # INR legacy path: fx_conversion gap is the §29 crux + gates redesign.
    all_pass = all(r.passed for r in results)
    fx = next((r for r in results if r.name == "fx_conversion"), None)
    redesign = bool(fx and not fx.passed and fx.detail.get("mean_gap_bps") is not None)
    fail_reason = None
    if not all_pass:
        fails = [r.name for r in results if not r.passed]
        fail_reason = "fx_conversion gap >= threshold" if "fx_conversion" in fails and redesign \
            else f"failed probes: {fails}"
    return {"verdict": "PASS" if all_pass else "FAIL",
            "redesign_required": redesign, "margin": "inr", "fail_reason": fail_reason}


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
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def gate_is_fresh(gate: dict, freshness_h: float = FRESHNESS_H) -> bool:
    if not isinstance(gate, dict) or "timestamp" not in gate:
        return False
    try:
        return (time.time() - float(gate["timestamp"])) / 3600.0 <= freshness_h
    except (TypeError, ValueError):
        return False


async def _run_live(margin: str = "usdt") -> None:
    from app.exchange.coindcx import CoinDCXClient
    async with CoinDCXClient() as client:
        results = await run_probes(client, margin)
    v = verdict(results, margin)
    write_gate(results, v)
    print(f"venue_verify [{margin}] {v['verdict']} -> {GATE_PATH} "
          f"(redesign_required={v['redesign_required']})")


def main() -> None:
    import argparse
    import asyncio
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="demo",
                    help="'run' = live probes -> venue_verify.json; else demo")
    ap.add_argument("--margin", choices=["usdt", "inr"], default="usdt",
                    help="margin path: usdt (redesign, no FX leg) or inr (legacy, fx_conversion gating)")
    args = ap.parse_args()
    if args.cmd == "run":
        asyncio.run(_run_live(args.margin))
    else:
        demo()


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
    # USDT re-point: instrument_spot takes spot_pair (BTCUSDT liveness)
    r3u = asyncio.run(instrument_spot(FakeClient(), spot_pair="BTCUSDT"))
    assert r3u.passed and r3u.detail["spot_pair"] == "BTCUSDT" and \
        r3u.detail["doc_spot_fee_pct"] == 0.169, r3u
    # usdt_wallet probe: funded -> PASS; absent/zero -> FAIL (expected blocker)
    class WalletClient(FakeClient):
        async def get_wallets(self):
            # CoinDCX derivatives wallets shape: currency_short_name + balance + locked_balance
            return [{"currency_short_name": "INR", "balance": "50000", "locked_balance": "0"},
                    {"currency_short_name": "USDT", "balance": "120.0", "locked_balance": "0"}]
    rw = asyncio.run(usdt_wallet(WalletClient()))
    assert rw.passed and rw.detail["usdt_balance"] == 120.0, rw

    class NoUsdtWallet(FakeClient):
        async def get_wallets(self):
            return [{"currency_short_name": "INR", "balance": "50000", "locked_balance": "0"}]
    rw2 = asyncio.run(usdt_wallet(NoUsdtWallet()))
    assert not rw2.passed and "fund USDT" in (rw2.error or ""), rw2

    class ZeroUsdtWallet(FakeClient):
        async def get_wallets(self):
            return [{"currency_short_name": "USDT", "balance": "0", "locked_balance": "0"}]
    rw3 = asyncio.run(usdt_wallet(ZeroUsdtWallet()))
    assert not rw3.passed and "balance=0" in (rw3.error or ""), rw3
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
    v = verdict(crafted, margin="inr")
    assert v["verdict"] == "PASS" and v["redesign_required"] is False, v
    # fx FAIL -> redesign trigger
    crafted_fx_fail = [r if r.name != "fx_conversion" else
                       ProbeResult("fx_conversion", False, {"mean_gap_bps": 12.0},
                                   "mean gap 12.00bps >= 10.0bps") for r in crafted]
    vf = verdict(crafted_fx_fail, margin="inr")
    assert vf["verdict"] == "FAIL" and vf["redesign_required"] is True, vf
    # USDT verdict: all-pass (incl usdt_wallet) -> PASS, redesign_required False
    usdt_results = [
        ProbeResult("auth_liveness", True), ProbeResult("instrument_perp", True),
        ProbeResult("instrument_spot", True), ProbeResult("funding_accrual", True),
        ProbeResult("basis_proxy", True), ProbeResult("rate_limit", True),
        ProbeResult("usdt_wallet", True, {"usdt_balance": 120.0})]
    vu = verdict(usdt_results, margin="usdt")
    assert vu["verdict"] == "PASS" and vu["redesign_required"] is False and \
        vu["margin"] == "usdt", vu
    # USDT verdict: usdt_wallet FAIL -> gate FAIL (not redesign — no FX leg)
    usdt_fail = [r if r.name != "usdt_wallet" else
                 ProbeResult("usdt_wallet", False, {"usdt_balance": 0}, "balance=0")
                 for r in usdt_results]
    vuf = verdict(usdt_fail, margin="usdt")
    assert vuf["verdict"] == "FAIL" and vuf["redesign_required"] is False, vuf
    # _probes margin selector: usdt set has usdt_wallet, no fx_conversion; inr set has fx_conversion
    usdt_names = [p.func.__name__ if hasattr(p, "func") else p.__name__ for p in _probes("usdt")]
    inr_names = [p.func.__name__ if hasattr(p, "func") else p.__name__ for p in _probes("inr")]
    assert "usdt_wallet" in usdt_names and "fx_conversion" not in usdt_names, usdt_names
    assert "fx_conversion" in inr_names and "usdt_wallet" not in inr_names, inr_names
    # gate round-trip
    write_gate(crafted, v)
    g = load_gate()
    assert g and g["verdict"] == "PASS" and gate_is_fresh(g), g
    assert gate_is_fresh({"timestamp": int(time.time()) - 25 * 3600}) is False  # stale
    assert load_gate(Path("reports/nope_missing.json")) is None
    GATE_PATH.unlink(missing_ok=True)  # cleanup
    print("venue_verify all probes + gate OK")


if __name__ == "__main__":
    main()