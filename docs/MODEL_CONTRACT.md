# Model contract, input dictionary, and latency/privacy/cost notes.

## Model input/output contract

- **Input:** a causal feature dict of 30 floats per closed bar, produced by
  `models/features.py::FeatureEngine.compute()`. Names are fixed in
  `FeatureEngine._feature_names()` and versioned by `FEATURE_VERSION`.
- **Output:** `(calibrated_probability, expected_return_pct)` via
  `BaseModel.predict()`. `predict_batch` provides vectorized scoring.
- **Decision:** `should_enter_long(features)` = probability >= confidence threshold
  AND expected return >= min expected return. The hard stop and sizing are applied
  by the risk layer regardless of this boolean.

## Feature dictionary (30 features, all causal)

| Group | Features |
|-------|----------|
| Returns | `ret_1`, `ret_3`, `ret_6`, `ret_12`, `ret_24`, `log_ret` |
| Trend | `price_vs_ema20`, `price_vs_ema50`, `price_vs_ema200`, `ema20_slope`, `ema50_slope`, `ema200_slope` |
| Volatility | `atr_14`, `atr_pct`, `parkinson_vol`, `realized_vol_24`, `vol_percentile_30d` |
| Regime | `adx_14`, `rsi_14`, `regime_uptrend`, `regime_downtrend`, `regime_range`, `regime_high_vol`, `regime_transition` |
| Volume | `volume_ratio` |
| Time | `hour_sin`, `hour_cos`, `dow_sin`, `dow_cos`, `is_weekend` |

## Model hosting / API availability

- Models are local artifacts (`models/artifacts/<version>/model.joblib`), loaded in
  process. There is no external model API to depend on, so inference does not fail
  on a third-party outage.
- If a model endpoint is ever used, it must be local-first with a cached fallback;
  an unavailable model **blocks entries** (fail-closed) rather than falling back to
  unverified rules.

## Latency

- Prediction is batched (`predict_batch`) over all valid rows; typical per-cycle
  inference is milliseconds for a few symbols on hourly bars.
- Trading cadence is configurable (`INTERVAL_SECONDS`, default 60s). The dashboard
  status cache TTL is 5s. Latency percentiles should be measured in shadow mode.

## Data privacy

- Exchange API keys, dashboard token, and notification secrets live only in
  environment variables; `.env` is gitignored.
- Audit logs redact sensitive keys (`monitoring/logger.py::AuditLog`).
- No trade/account data is sent to third parties. Model artifacts contain only
  numeric parameters and feature names, never user data.

## Cost

- Paper/testnet is free. Railway/Docker compute is the main cost. Postgres is
  optional (SQLite by default). No paid model API is used by default.

## Outage behavior

- Exchange API failure -> `AccountAccessError` -> reconcile -> halt entries.
- Missing/stale candles -> cycle records an error event and does not trade.
- Model artifact missing -> startup fails fast (train first).
- State store write failure -> halt.
- Process restart -> positions/halt state restored from SQLite/Postgres; unresolved
  order intents block entries until reconciled.

## Rollback to deterministic baseline

- The deterministic v1 baseline is fully implemented in `backtest/baseline.py` and
  can run live with `STRATEGY=baseline` (see README). To roll back:
  1. Set `STRATEGY=baseline` (or point to a baseline model/config).
  2. Keep `PAPER_TRADING=true`.
  3. Restart; the same risk controls and execution path are used.
- Model versioning: each trained model is saved under `models/artifacts/<version>/`
  with `metrics.json`. `models/registry.py::promote` records the production version,
  enabling instant rollback to the prior version.

## LLM boundary

An LLM may later summarize operator logs or explain recorded decisions, but it is
**not** part of the price-sensitive decision/execution path unless a reproducible
experiment proves a benefit. Any such feature must be behind a flag and validated
against the same acceptance gates.