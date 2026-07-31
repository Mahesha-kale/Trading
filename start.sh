#!/usr/bin/env bash
# One-command start: venv + deps + infra (postgres/redis) + API + frontend dev.
# Idempotent — skips installs that are already done. Ctrl-C stops everything.
# Prod alternative (full docker, nginx):  docker compose up --build
set -euo pipefail
cd "$(dirname "$0")"

echo "[1/4] python venv + deps"
if [ ! -d .venv ]; then python -m venv .venv; fi
# shellcheck disable=SC1091
. .venv/Scripts/activate 2>/dev/null || . .venv/bin/activate
pip install -e ".[dev]" -q

echo "[2/4] frontend deps"
if [ ! -d frontend/node_modules ]; then (cd frontend && npm install); fi

echo "[3/4] infra (postgres + redis), waiting for healthy"
docker compose up -d --wait postgres redis

echo "[4/4] API (:8000) + frontend (:5173)"
trap 'kill 0' EXIT INT TERM
python -m app.main serve &
(cd frontend && npm run dev) &
wait