# Spot Grid — Live Forward Validation

The spot grid bot (`scripts/grid_bot.py`) is the first strategy with positive
out-of-sample edge (BTC OOS Sharpe 1.11, rolling mean 1.6; ETH left out —
weak, see `reports/grid_harden.json`). These scripts validate that edge
survives live, tick-by-tick data — not just the 15m-close backtest.

## Pieces

| Script | Role |
|--------|------|
| `scripts/grid_bot.py` | `GridBot` + backtest. Shared by backtest and live (no divergence). |
| `scripts/grid_live.py` | Live paper runner. Socket.IO stream → `GridBot.step`. Logs fills + equity series. |
| `scripts/grid_live_replay.py` | After a run: sanity (drift 0) + 15m-resample divergence vs the live tick path. |
| `scripts/grid_monitor.py` | Tails a run log; alerts on fills / feed death / stall; auto-runs replay on completion. |
| `scripts/grid_schedule.bat` | Unattended launcher (double-launch guard) for Task Scheduler. |

## Live runner

CoinDCX public stream is **Socket.IO v2.4.0** (`wss://stream.coindcx.com`), not
raw WebSocket — a raw `websockets` client 503s on the Engine.IO handshake. The
spot LTP channel is `{pair}@prices` (event `price-change`, field `p`); the
payload's `data` is a JSON **string**, not a dict. If the feed is unavailable
after retries, the runner falls back to polling the 1m candle close every 60s.

```bash
.venv/Scripts/python scripts/grid_live.py B-BTC_USDT 43200 0.02 20
# args: pair  run_seconds  grid_spacing  rungs   (defaults 3600s / 0.02 / 20)
```

Writes:
- `reports/grid_live.jsonl` — human log lines
- `reports/grid_live_series.jsonl` — `{ts, px, eq}` per tick (for the replay)
- `reports/grid_live_summary.json` — final equity / pnl / open buys

## Divergence replay

The backtest steps 15m closes; live steps every tick. The replay asks how much
equity diverges between the two on the **same realized price path**:

1. **sanity** — replays recorded ticks through a fresh `GridBot`; final equity
   must equal the live run's recorded final equity (drift ~0). Catches loop/state bugs.
2. **divergence** — resamples the live path to 15m closes, re-runs `GridBot`,
   compares equity. Gap = intra-bar effect the close-only backtest cannot see.
   `+` = backtest under-states live; `-` = backtest over-states live.

```bash
.venv/Scripts/python scripts/grid_live_replay.py
```

**<50 15m bars is noise.** Run ≥12h (~50 bars) before trusting the gap. 1h = 4 bars = meaningless.

## Monitor

```bash
.venv/Scripts/python scripts/grid_monitor.py reports/grid_live_overnight.log 5
# args: log_path  stall_minutes   (default 5)
```

Emits one line per `[fill]` / `[feed_issue]` (503 / failed / unavailable) /
`[stall]` (no log line for N min — the real WS-drop failure mode) / `[done]`.
On `done:`, auto-runs the replay and prints its verdict. Stall detection uses
the ISO timestamp on each log line (a real clock), not file mtime.

## Unattended runs (survive Claude / reboots)

Background runs started inside a Claude Code session **die when the session
closes.** For runs that must survive, use Windows Task Scheduler, which launches
processes independent of Claude.

Register once (any prompt — `dd-MM-yyyy` date locale on this box):
```cmd
schtasks /create /tn grid_live_daily /tr "D:\Programming\Trading\scripts\grid_schedule.bat" /sc daily /st 00:00 /f
```

Start one run now (independent of Claude):
```cmd
schtasks /create /tn grid_live_now /tr "D:\Programming\Trading\scripts\grid_schedule.bat" /sc once /st 02:41 /sd 06-08-2026 /f
```

The bat guards against double-launch (skips if `grid_live.py` already running)
and appends an audit line to `reports/grid_schedule.log`. Both launched
processes are detached, so the Task Scheduler job returns immediately.

Manage:
```cmd
schtasks /query /tn grid_live_daily /v   :: status / last run
schtasks /delete /tn grid_live_daily /f   :: stop scheduling
```

Caveat: runs "only when user is logged on" by default. Lock the screen (don't
log off) overnight. For true logoff-proof runs, register with `/rl highest`
and a wake-timer (needs your account password).

**Process-count gotcha:** a single grid run shows as **2 OS processes** —
`.venv\Scripts\python.exe` (the venv launcher stub) re-execs the base interpreter
(`pythoncore-3.14\python.exe`). So `live=2 monitor=2` means one run + one
monitor, not a double-launch. The double-launch guard checks for *any*
`grid_live.py` process and still works (it matches both).

## Next-day checklist

1. `reports/grid_live_replay.json` — sanity drift (must be ~0) + divergence gap.
2. `reports/grid_monitor_scheduled.log` — any `[feed_issue]` / `[stall]` lines.
3. `reports/grid_live_summary.json` — final pnl / open buys.
4. If divergence gap is small and sane → live edge confirmed at this resolution.
   If large/negative → the close-only backtest over-states; tighten the fee/slippage model or re-tune `g`/`K`.
5. For a sharper divergence signal, run longer (overnight = ~50 bars).