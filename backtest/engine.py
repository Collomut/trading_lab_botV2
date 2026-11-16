"""Event-driven backtest engine with realistic costs and causal decisions.

Decision timing:
  * Signals are computed from closed candles up to bar ``i``.
  * Fills execute at bar ``i+1`` (next-bar open for entries/signal exits, and
    intrabar for stop/target checks). This prevents look-ahead fills.

Costs:
  * Slippage (base + square-root market impact) via :class:`ExecutionSimulator`.
  * Taker fees on both sides.
  * Spread is folded into the base slippage assumption (no L2 history available
    for multi-year backtests); this is disclosed in every report.

Risk controls (applied identically to every candidate):
  * Fixed-fractional, confidence-scaled sizing.
  * Initial swing/ATR stop floored at ``stop_loss_max_pct``.
  * Daily-loss halt, consecutive-loss halt (reset at UTC day boundary), and
    rolling profit-factor kill switch.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from backtest.execution_sim import ExecutionSimulator
from backtest.metrics import BacktestMetrics
from backtest.types import BacktestResult, SignalDecision, Strategy
from config.schemas import RiskConfig
from risk.sizing import PositionSizer
from risk.stops import StopManager


def _atr_series(df: pd.DataFrame, window: int = 14) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()


class BacktestEngine:
    def __init__(
        self,
        strategy: Strategy,
        risk_config: RiskConfig,
        *,
        confidence_threshold: float = 0.60,
        execution: ExecutionSimulator | None = None,
        initial_balance: float = 10000.0,
        fee_rate: float = 0.001,
        max_positions: int = 1,
    ):
        self.strategy = strategy
        self.risk = risk_config
        self.confidence_threshold = confidence_threshold
        self.exec_sim = execution or ExecutionSimulator(fee_rate=fee_rate)
        self.initial_balance = float(initial_balance)
        self.fee_rate = float(fee_rate)
        self.sizer = PositionSizer(risk_config)
        self.stops = StopManager(risk_config)
        self.max_positions = max_positions

    # -- risk gate ----------------------------------------------------------
    def _entries_halted(self, equity: float, day_state: dict, recent_pnls: list[float]) -> bool:
        if day_state["halted"]:
            return True
        if day_state["day_start_equity"] > 0:
            daily_loss_pct = max(0.0, -day_state["daily_pnl"]) / day_state["day_start_equity"] * 100.0
            if daily_loss_pct >= self.risk.max_daily_loss_pct:
                return True
        if day_state["consecutive_losses"] >= self.risk.max_consecutive_losses:
            return True
        if len(recent_pnls) >= self.risk.rolling_pf_window:
            window = recent_pnls[-self.risk.rolling_pf_window :]
            gp = sum(p for p in window if p > 0)
            gl = -sum(p for p in window if p < 0)
            if gl > 0 and (gp / gl) < self.risk.min_rolling_pf:
                return True
            if gl == 0 and gp == 0:
                return True
        return False

    def run(self, df: pd.DataFrame, symbol: str) -> BacktestResult:
        if df is None or len(df) < 50:
            raise ValueError("Backtest needs at least 50 bars")
        df = df.copy()
        for col in ("open", "high", "low", "close", "volume"):
            if col not in df.columns:
                raise ValueError(f"Missing OHLCV column: {col}")

        self.strategy.prepare(df)
        atr = _atr_series(df, 14)
        adv = (df["close"].astype(float) * df["volume"].astype(float)).rolling(24, min_periods=12).mean()

        n = len(df)
        realized_pnl = 0.0
        equity_curve: list[float] = []
        trades: list[dict] = []
        position: dict | None = None
        bars_in_market = 0
        recent_pnls: list[float] = []
        current_date = None
        day_state = {"day_start_equity": self.initial_balance, "daily_pnl": 0.0, "consecutive_losses": 0, "halted": False}

        for i in range(1, n - 1):
            exec_idx = i + 1
            exec_date = df.index[exec_idx].date()

            # ---- daily reset ----
            if exec_date != current_date:
                current_date = exec_date
                equity_now = self._equity(df, exec_idx, realized_pnl, position)
                day_state = {
                    "day_start_equity": equity_now,
                    "daily_pnl": 0.0,
                    "consecutive_losses": 0,
                    "halted": False,
                }

            exec_open = float(df["open"].iloc[exec_idx])
            exec_high = float(df["high"].iloc[exec_idx])
            exec_low = float(df["low"].iloc[exec_idx])
            exec_close = float(df["close"].iloc[exec_idx])
            if not all(math.isfinite(v) and v > 0 for v in (exec_open, exec_high, exec_low, exec_close)):
                equity_curve.append(self._equity(df, i, realized_pnl, position))
                continue

            exited_this_bar = False

            # ---- exits on the open position ----
            if position is not None:
                bars_in_market += 1
                exit_signal = bool(self.strategy.exit(df, i, position))
                reason = None
                fill_ref = None
                if exec_open <= position["stop"]:
                    fill_ref, reason = exec_open, "STOP-LOSS (gap)"
                elif exec_low <= position["stop"]:
                    fill_ref, reason = position["stop"], "STOP-LOSS"
                elif exit_signal:
                    fill_ref = exec_open
                    reason = "MODEL EXIT" if position["exit_policy"] == "model_exit" else "SIGNAL EXIT"
                elif position["take_profit"] is not None and exec_open >= position["take_profit"]:
                    fill_ref, reason = exec_open, "TAKE-PROFIT (gap)"
                elif position["take_profit"] is not None and exec_high >= position["take_profit"]:
                    fill_ref, reason = position["take_profit"], "TAKE-PROFIT"

                if fill_ref is not None:
                    notional = fill_ref * position["amount"]
                    fill = self.exec_sim.sell_fill_price(fill_ref, notional, adv.iloc[exec_idx])
                    exit_fee = self.exec_sim.fee(fill * position["amount"])
                    gross = (fill - position["entry_price"]) * position["amount"]
                    net = gross - position["entry_fee"] - exit_fee
                    realized_pnl += net
                    day_state["daily_pnl"] += net
                    if net < 0:
                        day_state["consecutive_losses"] += 1
                    else:
                        day_state["consecutive_losses"] = 0
                    recent_pnls.append(net)
                    r_dist = position["entry_price"] - position["initial_stop"]
                    r_mult = (fill - position["entry_price"]) / r_dist if r_dist > 0 else None
                    trades.append(
                        {
                            "symbol": symbol,
                            "entry_time": str(position["entry_time"]),
                            "exit_time": str(df.index[exec_idx]),
                            "entry_price": position["entry_price"],
                            "exit_price": fill,
                            "amount": position["amount"],
                            "gross_pnl": round(gross, 6),
                            "pnl": round(net, 6),
                            "fee": round(position["entry_fee"] + exit_fee, 6),
                            "pnl_pct": round(net / (position["entry_price"] * position["amount"]) * 100.0, 4) if position["entry_price"] > 0 else 0.0,
                            "r_multiple": round(r_mult, 4) if r_mult is not None else None,
                            "reason": reason,
                            "bars_held": position["bars_held"],
                        }
                    )
                    position = None
                    exited_this_bar = True

            # ---- manage/update remaining position (trailing, highest) ----
            if position is not None:
                position["bars_held"] += 1
                if exec_high > position["highest_price"]:
                    position["highest_price"] = exec_high
                if position["exit_policy"] == "risk_managed":
                    live_atr = float(atr.iloc[exec_idx]) if np.isfinite(atr.iloc[exec_idx]) else position["atr"]
                    # Break-even
                    r_mult = (exec_close - position["entry_price"]) / (position["entry_price"] - position["initial_stop"]) if (position["entry_price"] - position["initial_stop"]) > 0 else None
                    if r_mult is not None and r_mult >= self.risk.break_even_trigger_r and not position["break_even_activated"]:
                        position["stop"] = max(position["stop"], position["entry_price"])
                        position["break_even_activated"] = True
                    if position["break_even_activated"]:
                        trail = position["highest_price"] - live_atr * self.risk.trailing_stop_atr_multiple
                        position["stop"] = max(position["stop"], trail)
                    # Time stop
                    if position["bars_held"] >= self.risk.time_stop_bars and r_mult is not None and r_mult < 0.5:
                        notional = exec_close * position["amount"]
                        fill = self.exec_sim.sell_fill_price(exec_close, notional, adv.iloc[exec_idx])
                        exit_fee = self.exec_sim.fee(fill * position["amount"])
                        gross = (fill - position["entry_price"]) * position["amount"]
                        net = gross - position["entry_fee"] - exit_fee
                        realized_pnl += net
                        day_state["daily_pnl"] += net
                        day_state["consecutive_losses"] += 1 if net < 0 else 0
                        recent_pnls.append(net)
                        trades.append(
                            {
                                "symbol": symbol,
                                "entry_time": str(position["entry_time"]),
                                "exit_time": str(df.index[exec_idx]),
                                "entry_price": position["entry_price"],
                                "exit_price": fill,
                                "amount": position["amount"],
                                "gross_pnl": round(gross, 6),
                                "pnl": round(net, 6),
                                "fee": round(position["entry_fee"] + exit_fee, 6),
                                "pnl_pct": round(net / (position["entry_price"] * position["amount"]) * 100.0, 4),
                                "r_multiple": round(r_mult, 4),
                                "reason": "TIME-STOP",
                                "bars_held": position["bars_held"],
                            }
                        )
                        position = None
                        exited_this_bar = True

            # ---- entries (flat only, not on an exit bar) ----
            if position is None and not exited_this_bar and not self._entries_halted(
                self._equity(df, exec_idx, realized_pnl, position), day_state, recent_pnls
            ):
                decision: SignalDecision = self.strategy.entry(df, i)
                if decision.enter:
                    entry_ref = exec_open
                    atr_val = decision.atr if math.isfinite(decision.atr) and decision.atr > 0 else float(atr.iloc[i]) if np.isfinite(atr.iloc[i]) else 0.0
                    # Pre-slide stop to size the order, then re-anchor to the fill.
                    if decision.stop_ref is not None and math.isfinite(decision.stop_ref) and decision.stop_ref > 0:
                        pre_stop = max(float(decision.stop_ref), entry_ref * (1 - self.risk.stop_loss_max_pct / 100.0))
                    else:
                        pre_stop = self.stops.initial_stop(entry_ref, atr_val)
                    if not (0 < pre_stop < entry_ref):
                        equity_curve.append(self._equity(df, exec_idx, realized_pnl, position))
                        continue
                    equity = self._equity(df, exec_idx, realized_pnl, position)
                    size = self.sizer.calculate(
                        equity,
                        entry_ref,
                        pre_stop,
                        probability=decision.probability,
                        confidence_threshold=self.confidence_threshold,
                        entry_fee_rate=self.fee_rate,
                    )
                    if size > 0:
                        est_notional = size * entry_ref
                        fill = self.exec_sim.buy_fill_price(entry_ref, est_notional, adv.iloc[exec_idx])
                        # Re-anchor the stop to the realized fill.
                        if decision.stop_ref is not None and math.isfinite(decision.stop_ref) and decision.stop_ref > 0:
                            stop = max(float(decision.stop_ref), fill * (1 - self.risk.stop_loss_max_pct / 100.0))
                        else:
                            stop = self.stops.initial_stop(fill, atr_val)
                        if not (0 < stop < fill):
                            equity_curve.append(self._equity(df, exec_idx, realized_pnl, position))
                            continue
                        entry_fee = self.exec_sim.fee(fill * size)
                        tp = None
                        if decision.take_profit_atr_multiple and atr_val > 0:
                            tp = fill + decision.take_profit_atr_multiple * atr_val
                        position = {
                            "entry_time": df.index[exec_idx],
                            "entry_price": fill,
                            "amount": size,
                            "stop": stop,
                            "initial_stop": stop,
                            "take_profit": tp,
                            "exit_policy": "model_exit",
                            "atr": atr_val,
                            "highest_price": fill,
                            "break_even_activated": False,
                            "entry_fee": entry_fee,
                            "bars_held": 0,
                        }

            equity_curve.append(self._equity(df, exec_idx, realized_pnl, position))

        # Force-close any open position at the last bar close.
        if position is not None:
            last_idx = n - 1
            exit_close = float(df["close"].iloc[last_idx])
            notional = exit_close * position["amount"]
            fill = self.exec_sim.sell_fill_price(exit_close, notional, adv.iloc[last_idx])
            exit_fee = self.exec_sim.fee(fill * position["amount"])
            gross = (fill - position["entry_price"]) * position["amount"]
            net = gross - position["entry_fee"] - exit_fee
            realized_pnl += net
            r_dist = position["entry_price"] - position["initial_stop"]
            r_mult = (fill - position["entry_price"]) / r_dist if r_dist > 0 else None
            trades.append(
                {
                    "symbol": symbol,
                    "entry_time": str(position["entry_time"]),
                    "exit_time": str(df.index[last_idx]),
                    "entry_price": position["entry_price"],
                    "exit_price": fill,
                    "amount": position["amount"],
                    "gross_pnl": round(gross, 6),
                    "pnl": round(net, 6),
                    "fee": round(position["entry_fee"] + exit_fee, 6),
                    "pnl_pct": round(net / (position["entry_price"] * position["amount"]) * 100.0, 4),
                    "r_multiple": round(r_mult, 4) if r_mult is not None else None,
                    "reason": "END OF BACKTEST",
                    "bars_held": position["bars_held"],
                }
            )
            if equity_curve:
                equity_curve[-1] = self.initial_balance + realized_pnl
            else:
                equity_curve.append(self.initial_balance + realized_pnl)
            position = None

        if not equity_curve:
            equity_curve = [self.initial_balance]
        metrics = BacktestMetrics(trades, equity_curve, self.initial_balance).to_dict()
        metrics["bars_in_market"] = bars_in_market
        metrics["time_in_market_pct"] = round(bars_in_market / max(1, n) * 100.0, 2)
        return BacktestResult(
            candidate=self.strategy.name,
            symbol=symbol,
            initial_balance=self.initial_balance,
            final_balance=self.initial_balance + realized_pnl,
            trades=trades,
            equity_curve=equity_curve,
            bars=n,
            bars_in_market=bars_in_market,
            metrics=metrics,
        )

    def _equity(self, df: pd.DataFrame, i: int, realized_pnl: float, position: dict | None) -> float:
        """Total equity = starting balance + realized P&L + unrealized mark-to-market."""
        equity = self.initial_balance + realized_pnl
        if position is not None:
            close = float(df["close"].iloc[i])
            equity += (close - position["entry_price"]) * position["amount"]
        return equity
