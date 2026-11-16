"""CCXT exchange connector with paper/testnet/demo/live safety guards."""
from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timezone

import ccxt

from config.schemas import ExchangeConfig

logger = logging.getLogger("trade_v2.exchange")


def filter_closed_ohlcv(candles: list, timeframe_seconds: float, now_ms: int | None = None) -> list:
    """Keep only complete, structurally valid OHLCV candles."""
    if not isinstance(candles, list) or not math.isfinite(timeframe_seconds) or timeframe_seconds <= 0:
        return []
    cutoff_ms = (int(time.time() * 1000) if now_ms is None else int(now_ms)) - 2000
    duration_ms = timeframe_seconds * 1000
    result: list = []
    for candle in candles:
        if not isinstance(candle, (list, tuple)) or len(candle) < 6:
            continue
        try:
            ts = int(candle[0])
            o, h, l, c, v = (float(x) for x in candle[1:6])
        except (TypeError, ValueError, OverflowError):
            continue
        if not all(math.isfinite(x) for x in (o, h, l, c, v)):
            continue
        if ts <= 0 or min(o, h, l, c) <= 0 or v < 0:
            continue
        if h < max(o, c, l) or l > min(o, c):
            continue
        if ts + duration_ms > cutoff_ms:
            continue
        result.append([ts, o, h, l, c, v])
    result.sort(key=lambda row: row[0])
    dedup: dict[int, list] = {}
    for candle in result:
        dedup[candle[0]] = candle
    return [dedup[ts] for ts in sorted(dedup)]


def validate_candle_sequence(candles: list, timeframe_seconds: float, now_ms: int | None = None) -> list:
    if not candles or not math.isfinite(timeframe_seconds) or timeframe_seconds <= 0:
        return []
    ordered = sorted(candles, key=lambda row: row[0])
    duration_ms = int(timeframe_seconds * 1000)
    for idx in range(1, len(ordered)):
        if int(ordered[idx][0]) - int(ordered[idx - 1][0]) != duration_ms:
            return []
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    latest_close = int(ordered[-1][0]) + duration_ms
    if now - latest_close > duration_ms * 2 or latest_close > now + 2000:
        return []
    return ordered


class AccountAccessError(RuntimeError):
    """Safe, actionable account-access failure without echoing credentials."""


