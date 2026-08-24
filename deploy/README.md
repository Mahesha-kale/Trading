# Microstructure recorder deploy (Oracle Cloud Always Free)

Runs the CoinDCX trade recorder (`scripts/microstructure.py`) 24/7 on an
Always Free box, accumulating real-side CVD ticks to `reports/ticks_*.csv`
for the forward-test in `scripts/cvd_forward.py`.

## Box
Oracle Cloud Always Free **VM.Standard.A1.Flex** (ARM Ampere, 4 OCPU / 24GB),
Ubuntu. Attach a reserved public IP; open port 443 outbound (websocket). SSH
with the provisioned key.

## Setup on a fresh box
```sh
sudo apt update && sudo apt install -y python3-venv git
git clone https://github.com/Mahesha-kale/Trading.git ~/Trading
cd ~/Trading && python3 -m venv .venv && .venv/bin/pip install websockets pandas
# config: app/config.py defaults ws_url=wss://stream.coindcx.com -> no .env needed
sudo cp deploy/recorder-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now recorder-btc recorder-eth recorder-sol
```

## Operation
- Logs: `journalctl -u recorder-btc -f` (journald, auto-rotating — no log file).
- Data: `reports/ticks_B_BTC_USDT.csv` etc. (gitignored — the sample, do NOT
  commit). Single growing file per pair; ~150k rows/day/pair, ~160MB/month.
- Reconnect: in-script loop on drop (clean 1005) + systemd `Restart=always`.

## Reclamation caveat
Oracle reclaims idle Always Free instances after ~7d of low CPU+net+mem. The
recorder's continuous websocket traffic keeps net active, but verify the box
is alive each session. If reclaimed: reprovision, re-run setup, re-point at the
new public IP. The accrued ticks are on the box disk — lost on reclamation;
periodically scp down (`scp ubuntu@<ip>:~/Trading/reports/ticks_*.csv reports/`).

## Phase 1 paper-trader deploy

Runs the carry trader in PAPER mode (`--feed csv`, no `--live`, no orders) alongside the recorder.

### Prerequisites on the Oracle host
1. Repo cloned at `~/Trading` (i.e. `/home/ubuntu/Trading`) with `.venv` + `.env` (API keys; `.env` needed for the `venue_verify.py run` one-shot which signs private reads).
2. Deploy `coindcx-venue-recorder.service` (below) — the REST venue recorder writing `reports/coindcx_venue.csv`. This is a SEPARATE service from the microstructure `recorder-btc/eth/sol` units (which write `ticks_*.csv`); it must run before the paper-trader.

### Deploy
```bash
sudo cp deploy/coindcx-venue-recorder.service deploy/carry-paper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now coindcx-venue-recorder.service
sudo systemctl enable --now carry-paper.service
sudo journalctl -u carry-paper.service -f   # or tail /var/log/carry-paper.log
```

### Definitive Phase 0 venue verdict (one-shot, same host — CSV present)
```bash
cd ~/Trading
.venv/bin/python scripts/venue_verify.py run
cat reports/venue_verify.json   # verdict: PASS -> Phase 0 done, --live unlocked for Phase 2
                                 # fx_conversion FAIL -> redesign_required, hedge-redesign mandated
```

### Success criteria (7-14d)
```bash
cd ~/Trading
.venv/bin/python scripts/paper_check.py reports/carry_paper.csv reports/carry_trader_state.json 100000 14
```
PASS on all 5 criteria -> Phase 2 small-real unlocked. See spec §"Success criteria".

### Notes
- Paper mode places NO orders. `--live` is NOT set; the Phase 0 gate does not block paper.
- State persists across restarts (`reports/carry_trader_state.json`); `Restart=always` resumes.
- Recorder MUST run first (the unit `After=` it, but confirm `reports/coindcx_venue.csv` is growing).
- Kill-switch: `reports/carry_trader.HALT` → flatten all + halt. State reconciled against exchange on restart.