"""Abstract model contract and factory."""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class BaseModel(ABC):
    """Contract every decision model must satisfy.

    The model only scores; it never touches the exchange, orders, or risk limits.
    All hard risk controls are applied by the risk/execution layers regardless of
    what the model returns.
    """

    @abstractmethod
    def predict_proba(self, features: dict[str, float]) -> float:
        """Calibrated probability that the forward return exceeds zero net of costs."""

    @abstractmethod
    def predict_return(self, features: dict[str, float]) -> float:
        """Expected forward return in percent over the configured horizon."""

    @abstractmethod
    def predict(self, features: dict[str, float]) -> tuple[float, float]:
        """Return ``(calibrated_probability, expected_return_pct)``."""

    @abstractmethod
    def should_enter_long(self, features: dict[str, float]) -> bool:
        """Whether both the probability and expected-return gates pass."""

    @abstractmethod
    def save(self, path: str) -> None: ...

    @abstractmethod
    def load(self, path: str) -> None: ...

    @property
    @abstractmethod
    def feature_names(self) -> list[str]: ...

    @property
    @abstractmethod
    def is_calibrated(self) -> bool: ...

    def predict_batch(self, X) -> tuple[np.ndarray, np.ndarray]:
        """Vectorized prediction over a feature DataFrame.

        Backends may override for speed. The default iterates row-by-row.
        """
        probs = np.empty(len(X))
        rets = np.empty(len(X))
        for pos, (_, row) in enumerate(X.iterrows()):
            p, r = self.predict(row.to_dict())
            probs[pos] = p
            rets[pos] = r
        return probs, rets


def get_model(config) -> BaseModel:
    """Instantiate a model from :class:`config.schemas.ModelConfig`."""
    from models.sklearn_model import SklearnGradientModel

    model_type = str(getattr(config, "model_type", "sklearn")).lower()
    if model_type == "sklearn":
        return SklearnGradientModel(
            feature_names=None,
            confidence_threshold=config.confidence_threshold,
            min_expected_return_pct=config.min_expected_return_pct,
            calibration_method=config.calibration_method,
        )
    if model_type == "xgboost":
        from models.xgboost_model import XGBoostModel

        return XGBoostModel(
            confidence_threshold=config.confidence_threshold,
            min_expected_return_pct=config.min_expected_return_pct,
            calibration_method=config.calibration_method,
        )
    if model_type == "lightgbm":
        from models.lightgbm_model import LightGBMModel

        return LightGBMModel(
            confidence_threshold=config.confidence_threshold,
            min_expected_return_pct=config.min_expected_return_pct,
            calibration_method=config.calibration_method,
        )
    raise ValueError(f"Unknown MODEL_TYPE: {model_type}")
