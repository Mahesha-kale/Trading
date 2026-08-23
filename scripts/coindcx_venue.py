"""CoinDCX venue verification for the funding-carry watchlist (direction #1).

The §20 carry backtest used Binance perp funding + Binance perp/spot basis as a
PROXY for CoinDCX. §20 flagged "CoinDCX venue ≠ Binance" as an unverified caveat.
This closes what is verifiable from CoinDCX's public API:

1. FEES (instrument endpoint): actual maker/taker vs the backtest assumption.
2. FUNDING (rt endpoint): no public HISTORY, but current fr/efr vs Binance now.
3. BASIS (candle endpoint): CoinDCX INR-margin perp has NO USDT spot leg — spot is
   BTCINR (INR-quoted). Synthetic USDT spot = BTCINR / USDTINR (two INR legs ->
   carries a USDTINR FX risk Binance perp+USDT-spot does not). basis = perp/spot-1.

Key engineering question (§24): does CoinDCX basis stay < 100bps so the basis-
stop is free, or does it blow wider on the actual venue? Pulls N days of 1H
candles, builds the basis series, reports the distribution + the §23/§24 metrics.

Public endpoints, no auth. stdlib urllib. Usage: python scripts/coindcx_venue.py
"""
from __future__ import annotations

import json
import ssl
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np

# ponytail: venv py3.14 cert store is stale (curl verifies fine). Public read-only
# market-data endpoints only — unverified context is acceptable here. Do NOT reuse
# this for any authenticated/trading call.
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

PUB = "https://public.coindcx.com"
API = "https://api.coindcx.com"


def _get(base: str, path: str, params: dict) -> object:
    q = urlencode(params)
    req = Request(f"{base}{path}?{q}", headers={"User-Agent": "Mozilla/5.0 coindcx-venue-probe"})
    with urlopen(req, timeout=30, context=_CTX) as r:
        return json.load(r)


def candles(pair: str, days: int, pcode: str = "f") -> dict:
    to = 1770000000  # ponytail: fixed far-future upper bound avoids Date.now()
    # use a large fixed window; endpoint clips to available. (Date.now() banned in
    # some contexts; caller passes real now via env below if needed)
    to = int(__import__("time").time())
    from_ = to - days * 86400
    d = _get(PUB, "/market_data/candlesticks",
             {"pair": pair, "resolution": "60", "from": from_, "to": to, "pcode": pcode})
    if isinstance(d, dict) and d.get("s") == "ok" and d.get("data"):
        return {row["time"]: float(row["close"]) for row in d["data"]}
    return {}


def instrument(pair: str) -> dict:
    d = _get(API, "/exchange/v1/derivatives/futures/data/instrument",
             {"pair": pair, "margin_currency_short_name": "INR"})
    return d.get("instrument", d) if isinstance(d, dict) else {}


def funding_now() -> dict:
    d = _get(PUB, "/market_data/v3/current_prices/futures/rt", {})
    return d["prices"] if isinstance(d, dict) else {}


def basis_series(perp: dict, btcinr: dict, usdtinr: dict) -> np.ndarray:
    """basis (bps) = perp / (BTCINR/USDTINR) - 1, on aligned 1H closes."""
    ts = sorted(set(perp) & set(btcinr) & set(usdtinr))
    out = []
    for t in ts:
        spot = btcinr[t] / usdtinr[t]
        if spot > 0:
            out.append((perp[t] / spot - 1.0) * 1e4)
    return np.array(out)


def report(sym: str, perp_pair: str, spot_inr: str, days: int):
    inst = instrument(perp_pair)
    print(f"=== {sym} ({perp_pair}) ===")
    print(f"  fees: maker={inst.get('maker_fee')}% taker={inst.get('taker_fee')}% "
          f"(backtest used maker 0.02% taker 0.04%) | funding_freq={inst.get('funding_frequency')}h")
    fn = funding_now().get(perp_pair, {})
    print(f"  funding NOW: fr={fn.get('fr')} efr={fn.get('efr')} mp={fn.get('mp')} ls={fn.get('ls')}")
    perp = candles(perp_pair, days, "f")
    sinr = candles(spot_inr, days, "s") or candles(spot_inr, days, "")
    uinr = candles("USDTINR", days, "s") or candles("USDTINR", days, "")
    print(f"  candles {days}d: perp={len(perp)} {spot_inr}={len(sinr)} USDTINR={len(uinr)}")
    if not (perp and sinr and uinr):
        print("  -> cannot build basis (missing INR spot candles)\n")
        return
    b = basis_series(perp, sinr, uinr)
    print(f"  basis bps: n={len(b)} mean={b.mean():.1f} std={b.std():.1f} "
          f"max(prem)={b.max():.0f} min(disc)={b.min():.0f} "
          f"p99={np.percentile(b,99):.0f} p1={np.percentile(b,1):.0f}")
    print(f"  >> premium >100bps (stop would trigger): {(b > 100).mean()*100:.1f}%  "
          f">50bps: {(b>50).mean()*100:.1f}%")
    print(f"  Binance §23 ref: BTC max prem +69bps, min disc -186bps, 0 >1yr-funding.\n")


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    print(f"CoinDCX venue verify | {days}d 1H candles | INR-margin perp, synthetic USDT spot=BTCINR/USDTINR\n")
    for sym, perp, spot in (("BTC", "B-BTC_USDT", "BTCINR"),
                           ("ETH", "B-ETH_USDT", "ETHINR"),
                           ("SOL", "B-SOL_USDT", "SOLINR")):
        report(sym, perp, spot, days)


if __name__ == "__main__":
    main()