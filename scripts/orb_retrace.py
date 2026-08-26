"""ORB retrace-depth + sub-1 RR sweep (sub-project 7, §35.18).

Instagram reel variant (alphazone.ai, RoboQuant-coded bot): same ORB template
as orb_max but (a) entry on a DEEP RETRACE into the opening range (reel: 40%)
instead of the edge-touch retest, and (b) a sub-1 RR target (reel: 0.8R).
Sweeps retrace_pct x rr on the NY+Asia best cells (§35.16), last 1y, through
the K-fold + bootstrap-CI rigor gate. Last untested corner of this class:
sub-1 RR needs ~57%+ win rate under real taker costs vs ORB's 38-43%.

run:  python -m scripts.orb_retrace [--out reports/orb_retrace.log]
"""
from __future__ import annotations

from scripts.orb_exits import (CELLS_NY_ASIA, CSV, kfold_ci, load_csv,
                               winloss)

# retrace depth (of range) x reward:risk
GRID = [(rp, rr) for rp in (0.25, 0.4, 0.5) for rr in (0.8, 1.0, 1.5)]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/orb_retrace.log")
    args = ap.parse_args()
    out = open(args.out, "w") if args.out else None

    def emit(s=""):
        print(s)
        out and out.write(s + "\n")

    rows = []
    for asset, sess, rb in CELLS_NY_ASIA:
        df = load_csv(CSV[asset]).iloc[-35040:]  # last 1y
        emit(f"\n##### {asset} 15m {sess} rb={rb} | 1y {df.index[0].date()} -> {df.index[-1].date()} #####")
        for rp, rr in GRID:
            label = f"retrace{rp:.2f}+rr{rr}"
            sp = {"tp_mode": "rr", "rr": rr, "sl_mode": "or",
                  "retrace_pct": rp, "range_bars": rb, "session_open": sess}
            try:
                fnets, net, lo, trades, m = kfold_ci(df, sp, {})
            except Exception as e:  # noqa: BLE001
                emit(f"  {label:24} ERR {str(e)[:60]}")
                continue
            n, w, _l, pct = winloss(trades)
            k4 = sum(f > 0 for f in fnets) >= 3 and sum(fnets) > 0
            verdict = "PASS" if (k4 and net > 0 and lo > 0) else "fail"
            rows.append((asset, label, n, pct, net, lo, k4, verdict))
            emit(f"  {label:24} tr={n:4} win%={pct:4.0f} net={net:8.0f} "
                 f"dd={m.get('max_drawdown', 0):.2f} "
                 f"folds=[{','.join(str(round(f)) for f in fnets)}] CIlo={lo:.2f} {verdict}")
    emit("\n===== PASSING (CI lo > 0 AND >=3/4 folds AND net>0) =====")
    any_pass = False
    for asset, label, n, pct, net, lo, k4, verdict in rows:
        if verdict == "PASS":
            any_pass = True
            emit(f"  {asset} {label}: tr={n} win%={pct:.0f} net={net:.0f} CIlo={lo:.2f}")
    if not any_pass:
        emit("  NONE -- retrace-depth + sub-1 RR fails K-fold rigor; ORB stays refuted")
    out and out.close()


if __name__ == "__main__":
    main()
