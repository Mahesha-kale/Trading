"""CoinDCX funding + basis FORWARD recorder (direction #1 venue-verify closer).

§20 carry backtest used Binance funding + Binance perp/spot basis as a PROXY for
CoinDCX. The venue caveats (CoinDCX funding ≠ Binance; CoinDCX basis ≠ Binance)
cannot be closed retrospectively — CoinDCX exposes NO public funding-rate HISTORY
and NO INR-spot OHLC history. Both must be accrued forward. This polls CoinDCX's
real-time futures endpoint + the spot ticker every 60s and appends one row per
pair, so over weeks we get a real CoinDCX funding + basis series to verify:

  - funding: does CoinDCX fr/efr track Binance over time (is the ~7%/yr proxy right)?
  - basis:   does CoinDCX perp-vs-synthetic-spot basis stay <100bps (so the §24
             basis-stop is free on the actual venue)? The synthetic USDT spot =
             BTCINR/USDTINR (INR margin has no USDT spot leg -> carries USDTINR FX
             risk the Binance proxy did not; this IS the venue finding).

Public endpoints, no auth, stdlib only. Reuses nothing (runs standalone on the
cloud box). Append-only CSV: ts, sym, fr, efr, mp, ls, spot_inr, usdtinr, basis_bps.

Usage: python scripts/coindcx_venue_recorder.py   (runs until Ctrl-C)
"""
from __future__ import annotations

import csv
import json
import ssl
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PUB = "https://public.coindcx.com"
API = "https://api.coindcx.com"
PAIRS = {"BTC": "B-BTC_USDT", "ETH": "B-ETH_USDT", "SOL": "B-SOL_USDT"}
SPOT_INR = {"BTC": "BTCINR", "ETH": "ETHINR", "SOL": "SOLINR"}
POLL_S = 60
OUT = Path("reports/coindcx_venue.csv")

# ponytail: public read-only endpoints; unverified ctx only because the box's
# cert store may be stale. Do NOT reuse for authenticated calls.
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE
_UA = {"User-Agent": "Mozilla/5.0 coindcx-venue-recorder"}


def _get(base: str, path: str, params: dict) -> object:
    req = Request(f"{base}{path}?{urlencode(params)}", headers=_UA)
    with urlopen(req, timeout=15, context=_CTX) as r:
        return json.load(r)


def spot_prices() -> dict:
    """INR spot last prices from the public ticker (no OHLC history -> last only)."""
    rows = _get(API, "/exchange/ticker", {})
    return {r["market"]: float(r.get("last_price", 0)) for r in rows if r.get("market")}


def futures_rt() -> dict:
    d = _get(PUB, "/market_data/v3/current_prices/futures/rt", {})
    return d["prices"] if isinstance(d, dict) else {}


def sample() -> list[dict]:
    try:
        fut = futures_rt()
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] futures_rt failed: {e}", flush=True)
        return []
    try:
        spot = spot_prices()
    except Exception as e:  # spot ticker optional - basis just blank if it fails
        print(f"[{time.strftime('%H:%M:%S')}] spot ticker failed: {e}", flush=True)
        spot = {}
    usdtinr = spot.get("USDTINR", 0)
    rows = []
    for sym, pair in PAIRS.items():
        f = fut.get(pair)
        if not f:
            continue
        sinr = spot.get(SPOT_INR[sym], 0)
        synth = sinr / usdtinr if (usdtinr and sinr) else 0
        basis = (float(f["mp"]) / synth - 1.0) * 1e4 if synth else float("nan")
        rows.append({
            "ts": int(time.time()), "sym": sym,
            "fr": f.get("fr"), "efr": f.get("efr"),
            "mp": f.get("mp"), "ls": f.get("ls"),
            "spot_inr": sinr or "", "usdtinr": usdtinr or "",
            "basis_bps": round(basis, 2) if basis == basis else "",  # nan check
        })
    return rows


def main():
    new = not OUT.exists()
    f = open(OUT, "a", newline="", buffering=1)
    w = csv.DictWriter(f, fieldnames=["ts", "sym", "fr", "efr", "mp", "ls",
                                      "spot_inr", "usdtinr", "basis_bps"])
    if new:
        w.writeheader()
    print(f"coindcx_venue_recorder -> {OUT} (poll every {POLL_S}s)", flush=True)
    n = 0
    while True:
        rows = sample()
        for r in rows:
            w.writerow(r)
        n += len(rows)
        if rows:
            print(f"[{time.strftime('%H:%M:%S')}] {len(rows)} rows (total {n}) "
                  f"BTC efr={rows[0]['efr']} basis={rows[0]['basis_bps']}bps", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()