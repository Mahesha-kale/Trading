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
## Tuning, resume, and the deployed grid

**Deployed grid lives in `reports/grid_bot.json`** (`deployed` field), set by
`scripts/grid_bot.py`. `grid_live.py` reads it on start; CLI `g`/`K` args still
override. The Windows launcher (`grid_schedule.bat`) and the container both
omit `g`/`K` so they auto-follow tuning — re-tune in one place.

Why not the `best_grid` (train-argmax)? Train Sharpe over-fits to wide spacing
(trends inflate it); the live default used to be `g=0.02 K=20` (best train,
worst OOS in its row) and **flatlined for 12h** because BTC rarely moves 2%
in a day. Deployed is `g=0.008 K=10`: OOS Sharpe ~1.43, smallest train→OOS
drop among high-OOS grids, and 0.8% spacing fires fills in sub-day windows.
The full train-vs-OOS surface is saved in `grid_bot.json` for audit.

**Resume after a crash/reboot.** Log and series are opened in **append** mode
with a per-tick **flush** — a machine drop mid-run loses no data. On start,
`grid_live.py` replays the existing `grid_live_series.jsonl` through a fresh
`GridBot` to rebuild anchor / open buys / cash exactly (the series is the
single source of truth — no checkpoint file to drift from). If the grid
config changed since the series was recorded, it truncates and starts fresh
(can't safely mix grids in one series). `restart: unless-stopped` (container)
or Task Scheduler "restart on failure" (Windows) relaunches after a drop,
and the run resumes from the series.

## Cloud / overnight container

`docker compose up grid` runs the live runner as a restartable service
(`docker-compose.yml` → `grid`). It shares the app image, mounts `./reports`
so the series survives container recreation, and follows the deployed grid.
On a cloud VM with Docker set to start on boot, a reboot → daemon restart →
`grid` container restarts → `grid_live.py` resumes from the mounted series.
Monitor (`scripts/grid_monitor.py`) is not run in the container by default —
add it (a second command/sidecar) when you want feed-death alerts in the cloud.

## Status: edge refuted under real CoinDCX costs (2026-08)

The spot-grid line is **not deployable**. Pulling fresh Binance history through
2026-07 and modeling the real CoinDCX costs (0.169% taker + 18% GST = 0.19942%
per leg, plus **1% TDS on every sell notional**) refuted the edge:

- Long-only: negative on the 2025-2026 OOS (Sharpe -1.02, end 6621, DD -40%).
  The 2023-2025 "edge" was a regime artifact AND was overstated by the old
  FEE=0.001 model that ignored TDS.
- Long/short with the long side gated by close>SMA200: OOS Sharpe 0.67 looks
  positive, but it BLOWS UP in-sample (train DD -124%) — ungated shorts explode
  in the 2023-25 uptrend. The OOS "edge" is only because OOS was a downtrend.
- Regime-switch (long above SMA200, short below): bounds the shorts but only
  breaks even on OOS and loses in-sample.

1% TDS per sell is the structural killer: a round trip costs ~1.4%, so a grid
needs g >> 1.4% to profit, but wide grids fill rarely and still bleed in trends.
`reports/grid_bot.json` has `deployable: false`, `deployed: null`. `grid_live.py`
prints a WARNING when run against a refuted strategy (paper for divergence
validation only).

The scheduled Task Scheduler jobs (`grid_live_daily`, `grid_live_now`,
`grid_run_now`) have been **disabled** — no point running 12h paper loops of a
losing strategy. Re-enable only if a new config proves a positive OOS edge.

The double-launch guard in `scripts/grid_schedule.bat` is known to race (two
concurrent grid_live processes were observed) — fix with a file lock before
re-enabling unattended runs.
