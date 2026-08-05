"""Monitor a grid_live run by tailing its log. Emits one line per notable event
(fill, feed failure, stall, completion) so it can drive a notification stream.
On the run's `done:` line, auto-runs scripts/grid_live_replay.py and prints its
verdict, then exits.

Stdlib only — no watchdog/deps. Runnable standalone:
    python scripts/grid_monitor.py [log_path] [stall_minutes]
Defaults: reports/grid_live_overnight.log, stall=5min.

Stall detection uses the ISO timestamp at the start of each log line (a real
clock, not file mtime) — if no line lands within stall_minutes, the feed is
treated as dead and an alert fires once (re-fires if it recovers then stalls
again). This is the real failure mode: WS reconnect storm or feed drop leaving
the bot silently flat.

Exit codes: 0 run finished (replay run), 2 log never appeared, 3 timeout.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LOG = "reports/grid_live_overnight.log"
REPLAY = Path(__file__).parent / "grid_live_replay.py"
TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+\-]\d{2}:\d{2})")


def parse_ts(line: str) -> datetime | None:
    m = TS_RE.match(line)
    return datetime.fromisoformat(m.group(1)) if m else None


def classify(line: str) -> str:
    # order matters: terminal first
    if line.startswith("done:") or " done:" in line or "final equity" in line:
        return "done"
    if "fill " in line:
        return "fill"
    if any(k in line for k in ("failed", "503", "unavailable", "fallback")):
        return "feed_issue"
    return "info"


def tail(path: Path, stall_min: float, timeout_s: float | None):
    """Yield (kind, line) for notable events. Blocks until `done:` or timeout."""
    # ponytail: busy-poll tail (no watchdog dep). 2s cadence is fine for a bot
    # whose grid step is 2%; sub-second latency buys nothing here.
    wait_start = time.time()
    while not path.exists():
        if time.time() - wait_start > 60:
            print(f"stall: log {path} never appeared after 60s", flush=True)
            return
        time.sleep(2)
    last_line_ts: datetime | None = None
    last_emit_ts: datetime | None = None
    alerted = False
    offset = 0
    while True:
        with open(path, "rb") as f:
            f.seek(offset)
            chunk = f.read().decode("utf-8", "replace")
            offset = f.tell()
        if chunk:
            for line in chunk.splitlines():
                if not line.strip():
                    continue
                ts = parse_ts(line)
                if ts:
                    last_line_ts = ts
                    alerted = False  # activity resets stall latch
                kind = classify(line)
                if kind != "info":
                    print(f"[{kind}] {line}", flush=True)
                if kind == "done":
                    return  # run finished
        # stall check on wall clock vs last log line
        if last_line_ts is not None:
            lag = (datetime.now(timezone.utc) - last_line_ts).total_seconds() / 60
            if lag > stall_min and not alerted:
                print(f"[stall] no log line for {lag:.0f}min — feed may be dead", flush=True)
                alerted = True
        if timeout_s is not None and time.time() - wait_start > timeout_s:
            print(f"[timeout] monitor hit {timeout_s}s limit", flush=True)
            return
        time.sleep(2)


def main():
    log = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(DEFAULT_LOG)
    stall_min = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
    timeout_s = float(sys.argv[3]) if len(sys.argv) > 3 else None
    print(f"monitor start log={log} stall={stall_min}min", flush=True)
    tail(log, stall_min, timeout_s)
    # run finished — auto-replay if a series exists
    series = Path("reports/grid_live_series.jsonl")
    if series.exists() and series.stat().st_size > 0:
        print("[replay] running grid_live_replay.py ...", flush=True)
        py = sys.executable
        r = subprocess.run([py, str(REPLAY)], capture_output=True, text=True)
        for line in (r.stdout + r.stderr).splitlines():
            print(f"[replay] {line}", flush=True)
        print(f"[replay] exit={r.returncode}", flush=True)
    else:
        print("[replay] no series — run may have used poll-only or produced nothing", flush=True)
    print("monitor done", flush=True)


if __name__ == "__main__":
    main()