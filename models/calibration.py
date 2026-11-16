"""Probability calibration (Platt scaling / isotonic regression)."""
from __future__ import annotations

import numpy as np


class PlattCalibrator:
    """Logistic (Platt) calibration fitted on a held-out validation set."""

    def __init__(self):
        self._model = None
        self._fitted = False

    def fit(self, raw_scores: np.ndarray, labels: np.ndarray) -> "PlattCalibrator":
        from sklearn.linear_model import LogisticRegression

        x = np.asarray(raw_scores, dtype=float).reshape(-1, 1)
        y = np.asarray(labels, dtype=int)
        if len(np.unique(y)) < 2:
            # Degenerate validation set; calibration is the identity.
            self._model = None
            self._fitted = False
            return self
        self._model = LogisticRegression()
        self._model.fit(x, y)
        self._fitted = True
        return self

    def calibrate(self, raw_scores: np.ndarray) -> np.ndarray:
        scores = np.asarray(raw_scores, dtype=float).reshape(-1, 1)
        if not self._fitted or self._model is None:
            return np.clip(scores.ravel(), 0.0, 1.0)
        return self._model.predict_proba(scores)[:, 1]

    @property
    def is_fitted(self) -> bool:
        return self._fitted


class IsotonicCalibrator:
    """Isotonic regression calibration."""

    def __init__(self):
        self._model = None
        self._fitted = False

    def fit(self, raw_scores: np.ndarray, labels: np.ndarray) -> "IsotonicCalibrator":
        from sklearn.isotonic import IsotonicRegression

        x = np.asarray(raw_scores, dtype=float)
        y = np.asarray(labels, dtype=float)
        if len(np.unique(y)) < 2:
            self._model = None
            self._fitted = False
            return self
        self._model = IsotonicRegression(out_of_bounds="clip")
        self._model.fit(x, y)
        self._fitted = True
        return self

    def calibrate(self, raw_scores: np.ndarray) -> np.ndarray:
        scores = np.asarray(raw_scores, dtype=float)
        if not self._fitted or self._model is None:
            return np.clip(scores, 0.0, 1.0)
        return np.clip(self._model.predict(scores), 0.0, 1.0)

    @property
    def is_fitted(self) -> bool:
        return self._fitted


def build_calibrator(method: str):
    method = (method or "none").lower()
    if method == "platt":
        return PlattCalibrator()
    if method == "isotonic":
        return IsotonicCalibrator()
    return None


def brier_score(probabilities: np.ndarray, labels: np.ndarray) -> float:
    p = np.asarray(probabilities, dtype=float)
    y = np.asarray(labels, dtype=float)
    return float(np.mean((p - y) ** 2))


def reliability_curve(probabilities: np.ndarray, labels: np.ndarray, n_bins: int = 10) -> dict:
    """Return bin edges, predicted mean, and observed frequency per bin."""
    p = np.asarray(probabilities, dtype=float)
    y = np.asarray(labels, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, n_bins - 1)
    predicted, observed, counts = [], [], []
    for b in range(n_bins):
        mask = idx == b
        counts.append(int(mask.sum()))
        if mask.sum() == 0:
            predicted.append(None)
            observed.append(None)
        else:
            predicted.append(float(p[mask].mean()))
            observed.append(float(y[mask].mean()))
    return {"bin_edges": edges.tolist(), "predicted": predicted, "observed": observed, "counts": counts}
