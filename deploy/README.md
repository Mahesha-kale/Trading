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