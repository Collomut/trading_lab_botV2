# Comparison Protocol (baseline vs challenger)

This document defines the fair-comparison protocol required before any candidate
is promoted. It follows the staged plan agreed with the operator.

## Candidate systems

1. **Baseline** — `backtest/baseline.py`: the exact verified v1 strategy and
   configuration (EMA72 Donchian breakout + EMA72 exit + 4%-floored swing stop +
   100×ATR backstop target), reproduced on identical data and costs.
2. **Challenger** — `backtest/model_strategy.py` `gate_mode="full"`: the same hard
   risk controls plus the AI scorer/filter for entry and exit.
3. **Ablations** — isolates the model's contribution:
   - `ablation_prob_only` — entry gate uses probability only.
   - `ablation_return_only` — entry gate uses expected return only.
   - `ablation_model_sizing` — baseline entries, model-scaled position size.

If the universe, risk sizing, pair set, or execution assumptions change, that is a
separate candidate. Gains must not be attributed to the AI when multiple components
changed together.

## Data and backtest controls

- Both systems use identical, timestamp-aligned OHLCV, universe, start/end, starting
  equity, position constraints, and fee/slippage assumptions.
- Only information available at each decision timestamp is used. Signals use closed
  candles; fills happen at the next bar (no look-ahead).
- Chronological split: development / validation / untouched holdout. Tuning uses
  train+validation only. Every tried model, feature set, and parameter set is logged.
- Rolling/walk-forward with purging and embargo (`backtest/walkforward.py`).
- Costs modeled: taker fee (default 0.1%), base slippage (default 5 bps) plus a
  square-root market-impact term. Spread is folded into slippage (no L2 history).
  Assumptions and stress ranges are reported.
- Event-driven replay (no frictionless close fills). Edge scenarios are covered by
  the synthetic regime generator (trend up/down/range/volatile) and by stress tests.
- Uncertainty/sample counts reported. **Zero trades or tiny samples are inconclusive,
  not evidence of accuracy or safety.**

## Required metrics (per candidate, overall / per pair / per regime / per window)

- Net expectancy per completed trade after modeled costs.
- Net profit factor (gross profit and gross loss shown separately).
- Win rate, average win/loss, payoff ratio, break-even win rate.
- Max drawdown, worst trade, loss streak, tail loss, exposure, turnover, time in market.
- Trade count, number of independent periods, uncertainty intervals.
- Reconciliation error between simulated balance change and ledger P&L.
- Abstention rate, stale/missing-input rate, risk-gate blocks, runtime failures.

"Signal accuracy" must be defined precisely (e.g., probability a signal reaches a
fixed net target before a fixed net stop within a stated horizon, including fees and
no-hit labeling) before being measured. Calibration and precision/recall by confidence
band are reported but never substitute for net trading results.

## Selection-bias references

- Bailey et al., *The Probability of Backtest Overfitting*.
- Bailey & López de Prado, *The Deflated Sharpe Ratio*.
- *Beyond Agent Architecture: Execution Assumptions and Reproducibility in
  LLM-Based Trading Systems* (arXiv:2606.08285).

## Acceptance gates

A challenger is not declared better unless:

1. **Correctness:** full tests pass; safety/order/accounting paths have
   failure-injection coverage.
2. **Incremental benefit:** on the frozen holdout, the challenger improves
   predeclared net risk-adjusted objectives after costs, with uncertainty, across
   multiple markets/symbols/intervals.
3. **Risk:** drawdown and tail-loss metrics satisfy limits declared before the
   holdout is opened. Higher PF never offsets an unacceptable tail loss.
4. **Robustness:** results hold across rolling windows and regimes with stress costs;
   selection bias and all variants are disclosed.
5. **Operational safety:** no unexplained demo order/fee/balance/position/stop/ledger
   mismatch during the fixed observation period; outage/restart recovery behaves.
6. **Reproducibility:** another engineer can reproduce data snapshot, model version,
   config, commit, tests, and results.

If the challenger fails or is too uncertain, keep the deterministic baseline or
reject both. Novelty is not evidence.