# Deployment

## Docker (local)

```bash
docker build -f docker/Dockerfile -t trade_v2 .
docker run --rm -p 5000:5000 --env-file .env trade_v2
```

## Railway

- One replica only (SQLite is single-writer). Use Postgres (`DATABASE_URL`) if you
  must scale or want a managed DB. The Postgres driver is `psycopg[binary,pool]`;
  without the `pool` extra the store fails at startup with
  `Postgres store unavailable: missing psycopg_pool`.
- Mount a persistent volume at `/app/data` and set `DATA_DIR=/app/data`.
- Set env in the Railway dashboard, not in the repo.
- Railway injects `PORT`; the dashboard binds it automatically unless `--port`
  is passed explicitly.
- Health checks: `/health/liveness` and `/health/readiness` (public).
- Sign in at `/login` with the value of `DASHBOARD_TOKEN`. A successful sign-in
  sets an HttpOnly, `SameSite=Strict` session cookie (12-hour expiry); scripts
  can still use `X-Dashboard-Token` or `Authorization: Bearer <token>` instead.
  Use **Sign out** in the dashboard to revoke the session.

## Troubleshooting

### `Postgres store unavailable: missing psycopg_pool` (crash loop)

`DATABASE_URL` is set but the image does not contain the driver extra. Rebuild
after ensuring the dependency is installed:

```bash
pip install 'psycopg[binary,pool]>=3.2'   # or pip install -e '.[postgres]'
```

Alternatively clear `DATABASE_URL` to fall back to the SQLite store (single
replica only).


## Startup sequence

1. Load + validate config (fail fast).
2. Build state store (SQLite or Postgres).
3. Reconcile account state with the exchange (halt on mismatch).
4. Start dashboard; start trading loop (paper/live).

## Environment matrix

| Mode | PAPER_TRADING | PAPER_ENVIRONMENT | ALLOW_LIVE_TRADING | Result |
|------|---------------|-------------------|--------------------|--------|
| Simulated | true | simulated | false | virtual wallet, real market data |
| Testnet | true | testnet | false | Binance Spot Testnet |
| Demo | true | demo | false | Binance Demo |
| Live | false | - | true | real funds (guarded) |