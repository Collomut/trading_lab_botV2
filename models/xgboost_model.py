"""Optional XGBoost backend. Requires ``pip install xgboost``."""
from __future__ import annotations

import math

import numpy as np

from models.calibration import build_calibrator
from models.model import BaseModel


class XGBoostModel(BaseModel):
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

    @property
    def feature_names(self) -> list[str]:
        return self._feature_names

    @property
    def is_calibrated(self) -> bool:
        return self._is_calibrated

    def train(self, X, y_class, y_reg, X_val=None, y_val_class=None, *, random_state: int = 42) -> dict:
        import xgboost as xgb

        self._feature_names = list(X.columns)
        base = dict(
            max_depth=6,
            learning_rate=0.05,
            n_estimators=400,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=3,
            gamma=1.0,
            tree_method="hist",
            random_state=random_state,
        )
        self.classifier = xgb.XGBClassifier(objective="binary:logistic", eval_metric="auc", **base)
        self.classifier.fit(X, np.asarray(y_class, dtype=int))
        self.regressor = xgb.XGBRegressor(objective="reg:squarederror", **base)
        self.regressor.fit(X, np.asarray(y_reg, dtype=float))
        metrics: dict = {}
        if X_val is not None and y_val_class is not None and len(X_val) > 0:
            raw = self.classifier.predict_proba(X_val)[:, 1]
            metrics["mean_expected_return_pct"] = float(np.mean(self.regressor.predict(X_val)) * 100.0)
            calibrator = build_calibrator(self.calibration_method)
            if calibrator is not None:
                calibrator.fit(raw, y_val_class)
                if getattr(calibrator, "is_fitted", False):
                    self.calibrator = calibrator
                    self._is_calibrated = True
        return metrics

    def _vector(self, features):
        return np.array([[float(features[name]) for name in self._feature_names]], dtype=float)

    def predict_proba(self, features):
        if self.classifier is None:
            return 0.0
        raw = self.classifier.predict_proba(self._vector(features))[:, 1]
        if self.calibrator is not None and getattr(self.calibrator, "is_fitted", False):
            return float(self.calibrator.calibrate(raw)[0])
        return float(np.clip(raw, 0.0, 1.0)[0])

    def predict_return(self, features):
        if self.regressor is None:
            return 0.0
        return float(self.regressor.predict(self._vector(features))[0]) * 100.0

    def predict(self, features):
        p, r = self.predict_proba(features), self.predict_return(features)
        return (p if math.isfinite(p) else 0.0, r if math.isfinite(r) else 0.0)

    def should_enter_long(self, features):
        p, r = self.predict(features)
        return p >= self.confidence_threshold and r >= self.min_expected_return_pct

    def save(self, path):
        import joblib

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

    def load(self, path):
        import joblib

        data = joblib.load(path)
        self._feature_names = list(data["feature_names"])
        self.classifier = data["classifier"]
        self.regressor = data["regressor"]
        self.calibrator = data.get("calibrator")
        self._is_calibrated = bool(data.get("is_calibrated", False))
