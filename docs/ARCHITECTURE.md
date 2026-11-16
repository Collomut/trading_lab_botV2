# trade_v2 — Architecture & Decision Protocol

## What this is

`trade_v2` is a model-based crypto trading system. A trained ML model produces
entry signals; **hard risk controls** (fixed-fractional sizing, stops, circuit
breakers) are applied by the execution layer regardless of what the model says.
The system is paper/testnet by default and refuses live trading unless explicit
guards are satisfied.

## Design principles

1. **Model-only decisions.** An ML model scores each completed candle. Traditional
   TA (EMA/RSI/ADX) exists only as model input features, not as standalone rules.
2. **Profit factor ≥ 1.5 is the north star.** Every candidate is measured on net
   expectancy after modeled costs, not win rate or gross return.
3. **Fail-closed.** Missing fees, ambiguous fills, or state mismatches halt trading.
4. **Live-ready architecture.** Paper vs live is a property of the exchange adapter,
   not of the trading logic.
5. **Fair baseline comparison.** The AI challenger is evaluated against the
   deterministic v1 baseline on identical data, costs, and risk controls.

## Module map

| Path | Responsibility |
|------|----------------|
| `config/` | Typed config, fail-fast validation |
| `data/` | OHLCV download, cache, integrity validation, synthetic generator |
| `models/` | Causal feature engineering, gradient-boosted model, calibration, training, registry |
| `backtest/` | Event-driven engine with realistic costs; baseline, challenger, ablations |
| `risk/` | Sizing, stops, circuit breakers, pre-trade validators, position lifecycle |
| `execution/` | CCXT connector, order state machine, fill normalization, simulated exchange |
| `live/` | Live loop, kill switch, scheduler, heartbeat |
| `monitoring/` | Dashboard, alerts, audit logging |
| `state/` | SQLite (default) + optional Postgres, order/audit/trade persistence |

## Decision path (per completed 1h candle)

```
1. Fetch closed OHLCV (no forming candle) + order book + price.
2. Reconcile account state with the exchange. Mismatch -> halt.
3. Monitor equity -> daily-loss and rolling-drawdown breakers.
4. Manage open positions: stop, trailing, break-even, time-stop, model exit.
5. For each flat symbol:
     a. Compute causal feature vector.
     b. Model -> (calibrated probability, expected return %).
     c. Entry gate: prob >= CONFIDENCE_THRESHOLD AND
        expected_return >= MIN_EXPECTED_RETURN_PCT AND regime gate.
     d. Preflight: spread, depth, notional, balance, correlation.
     e. Risk manager: can_open_position (entry mode, halt, route halts, position cap).
     f. Size: fixed-fractional (1% risk) scaled by confidence & volatility,
        capped by notional %. Round to exchange precision.
     g. Place native stop on the exchange; persist position.
     h. Record audit + alert.
6. Every 60s (configurable) or on new candle.
```

## Key safety properties

- **Two-person rule for live.** `PAPER_TRADING=false` + `ALLOW_LIVE_TRADING=true`
  + `LIVE_CONFIRMATION=I_UNDERSTAND_REAL_MONEY_IS_AT_RISK` are all required.
- **Model cannot change risk limits.** The model only returns a probability and an
  expected return; risk is enforced by `risk/manager.py` and `risk/validators.py`.
- **LLM isolation.** Any future LLM-based summarization/explanation is kept out of
  the price-sensitive decision path and documented as an offline helper only.
- **Deterministic baseline.** The v1 EMA72/Donchian rule is reproduced in
  `backtest/baseline.py` for an apples-to-apples comparison.

## Configuration

See `.env.example` for all keys. Validation lives in `config/loader.py`.

## Data

Real data: `python main.py download --symbol BTC/USDT --start 2024-01-01 --end 2026-01-01`.
Offline demo: `--synthetic` generates deterministic OHLCV for pipeline tests (not market data).

## Model

Default backend: `sklearn` HistGradientBoosting (no optional deps). Optional
`xgboost` / `lightgbm` backends. Probabilities are calibrated (Platt/isotonic) on
held-out data so they can drive confidence-scaled sizing.