class ExchangeConnector:
    def __init__(self, config: ExchangeConfig):
        self.config = config
        self._lock = threading.RLock()
        if not config.paper_trading and not config.allow_live_trading:
            raise RuntimeError(
                "Live trading is disabled in this build; refusing to initialise a live exchange connection"
            )
        self.exchange = self._create_exchange()
        self.market_data_exchange = self._create_public_market_data_exchange()

    # -- construction -------------------------------------------------------
    def _create_exchange(self):
        exchange_class = getattr(ccxt, self.config.name)
        api_key = self.config.api_key
        api_secret = self.config.api_secret
        if self.config.paper_trading and self.config.paper_environment == "demo":
            api_key = self.config.demo_api_key
            api_secret = self.config.demo_api_secret
        exchange = exchange_class(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "spot", "adjustForTimeDifference": True},
            }
        )
        if self.config.paper_trading:
            if self.config.paper_environment == "demo":
                enable = getattr(exchange, "enable_demo_trading", None)
                if not callable(enable):
                    raise RuntimeError("Installed CCXT does not support Binance Demo mode; upgrade CCXT")
                enable(True)
            elif self.config.paper_environment == "testnet":
                exchange.set_sandbox_mode(True)
            elif self.config.paper_environment == "simulated":
                logger.info("Simulated environment requested; use SimulatedExchange for execution")
            else:
                raise ValueError("PAPER_ENVIRONMENT must be testnet, demo, or simulated")
        else:
            logger.warning("LIVE TRADING connector initialised — real money at risk")
        return exchange

    def _create_public_market_data_exchange(self):
        if not (self.config.paper_trading and self.config.paper_environment in {"testnet", "demo"}):
            return None
        if self.config.name.strip().lower() != "binance":
            return None
        public = getattr(ccxt, self.config.name)({"enableRateLimit": True, "options": {"defaultType": "spot"}})
        urls = public.urls.get("api", {})
        if isinstance(urls, dict) and "public" in urls:
            urls["public"] = "https://data-api.binance.vision/api/v3"
        return public

    # -- account ------------------------------------------------------------
    def get_balance(self) -> dict:
        with self._lock:
            try:
                balance = self.exchange.fetch_balance()
            except ccxt.BaseError as exc:
                raise AccountAccessError(self._safe_error(exc)) from exc
            holdings = {}
            for currency, amount in (balance.get("total") or {}).items():
                if amount and amount > 0:
                    holdings[currency] = {
                        "total": amount,
                        "free": (balance.get("free") or {}).get(currency, 0),
                        "used": (balance.get("used") or {}).get(currency, 0),
                    }
            return holdings

    def fetch_account_snapshot(self) -> tuple[dict, list]:
        with self._lock:
            try:
                balance = self.exchange.fetch_balance()
                orders = self.exchange.fetch_open_orders()
            except ccxt.BaseError as exc:
                raise AccountAccessError(self._safe_error(exc)) from exc
            return balance, orders

    def get_usdt_balance(self) -> float:
        try:
            return float(self.get_balance().get("USDT", {}).get("free", 0.0) or 0.0)
        except AccountAccessError:
            return 0.0

    # -- market data --------------------------------------------------------
    def load_markets(self) -> None:
        with self._lock:
            self.exchange.load_markets()

    def get_market_limits(self, symbol: str) -> dict:
        with self._lock:
            self.exchange.load_markets()
            market = self.exchange.market(symbol)
            limits = market.get("limits", {})
            amount = limits.get("amount", {}) or {}
            cost = limits.get("cost", {}) or {}
            return {
                "min_amount": amount.get("min"),
                "max_amount": amount.get("max"),
                "min_cost": cost.get("min"),
                "max_cost": cost.get("max"),
                "active": market.get("active", True),
            }

    def get_order_book(self, symbol: str, limit: int = 20) -> dict:
        with self._lock:
            try:
                return self.exchange.fetch_order_book(symbol, limit=limit)
            except ccxt.BaseError as exc:
                raise RuntimeError("Order book unavailable") from exc

    def get_ticker(self, symbol: str) -> dict | None:
        with self._lock:
            try:
                return self.exchange.fetch_ticker(symbol)
            except ccxt.BaseError:
                return None

    def get_current_price(self, symbol: str) -> float | None:
        ticker = self.get_ticker(symbol)
        if not ticker:
            return None
        last = ticker.get("last")
        try:
            value = float(last)
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) and value > 0 else None

    def get_public_market_data_price(self, symbol: str) -> float | None:
        if self.market_data_exchange is None:
            return None
        try:
            ticker = self.market_data_exchange.fetch_ticker(symbol)
            return float(ticker["last"]) if ticker.get("last") is not None else None
        except (ccxt.BaseError, TypeError, ValueError):
            return None

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> list:
        with self._lock:
            try:
                data_exchange = self.market_data_exchange or self.exchange
                return data_exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            except ccxt.BaseError:
                return []

    def fetch_closed_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> list:
        candles = self.fetch_ohlcv(symbol, timeframe, limit + 1)
        if not candles:
            return []
        try:
            seconds = float(self.exchange.parse_timeframe(timeframe))
        except (AttributeError, TypeError, ValueError):
            return []
        closed = filter_closed_ohlcv(candles, seconds)
        return validate_candle_sequence(closed, seconds)[-limit:]

    # -- precision ----------------------------------------------------------
    def amount_to_precision(self, symbol: str, amount) -> str:
        with self._lock:
            self.exchange.load_markets()
            return self.exchange.amount_to_precision(symbol, str(amount))

    def price_to_precision(self, symbol: str, price) -> str:
        with self._lock:
            self.exchange.load_markets()
            return self.exchange.price_to_precision(symbol, str(price))

    # -- orders -------------------------------------------------------------
    def place_market_buy(self, symbol: str, amount, client_order_id: str | None = None) -> dict | None:
        with self._lock:
            try:
                params = {"clientOrderId": client_order_id} if client_order_id else {}
                return self.exchange.create_market_buy_order(symbol, amount, params)
            except ccxt.InsufficientFunds:
                return None
            except ccxt.BaseError as exc:
                raise RuntimeError("Exchange did not confirm buy order outcome") from exc

    def place_market_sell(self, symbol: str, amount, client_order_id: str | None = None) -> dict | None:
        with self._lock:
            try:
                params = {"clientOrderId": client_order_id} if client_order_id else {}
                return self.exchange.create_market_sell_order(symbol, amount, params)
            except ccxt.BaseError as exc:
                raise RuntimeError("Exchange did not confirm sell order outcome") from exc

    def place_native_stop_loss(self, symbol: str, amount, stop_price, client_order_id: str) -> dict:
        with self._lock:
            try:
                prec = self.price_to_precision(symbol, stop_price)
                return self.exchange.create_order(
                    symbol, "market", "sell", float(amount), None,
                    {"stopLossPrice": prec, "clientOrderId": client_order_id},
                )
            except ccxt.BaseError as exc:
                raise RuntimeError("Exchange-native stop was not confirmed") from exc

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        with self._lock:
            try:
                self.exchange.cancel_order(order_id, symbol)
                return True
            except ccxt.BaseError:
                return False

    def fetch_order(self, order_id: str, symbol: str) -> dict:
        with self._lock:
            try:
                return self.exchange.fetch_order(order_id, symbol)
            except ccxt.BaseError as exc:
                raise RuntimeError("Exchange order status unavailable") from exc

    def fetch_order_by_client_id(self, client_order_id: str, symbol: str) -> dict:
        with self._lock:
            try:
                return self.exchange.fetch_order(None, symbol, {"origClientOrderId": client_order_id})
            except ccxt.BaseError as exc:
                raise RuntimeError("Client order status unavailable") from exc

    def fetch_order_trades(self, order_id: str, symbol: str) -> list:
        fetch_fills = getattr(self.exchange, "fetch_order_trades", None)
        if not callable(fetch_fills):
            return []
        with self._lock:
            try:
                fills = fetch_fills(str(order_id), symbol)
                return fills if isinstance(fills, list) else []
            except ccxt.BaseError:
                return []

    def get_open_orders(self, symbol: str | None = None) -> list:
        with self._lock:
            try:
                return self.exchange.fetch_open_orders(symbol)
            except ccxt.BaseError as exc:
                raise RuntimeError("Exchange open-order state unavailable") from exc

    def get_server_time(self) -> datetime:
        with self._lock:
            try:
                return datetime.fromtimestamp(self.exchange.fetch_time() / 1000, tz=timezone.utc)
            except ccxt.BaseError:
                return datetime.now(timezone.utc)

    # -- safety -------------------------------------------------------------
    @staticmethod
    def _safe_error(exc: Exception) -> str:
        text = f"{type(exc).__name__}"
        lowered = str(exc).lower()
        if "invalid api-key" in lowered or "-2015" in lowered:
            return "Binance rejected the API key, IP, or permissions (-2015)."
        if "signature" in lowered or "-1022" in lowered:
            return "Binance rejected the request signature (-1022)."
        if isinstance(exc, ccxt.RateLimitExceeded):
            return "Exchange rate limit reached; retry later."
        if isinstance(exc, ccxt.AuthenticationError):
            return "Authentication failed for the configured paper environment."
        return text
