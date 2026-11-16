# API Keys — secure exchange setup

1. Create a **Spot Testnet** key at https://testnet.binance.vision for paper testing.
   Put `API_KEY` / `API_SECRET` in `.env` (never commit).
2. For Binance Demo mode, create demo keys and set `DEMO_API_KEY` / `DEMO_API_SECRET`
   with `PAPER_ENVIRONMENT=demo`.
3. Restrict keys:
   - Enable **Spot trading only**.
   - **Disable withdrawals.**
   - Set an **IP whitelist** (Railway egress IPs or your fixed IP).
4. Never enable `ALLOW_LIVE_TRADING=true` until the live-readiness checklist passes.
5. Rotate keys immediately if leaked; update Railway/Docker env, restart.

Required env for live (all must be present):
- `PAPER_TRADING=false`
- `ALLOW_LIVE_TRADING=true`
- `LIVE_CONFIRMATION=I_UNDERSTAND_REAL_MONEY_IS_AT_RISK`