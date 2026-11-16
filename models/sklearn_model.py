"""Default sklearn gradient-boosting model (no optional dependencies)."""
from __future__ import annotations

import math

import joblib
import numpy as np

from models.calibration import build_calibrator
from models.model import BaseModel


class SklearnGradientModel(BaseModel):
    """HistGradientBoosting classifier + regressor with optional calibration.

    The classifier predicts direction (forward return > 0); the regressor predicts
    the forward return magnitude. Probabilities are calibrated on held-out data so
    they can be used for confidence-scaled sizing.
    """

    def __init__(
        self,
        feature_names: list[str] | None = None,
        *,
        confidence_threshold: float = 0.60,
        min_expected_return_pct: float = 1.5,
        calibration_method: str = "platt",
    ):
        self._feature_names = list(feature_names) if feature_names else []
        self.confidence_threshold = float(confidence_threshold)
        self.min_expected_return_pct = float(min_expected_return_pct)
        self.calibration_method = calibration_method
        self.classifier = None
        self.regressor = None
        self.calibrator = None
        self._is_calibrated = False

    # -- training -----------------------------------------------------------
    def train(
        self,
        X,
        y_class: np.ndarray,
        y_reg: np.ndarray,
        X_val=None,
        y_val_class: np.ndarray | None = None,
        *,
        random_state: int = 42,
    ) -> dict:
        from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

        self._feature_names = list(X.columns)
        self.classifier = HistGradientBoostingClassifier(
            max_depth=6,
            learning_rate=0.05,
            max_iter=400,
            l2_regularization=1.0,
            min_samples_leaf=40,
            random_state=random_state,
        )
        self.classifier.fit(X, np.asarray(y_class, dtype=int))

        self.regressor = HistGradientBoostingRegressor(
            max_depth=6,
            learning_rate=0.05,
            max_iter=400,
            l2_regularization=1.0,
            min_samples_leaf=40,
            random_state=random_state,
        )
        self.regressor.fit(X, np.asarray(y_reg, dtype=float))

        metrics: dict = {}
        if X_val is not None and y_val_class is not None and len(X_val) > 0:
            raw = self.classifier.predict_proba(X_val)[:, 1]
            raw_reg = self.regressor.predict(X_val)
            from sklearn.metrics import roc_auc_score

            try:
                metrics["auc"] = float(roc_auc_score(y_val_class, raw)) if len(np.unique(y_val_class)) > 1 else None
            except Exception:
                metrics["auc"] = None
            metrics["mean_expected_return_pct"] = float(np.mean(raw_reg) * 100.0)

            calibrator = build_calibrator(self.calibration_method)
            if calibrator is not None:
                calibrator.fit(raw, y_val_class)
                if getattr(calibrator, "is_fitted", False):
                    self.calibrator = calibrator
                    self._is_calibrated = True
            cal = self._calibrate(raw)
            from models.calibration import brier_score

            metrics["brier_raw"] = brier_score(raw, y_val_class)
            metrics["brier_calibrated"] = brier_score(cal, y_val_class)
        return metrics

    # -- inference ----------------------------------------------------------
    @property
    def feature_names(self) -> list[str]:
        return self._feature_names

    @property
    def is_calibrated(self) -> bool:
        return self._is_calibrated

    def _vector(self, features: dict[str, float]):
        import pandas as pd

        return pd.DataFrame(
            [[float(features[name]) for name in self._feature_names]],
            columns=self._feature_names,
        )

    def _calibrate(self, raw: np.ndarray) -> np.ndarray:
        if self.calibrator is not None and getattr(self.calibrator, "is_fitted", False):
            return self.calibrator.calibrate(raw)
        return np.clip(np.asarray(raw, dtype=float), 0.0, 1.0)

    def predict_proba(self, features: dict[str, float]) -> float:
        if self.classifier is None:
            return 0.0
        raw = self.classifier.predict_proba(self._vector(features))[:, 1]
        return float(self._calibrate(raw)[0])

    def predict_return(self, features: dict[str, float]) -> float:
        if self.regressor is None:
            return 0.0
        pred = float(self.regressor.predict(self._vector(features))[0])
        return pred * 100.0  # fraction -> percent

    def predict(self, features: dict[str, float]) -> tuple[float, float]:
        prob = self.predict_proba(features)
        ret = self.predict_return(features)
        if not math.isfinite(prob):
            prob = 0.0
        if not math.isfinite(ret):
            ret = 0.0
        return prob, ret

    def should_enter_long(self, features: dict[str, float]) -> bool:
        prob, ret = self.predict(features)
        return prob >= self.confidence_threshold and ret >= self.min_expected_return_pct

    def predict_batch(self, X):
        import numpy as np

        if self.classifier is None or self.regressor is None:
            return np.zeros(len(X)), np.zeros(len(X))
        raw = self.classifier.predict_proba(X)[:, 1]
        probs = self._calibrate(raw)
        rets = self.regressor.predict(X) * 100.0
        return probs, rets

    # -- persistence --------------------------------------------------------
    def save(self, path: str) -> None:
        joblib.dump(
            {
                "feature_names": self._feature_names,
                "classifier": self.classifier,
                "regressor": self.regressor,
                "calibrator": self.calibrator,
                "is_calibrated": self._is_calibrated,
                "confidence_threshold": self.confidence_threshold,
                "min_expected_return_pct": self.min_expected_return_pct,
                "calibration_method": self.calibration_method,
            },
            path,
        )

    def load(self, path: str) -> None:
        data = joblib.load(path)
        self._feature_names = list(data["feature_names"])
        self.classifier = data["classifier"]
        self.regressor = data["regressor"]
        self.calibrator = data.get("calibrator")
        self._is_calibrated = bool(data.get("is_calibrated", False))
        self.confidence_threshold = float(data.get("confidence_threshold", self.confidence_threshold))
        self.min_expected_return_pct = float(
            data.get("min_expected_return_pct", self.min_expected_return_pct)
        )
        self.calibration_method = data.get("calibration_method", self.calibration_method)

    def get_feature_importance(self) -> dict[str, float]:
        # HistGradientBoosting has no native importances; return permutation-free
        # uniform placeholder for dashboard display only.
        return {name: 1.0 / max(1, len(self._feature_names)) for name in self._feature_names}
