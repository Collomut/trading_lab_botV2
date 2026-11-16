"""In-memory simulated exchange for offline/paper testing without network."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone


class SimulatedExchange:
    """A virtual spot wallet with deterministic fills at the current price.

    Prices are supplied by ``price_provider(symbol)`` (e.g., the latest cached
    candle close). This is for engineering tests and the simulated paper mode; it
    is not a market simulator.
    """

    def __init__(self, initial_balance: float = 10000.0, fee_rate: float = 0.001, price_provider=None):
        self._cash = float(initial_balance)
        self._positions: dict[str, float] = {}
        self._orders: dict[str, dict] = {}
        self._stops: dict[str, dict] = {}
        self.fee_rate = float(fee_rate)
        self.price_provider = price_provider or (lambda symbol: None)
        self._lock = threading.RLock()

    def set_price_provider(self, provider) -> None:
        self.price_provider = provider

    def get_current_price(self, symbol: str) -> float | None:
        try:
            price = self.price_provider(symbol)
        except Exception:
            return None
        if price is None:
            return None
        try:
            value = float(price)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def get_balance(self) -> dict:
        with self._lock:
            holdings = {"USDT": {"total": self._cash, "free": self._cash, "used": 0.0}}
            for symbol, amount in self._positions.items():
                if amount > 0:
                    base = symbol.split("/")[0]
                    holdings[base] = {"total": amount, "free": amount, "used": 0.0}
            return holdings

    def get_usdt_free(self) -> float:
        return self._cash

    def fetch_account_snapshot(self) -> tuple[dict, list]:
        with self._lock:
            totals = {"USDT": self._cash}
            for symbol, amount in self._positions.items():
                totals[symbol.split("/")[0]] = amount
            balance = {"total": totals, "free": dict(totals), "used": {}}
            return balance, list(self._stops.values())

    def get_order_book(self, symbol: str, limit: int = 20) -> dict:
        price = self.get_current_price(symbol)
        if price is None:
            return {"bids": [], "asks": []}
        return {"bids": [[price * 0.9995, 1e6]], "asks": [[price * 1.0005, 1e6]]}

    def get_market_limits(self, symbol: str) -> dict:
        return {"min_amount": 0.0, "max_amount": None, "min_cost": 1.0, "max_cost": None, "active": True}

    def get_public_market_data_price(self, symbol: str) -> float | None:
        return self.get_current_price(symbol)

    def get_ticker(self, symbol: str) -> dict | None:
        price = self.get_current_price(symbol)
        if price is None:
            return None
        return {"last": price, "bid": price * 0.9995, "ask": price * 1.0005, "timestamp": int(time.time() * 1000)}

    def fetch_closed_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> list:
        return []

    def place_market_buy(self, symbol: str, amount, client_order_id=None) -> dict | None:
        with self._lock:
            price = self.get_current_price(symbol)
            if price is None:
                return None
            amt = float(amount)
            cost = amt * price
            fee = cost * self.fee_rate
            if cost + fee > self._cash:
                return None
            self._cash -= cost + fee
            base = symbol.split("/")[0]
            net = amt - amt * self.fee_rate
            self._positions[symbol] = self._positions.get(symbol, 0.0) + net
            return self._record(symbol, "buy", amt, price, client_order_id, fee_currency=base, fee_cost=amt * self.fee_rate, status="closed")

    def place_market_sell(self, symbol: str, amount, client_order_id=None) -> dict | None:
        with self._lock:
            price = self.get_current_price(symbol)
            if price is None:
                return None
            amt = float(amount)
            held = self._positions.get(symbol, 0.0)
            if amt > held + 1e-12:
                return None
            cost = amt * price
            fee = cost * self.fee_rate
            self._cash += cost - fee
            self._positions[symbol] = max(0.0, held - amt)
            return self._record(symbol, "sell", amt, price, client_order_id, fee_currency="USDT", fee_cost=fee, status="closed")

    def place_native_stop_loss(self, symbol: str, amount, stop_price, client_order_id: str) -> dict:
        with self._lock:
            order_id = f"sim_stop_{int(time.time()*1000)}"
            order = {
                "id": order_id,
                "clientOrderId": client_order_id,
                "symbol": symbol,
                "side": "sell",
                "type": "stop_loss",
                "status": "open",
                "price": float(stop_price),
                "stopPrice": float(stop_price),
                "amount": float(amount),
                "filled": 0.0,
                "timestamp": int(time.time() * 1000),
            }
            self._stops[symbol] = order
            self._orders[order_id] = order
            self._orders[client_order_id] = order
            return order

    def fetch_order(self, order_id: str, symbol: str) -> dict:
        return self._orders.get(str(order_id), {"id": order_id, "status": "closed", "filled": 0.0})

    def fetch_order_by_client_id(self, client_order_id: str, symbol: str) -> dict:
        return self._orders.get(str(client_order_id), {"id": client_order_id, "status": "closed", "filled": 0.0})

    def fetch_order_trades(self, order_id: str, symbol: str) -> list:
        order = self._orders.get(str(order_id))
        if not order:
            return []
        return [{"amount": order.get("amount"), "fee": order.get("fee")}]

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        with self._lock:
            for s, order in list(self._stops.items()):
                if str(order.get("id")) == str(order_id) or str(order.get("clientOrderId")) == str(order_id):
                    del self._stops[s]
            if str(order_id) in self._orders:
                self._orders[str(order_id)]["status"] = "canceled"
            return True

    def get_open_orders(self, symbol: str | None = None) -> list:
        if symbol:
            return [o for o in self._stops.values() if o.get("symbol") == symbol]
        return list(self._stops.values())

    def amount_to_precision(self, symbol: str, amount) -> str:
        return f"{float(amount):.8f}"

    def price_to_precision(self, symbol: str, price) -> str:
        return f"{float(price):.8f}"

    def _record(self, symbol, side, amount, price, client_order_id, *, fee_currency, fee_cost, status) -> dict:
        order_id = f"sim_{side}_{int(time.time()*1000)}"
        order = {
            "id": order_id,
            "clientOrderId": client_order_id or f"client_{order_id}",
            "symbol": symbol,
            "side": side,
            "type": "market",
            "status": status,
            "price": price,
            "average": price,
            "amount": amount,
            "filled": amount,
            "remaining": 0.0,
            "cost": amount * price,
            "fee": {"currency": fee_currency, "cost": fee_cost},
            "fees": [{"currency": fee_currency, "cost": fee_cost}],
            "timestamp": int(time.time() * 1000),
        }
        self._orders[order_id] = order
        if client_order_id:
            self._orders[client_order_id] = order
        return order
