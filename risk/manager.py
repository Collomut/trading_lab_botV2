"""Core risk manager: sizing, stops, circuit breakers, position lifecycle."""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from config.schemas import RiskConfig
from risk.circuit_breakers import CircuitBreakers
from risk.sizing import PositionSizer
from risk.state import RiskState
from risk.stops import StopManager
from risk.types import Position, TradeRecord
from state.store import StateStore

logger = logging.getLogger("trade_v2.risk")

MANAGED_ROUTES = ("uptrend", "downtrend", "model")


class RiskManager:
    """Orchestrates all risk controls and owns the open-position set."""

    def __init__(
        self,
        config: RiskConfig,
        store: StateStore,
        *,
        entry_mode_default: str = "ACTIVE",
    ):
        self.config = config
        self.store = store
        self.sizer = PositionSizer(config)
        self.stops = StopManager(config)
        self.breakers = CircuitBreakers(config)
        self.state = RiskState(store)
        self.open_positions: dict[str, Position] = {}
        self.trade_history: list[TradeRecord] = []
        self._entry_mode_default = entry_mode_default
        self._load_positions()
        self._load_trades()

    # -- persistence --------------------------------------------------------
    def _load_positions(self) -> None:
        try:
            data = self.store.read_positions()
            for symbol, payload in data.items():
                try:
                    position = Position.from_dict(payload)
                except (TypeError, ValueError):
                    self._halt("Persisted position state is unreadable; operator reconciliation required")
                    return
                if position.symbol != symbol or position.entry_price <= 0 or position.amount <= 0:
                    self._halt("Persisted position state is invalid; operator reconciliation required")
                    return
                self.open_positions[symbol] = position
        except Exception:
            self._halt("Could not load positions; operator reconciliation required")

    def _load_trades(self) -> None:
        try:
            for row in self.store.list_trades(20000):
                if not isinstance(row, dict) or row.get("action") not in {"SELL", "CLOSE"}:
                    continue
                try:
                    self.trade_history.append(
                        TradeRecord(
                            symbol=str(row.get("symbol", "")),
                            side="long",
                            entry_price=float(row.get("entry_price", 0.0)),
                            exit_price=float(row.get("price", 0.0)),
                            amount=float(row.get("amount", 0.0)),
                            entry_time=str(row.get("entry_time", "")),
                            exit_time=str(row.get("timestamp", "")),
                            pnl=float(row["pnl"]) if row.get("pnl") is not None else None,
                            pnl_pct=float(row["pnl_pct"]) if row.get("pnl_pct") is not None else None,
                            reason=str(row.get("reason", "")),
                            fee=float(row["fee"]) if row.get("fee") is not None else None,
                            accounting_complete=row.get("accounting_complete") is not False,
                            strategy=str(row.get("strategy", "")),
                            route=str(row.get("route", "legacy")),
                            regime=str(row.get("regime", "")),
                            r_multiple=float(row["r_multiple"]) if row.get("r_multiple") is not None else None,
                            order_id=str(row.get("order_id", "")),
                            simulated=bool(row.get("simulated", False)),
                        )
                    )
                except (TypeError, ValueError, KeyError):
                    continue
        except Exception:
            logger.warning("Could not hydrate trade history")

    def _save_positions(self) -> bool:
        ok = self.store.write_positions(
            {sym: pos.to_dict() for sym, pos in self.open_positions.items()}
        )
        if not ok:
            self._halt("Open-position state could not be saved; operator reconciliation required")
        return ok

    # -- halt / entry mode --------------------------------------------------
    def _halt(self, reason: str) -> None:
        self.state.halted = True
        self.state.halt_reason = str(reason)[:500]
        try:
            self.state.persist()
            self.store.append_event("risk_halt", {"reason": self.state.halt_reason})
        except Exception:
            logger.exception("Could not persist halt state")

    def halt(self, reason: str) -> None:
        self._halt(reason)

    def resume(self) -> bool:
        """Clear a reviewed halt. Callers must first verify a clean, reconciled account."""
        if not self.state.halted:
            return False
        self.state.halted = False
        self.state.halt_reason = ""
        try:
            self.state.persist()
            self.store.append_event("risk_resumed", {})
            return True
        except Exception:
            self.state.halted = True
            return False

    @property
    def is_halted(self) -> bool:
        return self.state.halted

    @property
    def halt_reason(self) -> str:
        return self.state.halt_reason

    def entry_mode(self) -> str:
        persisted = self.store.read_state("entry_mode")
        if persisted in {"ACTIVE", "EXIT_ONLY"}:
            return persisted
        return self._entry_mode_default

    def set_entry_mode(self, mode: str) -> None:
        if mode not in {"ACTIVE", "EXIT_ONLY"}:
            raise ValueError("entry_mode must be ACTIVE or EXIT_ONLY")
        self.store.write_state("entry_mode", {"mode": mode})
        self.store.append_event("mode_changed", {"mode": mode})

    def route_halts(self) -> dict[str, str]:
        return dict(self.state.route_halted)

    def clear_route_halts(self) -> bool:
        if not self.state.route_halted:
            return False
        for route in list(self.state.route_halted):
            self.state.route_losses[route] = 0
        self.state.route_halted = {}
        self.state.persist()
        self.store.append_event("route_loss_halt_cleared", {})
        return True

    # -- equity monitoring --------------------------------------------------
    def monitor_equity(self, equity: float, *, reconciled: bool = False) -> bool:
        """Persist equity anchors and trip the drawdown breaker if needed."""
        if not math.isfinite(equity) or equity <= 0:
            self._halt("Account equity unavailable or invalid; operator review required")
            return False
        self.state.reset_daily_if_needed()
        self.state.observe_equity(equity)
        self.state.persist()
        if self.breakers.rolling_drawdown_tripped(equity, self.state.rolling_peak_equity):
            self._halt(
                f"Rolling peak-to-trough drawdown limit reached: "
                f"peak={self.state.rolling_peak_equity:.2f} equity={equity:.2f}"
            )
            return False
        return True

    # -- entry gating -------------------------------------------------------
    def can_open_position(
        self, symbol: str, portfolio_value: float, *, route: str = "legacy"
    ) -> tuple[bool, str]:
        if self.entry_mode() != "ACTIVE":
            return False, "Entry-only pause is active; existing positions continue to be monitored"
        if self.state.halted:
            return False, f"Trading halted: {self.state.halt_reason}"
        if route in self.state.route_halted:
            return False, self.state.route_halted[route]
        if len(self.open_positions) >= self.config.max_consecutive_losses and len(self.open_positions) >= 10:
            # Defensive: never allow unbounded positions if a caller forgot the cap.
            return False, "Maximum open positions reached"
        if len(self.open_positions) >= self._max_open_positions():
            return False, f"Maximum open positions reached ({self._max_open_positions()})"
        if symbol in self.open_positions:
            return False, f"Already have an open position in {symbol}"
        if self.breakers.daily_loss_tripped(self.state.daily_loss, self.state.daily_starting_equity):
            self._halt(
                f"Daily loss limit reached: {self.state.daily_loss:.2f} "
                f"(starting equity {self.state.daily_starting_equity:.2f})"
            )
            return False, self.state.halt_reason
        return True, "OK"

    def _max_open_positions(self) -> int:
        # A conservative fixed cap; callers may override via subclass if needed.
        return 3

    # -- delegation helpers ------------------------------------------------
    def calculate_position_size(
        self,
        equity: float,
        entry_price: float,
        stop_price: float,
        *,
        probability: float = 1.0,
        confidence_threshold: float = 0.60,
        target_volatility: float | None = None,
        current_volatility: float | None = None,
        entry_fee_rate: float = 0.0,
        amount_step: float | None = None,
        min_amount: float | None = None,
        min_notional: float | None = None,
    ) -> float:
        return self.sizer.calculate(
            equity,
            entry_price,
            stop_price,
            probability=probability,
            confidence_threshold=confidence_threshold,
            target_volatility=target_volatility,
            current_volatility=current_volatility,
            entry_fee_rate=entry_fee_rate,
            amount_step=amount_step,
            min_amount=min_amount,
            min_notional=min_notional,
        )

    def calculate_stop_loss(self, entry_price: float, atr: float = 0.0) -> float:
        return self.stops.initial_stop(entry_price, atr)

    # -- position lifecycle -------------------------------------------------
    def open_position(
        self,
        symbol: str,
        entry_price: float,
        amount: float,
        *,
        stop_price: float,
        take_profit_price: float | None = None,
        exit_policy: str = "risk_managed",
        route: str = "legacy",
        regime: str = "",
        entry_fee_quote: float = 0.0,
        order_id: str = "",
        atr: float = 0.0,
        simulated: bool = False,
    ) -> Position:
        if symbol in self.open_positions:
            raise ValueError(f"Position already open for {symbol}")
        if not (math.isfinite(entry_price) and entry_price > 0):
            raise ValueError("entry_price must be finite and positive")
        if not (math.isfinite(amount) and amount > 0):
            raise ValueError("amount must be finite and positive")
        if not (math.isfinite(stop_price) and 0 < stop_price < entry_price):
            raise ValueError("stop_price must be finite, positive, and below entry")
        if take_profit_price is not None and not (
            math.isfinite(take_profit_price) and take_profit_price > entry_price
        ):
            raise ValueError("take_profit_price must be above entry")
        position = Position(
            symbol=symbol,
            side="long",
            entry_price=float(entry_price),
            amount=float(amount),
            entry_time=datetime.now(timezone.utc).isoformat(),
            stop_loss_price=float(stop_price),
            take_profit_price=float(take_profit_price) if take_profit_price is not None else None,
            order_id=str(order_id or ""),
            entry_fee_quote=max(0.0, float(entry_fee_quote)),
            highest_price=float(entry_price),
            exit_policy=exit_policy,
            route=route,
            regime=regime,
            simulated=simulated,
            atr_at_entry=float(atr or 0.0),
        )
        self.open_positions[symbol] = position
        if not self._save_positions():
            raise RuntimeError("Could not persist new position; order must be reconciled")
        return position

    def close_position(
        self,
        symbol: str,
        exit_price: float,
        reason: str,
        *,
        fee_cost: float | None = 0.0,
        closed_amount: float | None = None,
    ) -> TradeRecord | None:
        position = self.open_positions.get(symbol)
        if position is None:
            return None
        if not (math.isfinite(exit_price) and exit_price > 0):
            return None
        amount = position.amount if closed_amount is None else float(closed_amount)
        if not (math.isfinite(amount) and 0 < amount <= position.amount):
            return None

        allocated_entry_fee = position.entry_fee_quote * (amount / position.amount)
        accounting_complete = position.accounting_complete and fee_cost is not None

        # Remove then persist; restore on failure so state stays consistent.
        del self.open_positions[symbol]
        if not self._save_positions():
            self.open_positions[symbol] = position
            return None

        if accounting_complete:
            gross_pnl = (exit_price - position.entry_price) * amount
            total_fee = allocated_entry_fee + float(fee_cost)
            pnl = gross_pnl - total_fee
            cost_basis = position.entry_price * amount
            pnl_pct = (pnl / cost_basis * 100.0) if cost_basis > 0 else 0.0
        else:
            total_fee = None
            pnl = None
            pnl_pct = None

        risk_distance = position.entry_price - position.stop_loss_price
        r_multiple = (
            (exit_price - position.entry_price) / risk_distance
            if risk_distance > 0 and math.isfinite(risk_distance)
            else None
        )

        record = TradeRecord(
            symbol=symbol,
            side=position.side,
            entry_price=position.entry_price,
            exit_price=float(exit_price),
            amount=amount,
            entry_time=position.entry_time,
            exit_time=datetime.now(timezone.utc).isoformat(),
            pnl=pnl,
            pnl_pct=pnl_pct,
            reason=reason,
            fee=total_fee,
            accounting_complete=accounting_complete,
            strategy=position.exit_policy,
            route=position.route,
            regime=position.regime,
            r_multiple=r_multiple,
            order_id=position.order_id,
            simulated=position.simulated,
        )
        self.trade_history.append(record)

        self.store.append_trade(
            {
                "action": "CLOSE",
                "symbol": symbol,
                "price": float(exit_price),
                "amount": amount,
                "entry_price": position.entry_price,
                "entry_time": position.entry_time,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "fee": total_fee,
                "accounting_complete": accounting_complete,
                "reason": reason,
                "strategy": position.exit_policy,
                "route": position.route,
                "regime": position.regime,
                "r_multiple": r_multiple,
                "order_id": position.order_id,
                "simulated": position.simulated,
            }
        )

        if not accounting_complete:
            self._halt(
                f"Trade closed for {symbol} but fee/partial-fill accounting is incomplete; "
                "operator reconciliation required"
            )
            return record

        self.state.record_trade_pnl(pnl, position.route)
        self.state.persist()

        # Route-scoped consecutive-loss halt.
        if position.route in MANAGED_ROUTES:
            if self.breakers.consecutive_losses_tripped(self.state.route_losses.get(position.route, 0)):
                self.state.route_halted[position.route] = (
                    f"Consecutive loss limit reached "
                    f"({self.state.route_losses[position.route]}); {position.route} route paused"
                )
                self.state.persist()
                self.store.append_event("route_loss_halt", {"route": position.route})
        # Legacy global streak.
        if position.route == "legacy" and self.breakers.consecutive_losses_tripped(
            self.state.consecutive_losses
        ):
            self._halt(
                f"Consecutive loss limit reached ({self.state.consecutive_losses}); entries paused"
            )
        # Daily loss breaker.
        if self.breakers.daily_loss_tripped(
            self.state.daily_loss, self.state.daily_starting_equity
        ):
            self._halt(
                f"Daily loss limit reached: {self.state.daily_loss:.2f} "
                f"(starting equity {self.state.daily_starting_equity:.2f})"
            )
        return record

    def check_positions(
        self,
        price_getter,
        atr_getter=None,
        *,
        advance_bar: bool = False,
    ) -> list[tuple[str, str]]:
        """Update stops/trailing and return ``[(symbol, reason), ...]`` to close."""
        to_close: list[tuple[str, str]] = []
        for symbol, position in list(self.open_positions.items()):
            price = price_getter(symbol)
            if not (isinstance(price, (int, float)) and math.isfinite(price) and price > 0):
                self._halt(f"Unable to obtain a valid market price for {symbol}; operator review required")
                continue
            if advance_bar:
                position.bars_held += 1
            if price > position.highest_price:
                position.highest_price = price
            atr = atr_getter(symbol) if atr_getter else position.atr_at_entry

            # Stop loss first (conservative within a bar).
            if position.should_stop_loss(price):
                to_close.append(
                    (symbol, "TRAILING STOP triggered" if position.break_even_activated else "STOP-LOSS triggered")
                )
                continue

            if position.exit_policy in {"model_exit", "fixed_rr"}:
                if position.should_take_profit(price):
                    to_close.append((symbol, "TAKE-PROFIT triggered"))
                elif self.stops.time_stop_exit(position, price):
                    to_close.append((symbol, "TIME-STOP triggered"))
                else:
                    self._persist_if_changed(position)
                continue

            # risk_managed: break-even then trailing.
            new_stop, activated = self.stops.break_even_stop(position, price)
            if activated and not position.break_even_activated:
                position.break_even_activated = True
            if new_stop > position.stop_loss_price:
                position.stop_loss_price = new_stop
            if position.break_even_activated:
                trailed = self.stops.trailing_stop(position, price, atr)
                if trailed > position.stop_loss_price:
                    position.stop_loss_price = trailed
            self._persist_if_changed(position)
            if position.should_take_profit(price):
                to_close.append((symbol, "TAKE-PROFIT triggered"))
            elif self.stops.time_stop_exit(position, price):
                to_close.append((symbol, "TIME-STOP triggered"))
        return to_close

    def _persist_if_changed(self, position: Position) -> None:
        self._save_positions()

    # -- reporting ----------------------------------------------------------
    def get_performance_summary(self) -> dict:
        completed = [t for t in self.trade_history if t.accounting_complete and t.pnl is not None]
        incomplete = [t for t in self.trade_history if not t.accounting_complete or t.pnl is None]
        if not completed:
            return {
                "total_trades": 0,
                "incomplete_trades": len(incomplete),
                "open_positions": len(self.open_positions),
                "daily_pnl": round(self.state.daily_loss, 2),
                "is_halted": self.state.halted,
                "profit_factor": None,
                "win_rate": 0.0,
            }
        winners = [t for t in completed if t.pnl > 0]
        losers = [t for t in completed if t.pnl <= 0]
        gross_profit = sum(t.pnl for t in winners)
        gross_loss = -sum(t.pnl for t in losers)
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None
        pnls = [t.pnl for t in completed]
        return {
            "total_trades": len(completed),
            "incomplete_trades": len(incomplete),
            "winners": len(winners),
            "losers": len(losers),
            "win_rate": round(len(winners) / len(completed) * 100.0, 2),
            "total_pnl": round(sum(pnls), 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "profit_factor": round(profit_factor, 3) if profit_factor is not None else None,
            "avg_win": round(gross_profit / len(winners), 2) if winners else 0.0,
            "avg_loss": round(-gross_loss / len(losers), 2) if losers else 0.0,
            "open_positions": len(self.open_positions),
            "daily_pnl": round(self.state.daily_loss, 2),
            "is_halted": self.state.halted,
            "halt_reason": self.state.halt_reason,
            "route_halts": self.route_halts(),
        }
