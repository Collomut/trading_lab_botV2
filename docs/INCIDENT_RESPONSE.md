# Incident Response

## On halt

1. Open the dashboard; read `halt_reason`.
2. Reconcile: compare local positions vs exchange positions/orders.
3. If a protective stop is missing or ambiguous, cancel duplicate orders and
   re-place the stop before resuming.
4. Resume only from a flat, reconciled account (`POST /api/resume`).

## On flash crash / outage

- The bot halts on exchange/network/account errors (fail-closed).
- After recovery, restart; positions/halt state restore from SQLite/Postgres.
- Unresolved order intents block entries until reconciled.

## On API key compromise

- Revoke the key at the exchange, rotate, update env, restart.

## Rollback

- Roll back the model: `models/registry.py::promote` to the prior version and
  restart.
- Roll back to the deterministic baseline: set `STRATEGY=baseline`, keep paper mode,
  restart.