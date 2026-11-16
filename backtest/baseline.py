"""Deterministic baseline strategy: the v1 EMA72/Donchian rule.

This reproduces the production ``macro_donchian_ema72`` candidate as closely as
possible so the AI challenger can be compared against it on identical data and
costs:

  * Entry: completed 1h close breaks the prior 168-bar high AND is above EMA480,
    with ATR14 <= 2.5% of price (entry-only volatility band).
  * Exit: completed 1h close below EMA72.
  * Stop: prior-5-bar swing low, floored at 4% below entry.
  * Target: distant 100xATR backstop (effectively a trend target).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.types import SignalDecision


def _ema(close: pd.Series, window: int) -> pd.Series:
    return close.ewm(span=window, adjust=False, min_periods=window).mean()


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()


class BaselineEma72Strategy:
    name = "baseline_macro_donchian_ema72"

    def __init__(
        self,
        entry_lookback: int = 168,
        macro_ema: int = 480,
        exit_ema: int = 72,
        max_atr_pct: float = 2.5,
        min_candles: int = 600,
    ):
        self.entry_lookback = entry_lookback
        self.macro_ema = macro_ema
        self.exit_ema = exit_ema
        self.max_atr_pct = max_atr_pct
        self.min_candles = min_candles
        self._prepared = False

    def prepare(self, df: pd.DataFrame) -> None:
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        self._close = close
        self._ema_macro = _ema(close, self.macro_ema)
        self._ema_exit = _ema(close, self.exit_ema)
        self._atr = _atr(high, low, close, 14)
        self._prior_high = high.shift(1).rolling(self.entry_lookback, min_periods=self.entry_lookback).max()
        self._swing_low = low.shift(1).rolling(5, min_periods=5).min()
        self._prepared = True

    def entry(self, df, i: int) -> SignalDecision:
        if not self._prepared:
            self.prepare(df)
        if i < self.min_candles or i >= len(df):
            return SignalDecision(enter=False)
        close = float(self._close.iloc[i])
        ema_macro = self._ema_macro.iloc[i]
        prior_high = self._prior_high.iloc[i]
        swing_low = self._swing_low.iloc[i]
        atr = self._atr.iloc[i]
        if not np.isfinite([ema_macro, prior_high, swing_low, atr]).all() or close <= 0:
            return SignalDecision(enter=False)
        atr_pct = float(atr) / close * 100.0
        breakout = close > float(prior_high) and close > float(ema_macro)
        if breakout and atr_pct <= self.max_atr_pct:
            return SignalDecision(
                enter=True,
                probability=1.0,
                expected_return_pct=1e9,  # deterministic rule; expected-return gate passes
                stop_ref=float(swing_low),
                atr=float(atr),
                take_profit_atr_multiple=100.0,
                reason="168-bar breakout above EMA480 with ATR band",
            )
        return SignalDecision(enter=False)

    def exit(self, df, i: int, position) -> bool:
        if not self._prepared:
            self.prepare(df)
        if i >= len(df):
            return False
        exit_ema = self._ema_exit.iloc[i]
        close = float(self._close.iloc[i])
        return bool(np.isfinite(exit_ema) and close < float(exit_ema))
