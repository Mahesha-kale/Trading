"""External macro regime prior: does DXY / US10Y predict BTC direction out-of-
sample? Foundation before gating the perp strategies — if macro doesn't predict
BTC, gating can't help (the strategies have no edge of their own to gate, §8-12).

DXY (DTWEXBGS, trade-weighted dollar) and US10Y (DGS10) from FRED free CSV, daily.
BTC daily returns from the cached Binance 15m klines. Tests simple macro signals
as next-day BTC long/short/flat predictors, train 70% / OOS 30%.

Usage: python scripts/macro_signal.py [BTCUSDT|ETHUSDT]
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"


def fred(sid: str) -> pd.Series:
    df = pd.read_csv(FRED.format(sid=sid), index_col=0, parse_dates=True)
    return df.replace(".", pd.NA).dropna().astype(float).iloc[:, 0].rename(sid)


def btc_daily(symbol: str) -> pd.DataFrame:
    for ext in ("parquet", "csv"):
        p = f"reports/binance_{symbol}_15m.{ext}"
        try:
            df = (pd.read_parquet(p) if ext == "parquet"
                  else pd.read_csv(p, index_col=0, parse_dates=True))
            d = df["close"].astype(float).resample("1D").last().dropna()
            return pd.DataFrame({"btc": d})
        except Exception:
            continue
    raise SystemExit(f"no price cache for {symbol}; run scripts/pull_binance.py first")


def signal_pnl(sig: pd.Series, ret: pd.Series) -> pd.Series:
    """Position = signal (long/short/flat), daily PnL = signal.shift(1)*ret (act
    on prior day's close, no lookahead). Equity curve."""
    pnl = (sig.shift(1) * ret).fillna(0)
    return (1 + pnl).cumprod()


def metrics(eq: pd.Series) -> dict:
    rets = eq.pct_change().dropna()
    sh = rets.mean() / rets.std() * np.sqrt(365) if rets.std() > 0 else 0
    peak = eq.cummax(); dd = ((eq - peak) / peak).min()
    yrs = len(eq) / 365
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else 0
    gp = rets[rets > 0].sum(); gl = -rets[rets < 0].sum()
    pf = gp / gl if gl > 0 else 0
    return {"sharpe": round(sh, 2), "max_dd": round(float(dd), 3),
            "cagr": round(cagr, 3), "pf": round(pf, 2), "n": len(eq),
            "end_eq": round(float(eq.iloc[-1]), 3)}


def main(symbol="BTCUSDT"):
    px = btc_daily(symbol)
    px.index = px.index.tz_localize(None)  # FRED is tz-naive; align
    dxy = fred("DTWEXBGS")
    y10 = fred("DGS10")
    df = px.join(dxy, how="inner").join(y10, how="inner").dropna()
    df["ret"] = df["btc"].pct_change()
    df = df.dropna()
    print(f"{symbol}: {len(df)} daily rows {df.index[0].date()}->{df.index[-1].date()}", flush=True)
    # macro signals (act next day)
    df["dxy_mom5"] = -np.sign(df["DTWEXBGS"].pct_change(5))      # falling dollar -> long BTC
    df["dxy_below_ma200"] = (df["DTWEXBGS"] < df["DTWEXBGS"].rolling(200).mean()).astype(int) * 2 - 1
    df["y10_mom5"] = -np.sign(df["DGS10"].diff(5))               # falling rates -> long BTC
    df["dxy_y10"] = ((df["dxy_mom5"] + df["y10_mom5"]) / 2)      # combined, both risk-on
    sigs = {"dxy_mom5": "dxy_mom5", "dxy_below_ma200": "dxy_below_ma200",
             "y10_mom5": "y10_mom5", "dxy+y10": "dxy_y10", "buyhold": None}
    split = df.index[int(len(df) * 0.7)]
    train = df.loc[:split]; oos = df.loc[split:]
    print(f"split {split.date()} | train {len(train)} oos {len(oos)}\n", flush=True)
    print(f"{'signal':16} {'IS sh':>7} {'IS PF':>6} {'OOS sh':>7} {'OOS PF':>7} {'OOS net%':>9}", flush=True)
    out = {}
    for name, col in sigs.items():
        if col is None:  # buy&hold
            is_eq = (1 + train["ret"]).cumprod(); oo_eq = (1 + oos["ret"]).cumprod()
        else:
            is_eq = signal_pnl(train[col], train["ret"]); oo_eq = signal_pnl(oos[col], oos["ret"])
        im, om = metrics(is_eq), metrics(oo_eq)
        oos_net_pct = round((oo_eq.iloc[-1] - 1) * 100, 1)
        out[name] = {"is": im, "oos": om, "oos_net_pct": oos_net_pct}
        print(f"{name:16} {im['sharpe']:7.2f} {im['pf']:6.2f} {om['sharpe']:7.2f} "
              f"{om['pf']:7.2f} {oos_net_pct:9.1f}", flush=True)
    # robust macro edge = positive Sharpe in BOTH halves AND OOS > buyhold.
    # A signal that is +OOS but -IS (or vice versa) is regime luck, not an edge —
    # a real predictor is positive in both train and test.
    macro = {k: v for k, v in out.items() if k != "buyhold"}
    bh_sh = out["buyhold"]["oos"]["sharpe"]
    robust = [k for k, v in macro.items()
              if v["is"]["sharpe"] > 0 and v["oos"]["sharpe"] > 0
              and v["oos"]["sharpe"] > bh_sh and v["oos"]["sharpe"] > 0.3]
    best = max(macro, key=lambda k: macro[k]["oos"]["sharpe"])
    if robust:
        verdict = f"ROBUST MACRO EDGE OOS: {robust} (best {best} oos sh {macro[best]['oos']['sharpe']} vs buyhold {bh_sh})"
    else:
        verdict = (f"no robust macro edge OOS (best {best} oos sh {macro[best]['oos']['sharpe']} "
                  f"is sh {macro[best]['is']['sharpe']} vs buyhold {bh_sh}; positive-OOS/negative-IS = regime luck)")
    print(f"\nverdict: {verdict}")
    json.dump({"symbol": symbol, "n": len(df), "split": str(split.date()),
                "signals": out, "verdict": verdict},
              open("reports/macro_signal.json", "w"), indent=2, default=str)
    print("-> reports/macro_signal.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT")