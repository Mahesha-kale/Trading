"""ORB breakout-strength filter sweep (sub-project 7, §35.19).

Prop-firm reel variant (instagram DZvAMYZA1ae): entry AT the breakout-bar close
("gold bar", no retest) + regime filters on the breakout itself -- relative
volume and ATR floor, to filter weak vs strong breaks. Sweeps
entry_mode=close x min_relvol x min_atr_pct on the 4 NY+Asia best cells
(§35.16), last 1y, K-fold + bootstrap-CI rigor gate. Distinct from §35 phase-3
slow regime gates (SMA200/vol-tier): these are PER-SIGNAL breakout-strength
filters.

run:  python -m scripts.orb_filters [--out reports/orb_filters.log]
"""
from __future__ import annotations

from scripts.orb_exits import (CELLS_NY_ASIA, CSV, kfold_ci, load_csv,
                               winloss)

# min_relvol (signal-bar vol / 20-bar mean), min_atr_pct (ATR14/close floor)
GRID = [(rv, ap) for rv in (0.0, 1.5, 2.0) for ap in (0.0, 0.002, 0.004)]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/orb_filters.log")
    args = ap.parse_args()
    out = open(args.out, "w") if args.out else None

    def emit(s=""):
        print(s)
        out and out.write(s + "\n")

    rows = []
    for asset, sess, rb in CELLS_NY_ASIA:
        df = load_csv(CSV[asset]).iloc[-35040:]  # last 1y
        emit(f"\n##### {asset} 15m {sess} rb={rb} | 1y {df.index[0].date()} -> {df.index[-1].date()} #####")
        for rv, ap in GRID:
            label = f"close rv{rv}+atr{ap}"
            sp = {"tp_mode": "rr", "rr": 2.0, "sl_mode": "or",
                  "entry_mode": "close", "min_relvol": rv, "min_atr_pct": ap,
                  "range_bars": rb, "session_open": sess}
            try:
                fnets, net, lo, trades, m = kfold_ci(df, sp, {})
            except Exception as e:  # noqa: BLE001
                emit(f"  {label:26} ERR {str(e)[:60]}")
                continue
            n, w, _l, pct = winloss(trades)
            k4 = sum(f > 0 for f in fnets) >= 3 and sum(fnets) > 0
            verdict = "PASS" if (k4 and net > 0 and lo > 0) else "fail"
            rows.append((asset, label, n, pct, net, lo, k4, verdict))
            emit(f"  {label:26} tr={n:4} win%={pct:4.0f} net={net:8.0f} "
                 f"dd={m.get('max_drawdown', 0):.2f} "
                 f"folds=[{','.join(str(round(f)) for f in fnets)}] CIlo={lo:.2f} {verdict}")
    emit("\n===== PASSING (CI lo > 0 AND >=3/4 folds AND net>0) =====")
    any_pass = False
    for asset, label, n, pct, net, lo, k4, verdict in rows:
        if verdict == "PASS":
            any_pass = True
            emit(f"  {asset} {label}: tr={n} win%={pct:.0f} net={net:.0f} CIlo={lo:.2f}")
    if not any_pass:
        emit("  NONE -- close entry + relvol/ATR filters fail K-fold rigor; ORB stays refuted")
    out and out.close()


if __name__ == "__main__":
    main()
