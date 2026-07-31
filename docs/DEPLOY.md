# Deployment

## Docker Compose
`docker compose up -d` starts postgres, redis, api, nginx.
- API: container `api` (uvicorn)
- nginx: ports 80 -> `/api/` proxied to api, `/` serves frontend static

## Production checklist
- [ ] Alembic migrations instead of `create_all`
- [ ] Postgres password + secrets via Docker secrets / vault, not `.env`
- [ ] HTTPS termination (add certs to nginx or use a LB)
- [ ] Log aggregation; `structlog` ConsoleRenderer -> JSON renderer in prod
- [ ] Healthcheck + restart policy on `api`
- [ ] Monitoring: latency endpoint, PnL alert via Telegram kill-switch
- [ ] Funding rate feed: currently fixed 0.01%/8h in backtest; pull real funding for live accuracy

## Scaling / extensibility
Add a futures pair: it's just a `symbol`/`pair` string threaded through config + clients — no code change. Per-pair risk overrides: extend `RiskManager` to key state by symbol.