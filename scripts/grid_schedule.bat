@echo off
REM Daily unattended launcher for the spot grid live run + monitor.
REM Guard: skip if a grid_live.py run is already active (a hung/overrun prior
REM run would otherwise collide on the fixed report paths).
cd /d D:\Programming\Trading
powershell -NoProfile -Command "if (Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object {$_.CommandLine -like '*grid_live.py*'}) { exit 1 } else { exit 0 }"
if errorlevel 1 (
  echo %date% %time% skip: grid_live.py already running >> reports\grid_schedule.log
  exit /b 0
)

echo %date% %time% launch: grid_live 12h + monitor >> reports\grid_schedule.log
REM Detached: live run (12h), then monitor (runs until done, auto-replays).
REM g/K omitted -> grid_live.py reads the deployed grid from reports/grid_bot.json.
start "" cmd /c ".venv\Scripts\python.exe scripts\grid_live.py B-BTC_USDT 43200 > reports\grid_live_scheduled.log 2>&1"
timeout /t 5 /nobreak >nul
start "" cmd /c ".venv\Scripts\python.exe scripts\grid_monitor.py reports\grid_live_scheduled.log 5 > reports\grid_monitor_scheduled.log 2>&1"
exit /b 0