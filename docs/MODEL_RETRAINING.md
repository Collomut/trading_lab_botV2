# Model Retraining

## Schedule

- Weekly: retrain on the latest 2 years of data.
- Immediate: if rolling profit factor < 1.0 for 5 consecutive days.

## Pipeline

1. Download latest OHLCV (`python main.py download ...`).
2. Train with walk-forward validation (`python main.py train ...`).
3. If validation PF > production, shadow-deploy (`models/registry.py::shadow_deploy`).
4. Shadow for 7 days (decisions logged, not executed).
5. If shadow PF > production PF, promote; update `MODEL_PATH` and restart.

## Rollback

- Keep the last 3 versions.
- On a model-related halt, revert to the previous version and restart.