"""Causal feature engineering for the decision model.

Every feature is computed from data at or before the decision bar. Labels are
created separately (forward returns) so the feature matrix itself never contains
future information.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Indicator primitives (implemented locally for determinism / dependency safety)
# ---------------------------------------------------------------------------
def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    ranges = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    )
    return ranges.max(axis=1)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    tr = _true_range(high, low, close)
    return tr.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()


def _ema(close: pd.Series, window: int) -> pd.Series:
    return close.ewm(span=window, adjust=False, min_periods=window).mean()


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(
        np.where((up > down) & (up > 0), up, 0.0), index=high.index
    )
    minus_dm = pd.Series(
        np.where((down > up) & (down > 0), down, 0.0), index=high.index
    )
    atr = _atr(high, low, close, window)
    plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean() / atr
    minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean() / atr
    denom = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / denom
    return dx.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()


def _parkinson_vol(high: pd.Series, low: pd.Series, window: int = 14) -> pd.Series:
    log_hl = np.log(high / low)
    variance = (log_hl ** 2).rolling(window, min_periods=window).mean() / (4.0 * math.log(2.0))
    return np.sqrt(variance)


# ---------------------------------------------------------------------------
# Feature engine
# ---------------------------------------------------------------------------
class FeatureEngine:
    """Build the decision-model feature matrix and single-row feature vectors."""

    FEATURE_VERSION = 1
    # EMA200 + 24-bar slope dominates the warmup requirement.
    REQUIRED_LOOKBACK = 250
    VOL_PERCENTILE_WINDOW = 720  # 30 days of 1h bars

    def __init__(self, feature_version: int = FEATURE_VERSION):
        self.feature_version = feature_version

    @staticmethod
    def _feature_names() -> list[str]:
        names = [
            "ret_1", "ret_3", "ret_6", "ret_12", "ret_24",
            "log_ret",
            "price_vs_ema20", "price_vs_ema50", "price_vs_ema200",
            "ema20_slope", "ema50_slope", "ema200_slope",
            "atr_14", "atr_pct",
            "parkinson_vol",
            "realized_vol_24",
            "vol_percentile_30d",
            "adx_14", "rsi_14",
            "regime_uptrend", "regime_downtrend", "regime_range",
            "regime_high_vol", "regime_transition",
            "volume_ratio",
            "hour_sin", "hour_cos", "dow_sin", "dow_cos", "is_weekend",
        ]
        return names

    def get_feature_names(self) -> list[str]:
        return self._feature_names()

    def get_required_lookback(self) -> int:
        return self.REQUIRED_LOOKBACK

    # -- core computation ---------------------------------------------------
    def _compute_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        required = {"high", "low", "close", "volume"}
        if not required.issubset(df.columns):
            raise ValueError(f"OHLCV frame missing columns: {required - set(df.columns)}")
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError("OHLCV frame must have a DatetimeIndex")

        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        volume = df["volume"].astype(float)

        ema20 = _ema(close, 20)
        ema50 = _ema(close, 50)
        ema200 = _ema(close, 200)
        atr = _atr(high, low, close, 14)
        adx = _adx(high, low, close, 14)
        rsi = _rsi(close, 14)

        out = pd.DataFrame(index=df.index)
        out["ret_1"] = close.pct_change(1)
        out["ret_3"] = close.pct_change(3)
        out["ret_6"] = close.pct_change(6)
        out["ret_12"] = close.pct_change(12)
        out["ret_24"] = close.pct_change(24)
        out["log_ret"] = np.log(close / close.shift(1))
        out["price_vs_ema20"] = close / ema20 - 1.0
        out["price_vs_ema50"] = close / ema50 - 1.0
        out["price_vs_ema200"] = close / ema200 - 1.0
        out["ema20_slope"] = ema20.pct_change(5)
        out["ema50_slope"] = ema50.pct_change(10)
        out["ema200_slope"] = ema200.pct_change(24)
        out["atr_14"] = atr
        out["atr_pct"] = atr / close * 100.0
        out["parkinson_vol"] = _parkinson_vol(high, low, 14)
        out["realized_vol_24"] = close.pct_change().rolling(24, min_periods=12).std()
        out["vol_percentile_30d"] = out["realized_vol_24"].rolling(
            self.VOL_PERCENTILE_WINDOW, min_periods=168
        ).rank(pct=True)
        out["adx_14"] = adx
        out["rsi_14"] = rsi

        # Regime one-hot (causal: uses only current/past values).
        high_vol = out["atr_pct"] > 3.0
        uptrend = (adx >= 25.0) & (close > ema200) & (ema200 > ema200.shift(24))
        downtrend = (adx >= 25.0) & (close < ema200) & (ema200 < ema200.shift(24))
        range_ = adx <= 18.0
        transition = ~(high_vol | uptrend | downtrend | range_)
        out["regime_uptrend"] = uptrend.astype(int)
        out["regime_downtrend"] = downtrend.astype(int)
        out["regime_range"] = range_.astype(int)
        out["regime_high_vol"] = high_vol.astype(int)
        out["regime_transition"] = transition.astype(int)

        vol_mean = volume.rolling(20, min_periods=20).mean()
        out["volume_ratio"] = volume / vol_mean

        hour = df.index.hour
        dow = df.index.dayofweek
        out["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
        out["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)
        out["dow_sin"] = np.sin(2 * np.pi * dow / 7.0)
        out["dow_cos"] = np.cos(2 * np.pi * dow / 7.0)
        out["is_weekend"] = (dow >= 5).astype(int)

        return out[self._feature_names()]

    def compute_matrix(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return the full causal feature matrix (aligned to ``df.index``)."""
        return self._compute_frame(df)

    def compute(self, df: pd.DataFrame) -> dict[str, float] | None:
        """Return the feature dict for the last closed bar, or ``None`` if not ready."""
        if df is None or len(df) < self.REQUIRED_LOOKBACK:
            return None
        frame = self._compute_frame(df)
        last = frame.iloc[-1]
        if last.isna().any():
            return None
        values = {name: float(last[name]) for name in self._feature_names()}
        if not all(math.isfinite(v) for v in values.values()):
            return None
        return values

    @staticmethod
    def forward_return_labels(df: pd.DataFrame, horizon: int, cost_pct: float = 0.0) -> pd.Series:
        """Net forward return over ``horizon`` bars (causal label target)."""
        close = df["close"].astype(float)
        fwd = close.shift(-horizon) / close - 1.0
        return fwd - cost_pct
