"""Phase 1 paper-trader success-criteria verdict (sub-project 5).

Reads reports/carry_paper.csv + reports/carry_trader_state.json and emits the
5-criteria verdict that gates Phase 2 small-real. See spec §"Success criteria".

Usage:
  python scripts/paper_check.py            # demo self-check
  python scripts/paper_check.py run        # real verdict on default reports paths
  python scripts/paper_check.py [ledger_csv] [state_json] [capital] [window_d]
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

REPORTS = Path("reports")
CARRY_YR_TARGET = 0.07  # §20 proxy ~7%/yr (sanity, not proof)

CRITERIA = [
    "zero_faults", "feed_live", "signal_fired", "funding_nonneg", "state_clean",
]


def _read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return list(csv.DictReader(path.read_text().splitlines()))


def _read_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def verdict(rows: list[dict], state: dict, capital: float, window_d: float) -> dict:
    events = [r.get("event", "") for r in rows]
    # 1. zero faults: no DD_HALT, no halted_orphan in state, no corrupt
    c1 = ("DD_HALT" not in events) and (not state.get("halted_orphan")) and (not state.get("corrupt"))
    # 2. feed live: FEED_OUTAGE < 5% of rows
    n = len(rows) or 1
    c2 = (events.count("FEED_OUTAGE") / n) < 0.05
    # 3. signal fired: >=1 ENTER_SHORT and >=1 FLATTEN
    c3 = events.count("ENTER_SHORT") >= 1 and events.count("FLATTEN") >= 1
    # 4. funding non-negative + annualized within order-of-magnitude of 7%/yr
    accrued = state.get("accrued_funding", 0.0)
    yr = max(window_d / 365.0, 1e-9)
    ann = (accrued / capital) / yr if capital else 0.0
    c4 = accrued >= 0 and ann <= CARRY_YR_TARGET * 10  # within 10x of 7%/yr (order of magnitude)
    # 5. state clean: not halted (a planned end-of-window stop is fine; an unplanned halt fails c1)
    c5 = not state.get("halted", False)
    crit = {CRITERIA[i]: c for i, c in enumerate([c1, c2, c3, c4, c5])}
    return {"pass": all(crit.values()), "criteria": crit,
            "detail": f"accrued={accrued} ann={ann:.4f} events={len(rows)}"}


def demo() -> None:
    import tempfile
    td = Path(tempfile.mkdtemp())
    # pass case: 10 rows, an ENTER_SHORT + FLATTEN, no faults, accrued positive, state clean
    lp = td / "carry_paper.csv"
    lp.write_text("ts,event,side,fr,efr,basis_bps,accrued_funding,equity\n"
                  "1,ENTER_SHORT,-1,0.0003,0.0003,10,0,100000\n"
                  "2,FUNDING_ACCRUE,-1,0.0003,0.0003,10,270,100270\n"
                  "3,FLATTEN,0,,,0,270,100270\n")
    sp = td / "state.json"
    sp.write_text(json.dumps({"accrued_funding": 270.0, "halted": False, "halted_orphan": False, "corrupt": False}))
    v = verdict(_read_ledger(lp), _read_state(sp), capital=100_000.0, window_d=14.0)
    assert v["pass"] is True, v
    assert all(v["criteria"].values()), v
    # fail case: a DD_HALT -> criterion 1 fails
    lp.write_text("ts,event,side,fr,efr,basis_bps,accrued_funding,equity\n"
                  "1,ENTER_SHORT,-1,0.0003,0.0003,10,0,100000\n"
                  "2,DD_HALT,0,,,0,-5000,75000\n")
    sp.write_text(json.dumps({"accrued_funding": -5000.0, "halted": True, "halted_orphan": False, "corrupt": False}))
    vf = verdict(_read_ledger(lp), _read_state(sp), capital=100_000.0, window_d=14.0)
    assert vf["pass"] is False and vf["criteria"]["zero_faults"] is False, vf
    print("paper_check OK")


def main() -> None:
    import sys
    ledger = Path(sys.argv[1]) if len(sys.argv) > 1 else (REPORTS / "carry_paper.csv")
    state = Path(sys.argv[2]) if len(sys.argv) > 2 else (REPORTS / "carry_trader_state.json")
    capital = float(sys.argv[3]) if len(sys.argv) > 3 else 100_000.0
    window_d = float(sys.argv[4]) if len(sys.argv) > 4 else 14.0
    v = verdict(_read_ledger(ledger), _read_state(state), capital, window_d)
    print(json.dumps(v, indent=2))
    print("PASS" if v["pass"] else "FAIL")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "run":
        # real verdict on default reports paths (matches regime_gate_wf `run`)
        sys.argv = [sys.argv[0]]
        main()
    elif len(sys.argv) > 1:
        main()  # positional: [ledger_csv] [state_json] [capital] [window_d]
    else:
        demo()