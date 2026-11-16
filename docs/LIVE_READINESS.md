# Live Readiness Checklist

Must be 100% complete before `ALLOW_LIVE_TRADING=true`:

```
[ ] All unit + integration tests pass
[ ] Coverage >= 90% on risk/, execution/, models/, backtest/
[ ] Walk-forward: PF > 1.3 on all holdout folds
[ ] Max drawdown < 8% on all holdout folds
[ ] Calmar > 0.5 on all holdout folds
[ ] Calibration verified (Brier improved)
[ ] Paper traded 30+ consecutive days
[ ] Paper PF > 1.2 over 30 days
[ ] No circuit-breaker trips during paper period
[ ] Daily reconciliation verified
[ ] Dashboard token set (32+ chars)
[ ] API keys Spot-only, withdrawals disabled, IP whitelisted
[ ] Alerts tested (Telegram/email/Discord)
[ ] Emergency stop tested
[ ] Resume tested
[ ] Model retraining tested
[ ] Rollback procedure tested
[ ] Incident runbook reviewed
[ ] Two-person rule configured (ALLOW_LIVE_TRADING + LIVE_CONFIRMATION)
```