"""Funding-rate carry: a structurally different edge class from the price-momentum /
reversion family that showed no OOS edge (§8-§10). The carry trade holds the
funding-RECEIVING side of the perp: short when funding>0 (shorts get paid), long
when funding<0 (longs get paid). PnL per 8h interval = funding received + adverse
price move. Edge exists if funding income > adverse drift on average, or if
funding predicts price direction.

Binance public fapi gives funding history + mark price (no key); price comes
from the cached Binance 15m klines. Tests on BTCUSDT/ETHUSDT over the same 2.5yr
multi-regime window as §9, with train(70%)/OOS(30%) walk-forward.

Usage: python scripts/funding_carry.py [BTCUSDT|ETHUSDT]
"""
from __future__ import annotations

import json
import sys
from urllib.parse import urlencode
from urllib.request import urlopen

import numpy as np
import pandas as pd

FAPI = "https://fapi.binance.com/fapi/v1/fundingRate"


def fetch_funding(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    rows = []
    cur = start_ms
    while cur < end_ms:
        q = urlencode({"symbol": symbol, "startTime": cur, "endTime": end_ms, "limit": 1000})
        batch = json.load(urlopen(f"{FAPI}?{q}", timeout=30))
        if not batch:
            break
        rows.extend(batch)
        cur = batch[-1]["fundingTime"] + 1
        if len(batch) < 1000:
            break
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
    df["rate"] = pd.to_numeric(df["fundingRate"], errors="coerce")
    return df.set_index("ts")[["rate"]].sort_index().dropna()


def load_price(symbol: str) -> pd.Series:
    for ext in ("parquet", "csv"):
        p = f"reports/binance_{symbol}_15m.{ext}"
        try:
            df = (pd.read_parquet(p) if ext == "parquet"
                  else pd.read_csv(p, index_col=0, parse_dates=True))
            return df["close"].astype(float).sort_index()
        except Exception:
            continue
    raise SystemExit(f"no price cache for {symbol}; run scripts/pull_binance.py first")


def align(price: pd.Series, funding: pd.DataFrame) -> pd.DataFrame:
    """Closest 15m close at/after each funding timestamp."""
    f = funding.copy()
    f["px"] = price.reindex(f.index, method="nearest")
    f["px_next"] = f["px"].shift(-1)  # price at next funding
    return f.dropna()


def carry_pnl(f: pd.DataFrame, leverage: float = 1.0) -> pd.Series:
    """Equity curve of always holding the funding-receiving side (directional,
    unhedged). per interval: pos = -sign(rate); funding received = |rate|;
    price pnl = pos*ret. equity *= 1 + lev*(|rate| + pos*ret).
    ponytail: unhedged carry is just a directional bet — adverse price dwarfs the
    ~9%/yr funding income (see results). The real carry is delta_neutral_pnl."""
    pos = -np.sign(f["rate"])
    ret = f["px_next"] / f["px"] - 1.0
    interval = leverage * (f["rate"].abs() + pos * ret)
    eq = (1.0 + interval).cumprod()
    return eq


def delta_neutral_pnl(f: pd.DataFrame, fee_taker: float = 0.0004,
                       maker: bool = False) -> pd.Series:
    """Delta-neutral funding harvest: long perp + short spot (or flip) so price
    cancels, keep funding. PnL per interval = |rate| (received) - fees on flips.
    Flip when the receiving side changes (rate sign change). perp≈spot so price
    pnl on the hedge leg exactly cancels the perp leg (basis ignored, <0.1% on
    BTC, well below fees). This is the actual carry trade; the fee dominates."""
    fee = fee_taker * (0.5 if maker else 1.0)  # maker ~half taker if filled
    rate = f["rate"].values
    side = -np.sign(rate)  # +1 long perp, -1 short perp
    flips = np.diff(side, prepend=side[0]) != 0  # entering + every sign change
    # each flip = close old + open new perp AND spot = 4 fills (2 perp, 2 spot)
    fee_cost = np.where(flips, 4 * fee, 0.0)
    funding_income = np.abs(rate)
    interval = funding_income - fee_cost
    return pd.Series((1.0 + interval).cumprod(), index=f.index)


def metrics(eq: pd.Series) -> dict:
    rets = eq.pct_change().dropna()
    bpy = 365 * 3  # 8h funding = 3/day
    sh = rets.mean() / rets.std() * np.sqrt(bpy) if rets.std() > 0 else 0
    peak = eq.cummax(); dd = ((eq - peak) / peak).min()
    yrs = len(eq) / bpy
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else 0
    gp = rets[rets > 0].sum(); gl = -rets[rets < 0].sum()
    pf = gp / gl if gl > 0 else 0
    return {"sharpe": round(sh, 2), "max_dd": round(float(dd), 3),
            "cagr": round(cagr, 3), "pf": round(pf, 2),
            "n": len(eq), "end_eq": round(float(eq.iloc[-1]), 3)}


def main(symbol="BTCUSDT", leverage=1.0):
    price = load_price(symbol)
    funding = fetch_funding(symbol, int(price.index[0].timestamp() * 1000),
                            int(price.index[-1].timestamp() * 1000))
    f = align(price, funding)
    print(f"{symbol}: {len(f)} funding events {f.index[0].date()}->{f.index[-1].date()} "
          f"| mean|rate|={f['rate'].abs().mean()*100:.4f}%/8h", flush=True)
    # buy-and-hold benchmark (long perp, full period)
    bh = f["px_next"].iloc[-1] / f["px"].iloc[0] - 1
    split = f.index[int(len(f) * 0.7)]
    train = f.loc[:split]; oos = f.loc[split:]
    print(f"split {split.date()} | train {len(train)} oos {len(oos)}", flush=True)
    full = carry_pnl(f, leverage)
    print(f"  carry FULL (directional):    {metrics(full)}", flush=True)
    print(f"  carry OOS  (directional):     {metrics(carry_pnl(oos, leverage))}", flush=True)
    # delta-neutral (real carry): hedge cancels price, keep funding - fees
    dn_full = delta_neutral_pnl(f)
    print(f"  delta-neutral FULL: {metrics(dn_full)}", flush=True)
    print(f"  delta-neutral OOS:  {metrics(delta_neutral_pnl(oos))}", flush=True)
    # maker-filled delta-neutral (half the fee, optimistic)
    print(f"  delta-neutral OOS (maker): {metrics(delta_neutral_pnl(oos, maker=True))}", flush=True)
    bh_oos = oos["px_next"].iloc[-1] / oos["px"].iloc[0] - 1
    print(f"  buy&hold OOS ret: {bh_oos*100:.2f}%", flush=True)
    oos_sh = metrics(delta_neutral_pnl(oos))["sharpe"]
    oos_sh_maker = metrics(delta_neutral_pnl(oos, maker=True))["sharpe"]
    verdict = ("DELTA-NEUTRAL CARRY EDGE OOS" if oos_sh_maker > 0.5
               else "marginal carry OOS (fee-sensitive)" if oos_sh_maker > 0
               else "no carry edge OOS (fees eat funding)")
    print(f"\nverdict: {verdict} (oos sharpe taker {oos_sh}, maker {oos_sh_maker})")
    out = {"symbol": symbol, "leverage": leverage,
            "n_events": len(f), "mean_abs_rate_pct": f["rate"].abs().mean() * 100,
            "directional": {"full": metrics(full), "oos": metrics(carry_pnl(oos, leverage))},
            "delta_neutral": {"full": metrics(dn_full), "oos": metrics(delta_neutral_pnl(oos)),
                              "oos_maker": metrics(delta_neutral_pnl(oos, maker=True))},
            "buyhold_oos_ret": round(bh_oos, 4), "verdict": verdict}
    json.dump(out, open("reports/funding_carry.json", "w"), indent=2, default=str)
    print("-> reports/funding_carry.json")


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    lev = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    main(sym, lev)