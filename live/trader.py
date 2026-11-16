"""Main live/paper trading loop."""
from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone

from backtest.model_strategy import ModelStrategy
from execution.fills import FillNormalizer
from execution.order_manager import OrderManager
from execution.reconciliation import Reconciler
from models.features import FeatureEngine
from models.model import BaseModel
from risk.manager import RiskManager
from risk.types import Position

logger = logging.getLogger("trade_v2.trader")


def ohlcv_to_dataframe(ohlcv: list):
    import pandas as pd

    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    return df


class LiveTrader:
    """Wires the model, hard risk controls, and execution together.

    Every entry/exit runs the same gates regardless of mode. Paper vs live is a
    property of the exchange adapter, not of this class.
    """

    def __init__(self, config, model: BaseModel, exchange, risk_manager: RiskManager, alerts=None):
        self.config = config
        self.model = model
        self.exchange = exchange
        self.risk = risk_manager
        self.alerts = alerts
        self.feature_engine = FeatureEngine(config.model.feature_version)
        self.model_strategy = ModelStrategy(model, self.feature_engine)
        self.order_manager = OrderManager(risk_manager.store, exchange)
        self.reconciler = Reconciler(risk_manager.store, risk_manager, exchange)
        self._last_analysis: dict[str, dict] = {}

    # -- equity -------------------------------------------------------------
    def _equity_usdt(self, prices: dict[str, float]) -> float:
        balance, _ = self.exchange.fetch_account_snapshot()
        totals = balance.get("total", {}) or {}
        equity = float(totals.get("USDT") or 0.0)
        for symbol, position in self.risk.open_positions.items():
            price = prices.get(symbol)
            if price is None:
                raise ValueError(f"market valuation unavailable for {symbol}")
            equity += position.amount * price
        return equity

    # -- cycle --------------------------------------------------------------
    def run_cycle(self) -> bool:
        try:
            ok, reason = self.reconciler.reconcile()
            if not ok:
                self.risk.halt(f"Exchange reconciliation failed: {reason}")
                logger.error("Reconciliation failed: %s", reason)
                return False

            prices: dict[str, float] = {}
            atrs: dict[str, float] = {}
            frames: dict[str, object] = {}
            for raw_symbol in self.config.strategy.trading_pairs:
                symbol = raw_symbol.strip()
                ohlcv = self.exchange.fetch_closed_ohlcv(
                    symbol, self.config.strategy.timeframe, self.config.strategy.lookback_candles
                )
                if not ohlcv or len(ohlcv) < self.feature_engine.get_required_lookback():
                    logger.info("Insufficient closed candles for %s", symbol)
                    continue
                df = ohlcv_to_dataframe(ohlcv)
                frames[symbol] = df
                price = self.exchange.get_current_price(symbol)
                if price is None:
                    logger.warning("No fresh price for %s", symbol)
                    continue
                prices[symbol] = price

            if not prices:
                logger.warning("No market prices available; cycle skipped")
                return False

            equity = self._equity_usdt(prices)
            if not self.risk.monitor_equity(equity):
                return False

            # Precompute ATR for trailing stops.
            for symbol, df in frames.items():
                atrs[symbol] = self._atr(df)

            price_getter = lambda sym: prices.get(sym)
            atr_getter = lambda sym: atrs.get(sym, 0.0)
            to_close = self.risk.check_positions(price_getter, atr_getter, advance_bar=True)
            for symbol, reason in to_close:
                price = prices.get(symbol)
                if price is not None:
                    self._exit_position(symbol, reason, price)

            for symbol, df in frames.items():
                if symbol in self.risk.open_positions:
                    # Model-based exit on completed candle.
                    self.model_strategy.prepare(df)
                    i = len(df) - 1
                    if self.model_strategy.exit(df, i, self.risk.open_positions[symbol]):
                        self._exit_position(symbol, "MODEL EXIT", prices[symbol])
                    continue
                self._maybe_enter(symbol, df, prices[symbol], equity)
            return True
        except Exception:
            logger.exception("Trading cycle failed; halting")
            self.risk.halt("Trading cycle failed; operator reconciliation required")
            return False

    @staticmethod
    def _atr(df) -> float:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        prev = close.shift(1)
        tr = (high - low).combine((high - prev).abs(), max).combine((low - prev).abs(), max)
        atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        value = atr.iloc[-1]
        return float(value) if math.isfinite(value) else 0.0

    # -- entry --------------------------------------------------------------
    def _maybe_enter(self, symbol: str, df, price: float, equity: float) -> None:
        self.model_strategy.prepare(df)
        i = len(df) - 1
        decision = self.model_strategy.entry(df, i)
        if not decision.enter:
            return

        can_open, reason = self.risk.can_open_position(symbol, equity, route="model")
        if not can_open:
            logger.info("Entry blocked for %s: %s", symbol, reason)
            return

        try:
            limits = self.exchange.get_market_limits(symbol)
            book = self.exchange.get_order_book(symbol)
            best_bid = float(book["bids"][0][0])
            best_ask = float(book["asks"][0][0])
            spread_bps = (best_ask - best_bid) / ((best_ask + best_bid) / 2) * 10000
            if spread_bps > self.config.risk.max_spread_bps:
                logger.info("Entry blocked for %s: spread %.1f bps", symbol, spread_bps)
                return
        except Exception as exc:
            logger.warning("Entry preflight failed for %s (%s)", symbol, type(exc).__name__)
            return

        atr = decision.atr
        if decision.stop_ref and decision.stop_ref > 0:
            stop = max(float(decision.stop_ref), price * (1 - self.config.risk.stop_loss_max_pct / 100.0))
        else:
            stop = self.risk.calculate_stop_loss(price, atr)
        if not (0 < stop < price):
            logger.warning("Invalid stop for %s; entry skipped", symbol)
            return

        try:
            amount = self.risk.calculate_position_size(
                equity,
                price,
                stop,
                probability=decision.probability,
                confidence_threshold=self.config.model.confidence_threshold,
                entry_fee_rate=self.config.execution.fee_rate,
                min_amount=limits.get("min_amount"),
                min_notional=limits.get("min_cost"),
            )
        except Exception as exc:
            logger.warning("Sizing failed for %s (%s)", symbol, type(exc).__name__)
            return
        if amount <= 0:
            return
        amount = float(self.exchange.amount_to_precision(symbol, amount))

        try:
            order, client_id = self.order_manager.submit_market(
                symbol, "buy", amount, decision_key=str(int(time.time() * 1000))
            )
        except Exception as exc:
            self.risk.halt(f"Buy order state requires reconciliation for {symbol}")
            logger.error("Buy order ambiguous for %s: %s", symbol, exc)
            return
        if not order:
            self.order_manager.mark_applied(client_id)
            return
        if not FillNormalizer.is_confirmed_full_fill(order, amount):
            self.risk.halt(f"Unconfirmed or partial buy fill for {symbol}; reconcile before continuing")
            return

        fill_price = float(order.get("average") or order.get("price") or 0)
        net_amount = FillNormalizer.net_base_filled(order, symbol)
        fill_amount = float(net_amount) if net_amount is not None else float(order.get("filled") or amount)
        entry_fee = FillNormalizer.resolve_fee_quote_cost(order, symbol, fill_price, self.exchange)
        if fill_price <= 0 or fill_amount <= 0:
            self.risk.halt(f"Invalid buy fill details for {symbol}; reconcile")
            return

        actual_stop = max(float(decision.stop_ref or stop), fill_price * (1 - self.config.risk.stop_loss_max_pct / 100.0))
        if not (0 < actual_stop < fill_price):
            actual_stop = fill_price * (1 - self.config.risk.stop_loss_max_pct / 100.0)
        take_profit = None
        if decision.take_profit_atr_multiple and atr > 0:
            take_profit = fill_price + decision.take_profit_atr_multiple * atr

        try:
            position = self.risk.open_position(
                symbol,
                fill_price,
                fill_amount,
                stop_price=actual_stop,
                take_profit_price=take_profit,
                exit_policy="model_exit",
                route="model",
                regime=str(self._regime_from_decision(df, i)),
                entry_fee_quote=entry_fee or 0.0,
                order_id=str(order.get("id", "")),
                atr=atr,
            )
        except Exception as exc:
            logger.error("Failed to persist position for %s (%s)", symbol, type(exc).__name__)
            self.risk.halt(f"Position persistence failed for {symbol}; reconcile")
            return

        self._place_stop(symbol, position)
        self.order_manager.mark_applied(client_id)
        self._notify(f"BUY {symbol} @ {fill_price:.6f} amount={fill_amount:.6f} stop={actual_stop:.6f}")

    def _place_stop(self, symbol: str, position: Position) -> None:
        client_id = self.order_manager.client_order_id(symbol, "stop", position.entry_time)
        try:
            order = self.exchange.place_native_stop_loss(symbol, position.amount, position.stop_loss_price, client_id)
            if not isinstance(order, dict) or not order.get("id") or str(order.get("status", "")).lower() != "open":
                raise RuntimeError("stop not confirmed open")
            position.stop_order_id = str(order["id"])
            position.stop_client_order_id = client_id
            self.risk._save_positions()
            self.risk.store.append_event("protective_stop_placed", {"symbol": symbol, "order_id": str(order["id"])})
        except Exception as exc:
            self.risk.halt(f"Native stop placement failed for {symbol}; reconcile immediately")
            logger.critical("Stop placement failed for %s (%s)", symbol, type(exc).__name__)

    # -- exit ---------------------------------------------------------------
    def _exit_position(self, symbol: str, reason: str, price: float) -> None:
        position = self.risk.open_positions.get(symbol)
        if position is None:
            return
        if position.stop_order_id:
            if not self.exchange.cancel_order(position.stop_order_id, symbol):
                self.risk.halt(f"Could not cancel exchange stop for {symbol}; reconcile")
                return
        try:
            order, client_id = self.order_manager.submit_market(
                symbol, "sell", position.amount, decision_key=str(int(time.time() * 1000))
            )
        except Exception as exc:
            self.risk.halt(f"Sell order state requires reconciliation for {symbol}")
            logger.error("Sell ambiguous for %s: %s", symbol, exc)
            return
        if not order or not FillNormalizer.is_confirmed_full_fill(order, position.amount):
            self.risk.halt(f"Sell for {symbol} not confirmed full fill; reconcile")
            return
        fill_price = float(order.get("average") or order.get("price") or price)
        exit_fee = FillNormalizer.resolve_fee_quote_cost(order, symbol, fill_price, self.exchange)
        record = self.risk.close_position(symbol, fill_price, reason, fee_cost=exit_fee)
        self.order_manager.mark_applied(client_id)
        if record:
            self._notify(f"SELL {symbol} @ {fill_price:.6f} pnl={record.pnl} reason={reason}")

    # -- helpers ------------------------------------------------------------
    def _regime_from_decision(self, df, i: int) -> str:
        return ""

    def _notify(self, message: str) -> None:
        if self.alerts is not None:
            try:
                self.alerts.send(message)
            except Exception:
                pass

    def run(self, interval_seconds: int = 60) -> None:
        logger.info("Trading loop started (interval=%ss)", interval_seconds)
        while True:
            ok = self.run_cycle()
            if not ok:
                logger.warning("Cycle reported failure; check halt state")
            time.sleep(interval_seconds)
