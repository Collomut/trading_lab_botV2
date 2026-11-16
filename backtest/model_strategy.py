"""AI challenger strategy: model-scored entries with model-based exits.

The model only supplies the entry probability and expected return. The hard stop,
position sizing, and circuit breakers are applied by the engine/risk layer, so the
challenger shares identical hard risk controls with the deterministic baseline.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.types import SignalDecision
from models.features import FeatureEngine
from models.model import BaseModel


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()


class ModelStrategy:
    name = "challenger_model"

    def __init__(
        self,
        model: BaseModel,
        feature_engine: FeatureEngine | None = None,
        *,
        exit_probability: float = 0.40,
        use_model_exit: bool = True,
        take_profit_atr_multiple: float | None = None,
        min_candles: int | None = None,
        gate_mode: str = "full",
    ):
        self.model = model
        self.engine = feature_engine or FeatureEngine()
        self.exit_probability = exit_probability
        self.use_model_exit = use_model_exit
        self.take_profit_atr_multiple = take_profit_atr_multiple
        self.min_candles = min_candles or self.engine.get_required_lookback()
        self.gate_mode = gate_mode  # "full" | "prob_only" | "return_only"
        self._features: pd.DataFrame | None = None
        self._prob: pd.Series | None = None
        self._exp: pd.Series | None = None
        self._atr: pd.Series | None = None
        self._swing_low: pd.Series | None = None
        self._prepared = False

    def prepare(self, df: pd.DataFrame) -> None:
        self._features = self.engine.compute_matrix(df)
        valid = self._features.notna().all(axis=1)
        self._prob = pd.Series(np.nan, index=df.index, dtype=float)
        self._exp = pd.Series(np.nan, index=df.index, dtype=float)
        if valid.any():
            probs, rets = self.model.predict_batch(self._features[valid])
            self._prob.loc[valid] = probs
            self._exp.loc[valid] = rets
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        self._atr = _atr(high, low, close, 14)
        self._swing_low = low.shift(1).rolling(5, min_periods=5).min()
        self._prepared = True

    def _ready(self, i: int, df) -> bool:
        if not self._prepared:
            self.prepare(df)
        return (
            self.min_candles <= i < len(df)
            and np.isfinite(self._prob.iloc[i])
            and np.isfinite(self._exp.iloc[i])
        )

    def entry(self, df, i: int) -> SignalDecision:
        if not self._ready(i, df):
            return SignalDecision(enter=False)
        prob = float(self._prob.iloc[i])
        exp_ret = float(self._exp.iloc[i])
        atr = float(self._atr.iloc[i]) if np.isfinite(self._atr.iloc[i]) else 0.0
        swing = float(self._swing_low.iloc[i]) if np.isfinite(self._swing_low.iloc[i]) else 0.0
        if self.gate_mode == "prob_only":
            enter = prob >= self.model.confidence_threshold
        elif self.gate_mode == "return_only":
            enter = exp_ret >= self.model.min_expected_return_pct
        else:
            enter = prob >= self.model.confidence_threshold and exp_ret >= self.model.min_expected_return_pct
        if enter:
            return SignalDecision(
                enter=True,
                probability=prob,
                expected_return_pct=exp_ret,
                stop_ref=swing if swing > 0 else None,
                atr=atr,
                take_profit_atr_multiple=self.take_profit_atr_multiple,
                reason=f"model p={prob:.3f} exp={exp_ret:.2f}%",
            )
        return SignalDecision(enter=False)

    def exit(self, df, i: int, position) -> bool:
        if not self.use_model_exit:
            return False
        if not self._prepared:
            self.prepare(df)
        if i >= len(df) or not np.isfinite(self._prob.iloc[i]):
            return False
        return bool(self._prob.iloc[i] < self.exit_probability)
