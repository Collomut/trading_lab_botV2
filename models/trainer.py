"""Walk-forward model training and evaluation."""
from __future__ import annotations

import numpy as np
import pandas as pd

from config.schemas import ModelConfig
from models.features import FeatureEngine
from models.model import BaseModel, get_model


class ModelTrainer:
    """Build datasets and train/evaluate the decision model chronologically."""

    def __init__(self, feature_engine: FeatureEngine, model_config: ModelConfig):
        self.engine = feature_engine
        self.config = model_config

    # -- dataset ------------------------------------------------------------
    def build_dataset(
        self, df: pd.DataFrame, *, cost_pct: float = 0.0
    ) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
        """Return ``(X, y_class, y_reg)`` with no future data in the features."""
        features = self.engine.compute_matrix(df)
        forward = self.engine.forward_return_labels(df, self.config.horizon_bars, cost_pct=cost_pct)
        frame = features.copy()
        frame["__forward__"] = forward
        # Only rows with a complete feature vector AND a realized forward label.
        valid = frame["__forward__"].notna() & features.notna().all(axis=1)
        frame = frame[valid]
        if frame.empty:
            return pd.DataFrame(columns=features.columns), np.array([]), np.array([])
        X = frame[features.columns]
        y_reg = frame["__forward__"].to_numpy(dtype=float)
        y_class = (y_reg > 0.0).astype(int)
        return X, y_class, y_reg

    # -- splits -------------------------------------------------------------
    @staticmethod
    def chronological_split(n: int, train_frac: float = 0.7, val_frac: float = 0.15):
        train_end = int(n * train_frac)
        val_end = int(n * (train_frac + val_frac))
        return (
            np.arange(0, train_end),
            np.arange(train_end, val_end),
            np.arange(val_end, n),
        )

    @staticmethod
    def walk_forward_indices(n: int, n_splits: int = 3) -> list[tuple[np.ndarray, np.ndarray]]:
        """Expanding-window splits; each fold validates on the next untouched block."""
        if n < (n_splits + 1) * 2:
            return []
        boundaries = np.linspace(0, n, n_splits + 2, dtype=int)
        folds = []
        for k in range(1, n_splits + 1):
            train = np.arange(0, boundaries[k])
            val = np.arange(boundaries[k], boundaries[k + 1])
            if len(train) > 0 and len(val) > 0:
                folds.append((train, val))
        return folds

    # -- training -----------------------------------------------------------
    def train(self, df: pd.DataFrame, *, cost_pct: float = 0.0, random_state: int = 42):
        X, y_class, y_reg = self.build_dataset(df, cost_pct=cost_pct)
        if len(X) < 200:
            raise ValueError(f"Insufficient training rows: {len(X)}")
        tr, va, _ = self.chronological_split(len(X))
        model = get_model(self.config)
        metrics = model.train(
            X.iloc[tr],
            y_class[tr],
            y_reg[tr],
            X.iloc[va],
            y_class[va],
            random_state=random_state,
        )
        metrics["train_rows"] = int(len(tr))
        metrics["val_rows"] = int(len(va))
        metrics["feature_count"] = int(X.shape[1])
        return model, metrics

    def walk_forward(self, df: pd.DataFrame, *, cost_pct: float = 0.0, n_splits: int = 3) -> list[dict]:
        X, y_class, y_reg = self.build_dataset(df, cost_pct=cost_pct)
        results: list[dict] = []
        for fold_idx, (tr, va) in enumerate(self.walk_forward_indices(len(X), n_splits)):
            if len(tr) < 200 or len(va) < 20:
                continue
            model = get_model(self.config)
            metrics = model.train(
                X.iloc[tr], y_class[tr], y_reg[tr], X.iloc[va], y_class[va]
            )
            # Baseline prevalence for context.
            metrics.update(
                {
                    "fold": fold_idx,
                    "train_rows": int(len(tr)),
                    "val_rows": int(len(va)),
                    "val_positive_rate": float(np.mean(y_class[va])),
                }
            )
            results.append(metrics)
        return results
