"""Cached public market data for the surveillance dashboard.

The trading bot already relies on Binance public market data; this module reuses
the same public endpoint (no API key) to power the dashboard's chart and market
table. All network work runs off the event loop and results are cached briefly
so page polling never hammers the exchange.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("trade_v2.dashboard.market")

PUBLIC_BINANCE_API = "https://data-api.binance.vision/api/v3"


class MarketData:
    """Small, TTL-cached wrapper around a public CCXT exchange."""

    def __init__(self, exchange_name: str = "binance", ttl_seconds: float = 30.0):
        self.exchange_name = exchange_name
        self.ttl_seconds = ttl_seconds
        self._exchange: Any = None
        self._cache: dict[tuple, tuple[float, dict]] = {}
        self._lock = asyncio.Lock()

    def _get_exchange(self):
        if self._exchange is None:
            import ccxt

            exchange = getattr(ccxt, self.exchange_name)(
                {"enableRateLimit": True, "timeout": 12000}
            )
            urls = exchange.urls.get("api", {})
            if isinstance(urls, dict) and "public" in urls:
                urls["public"] = PUBLIC_BINANCE_API
            self._exchange = exchange
        return self._exchange

    async def snapshot(
        self,
        symbols: list[str],
        timeframe: str = "1h",
        limit: int = 120,
        *,
        force: bool = False,
    ) -> dict:
        """Return quotes + OHLCV candles for ``symbols``.

        Never raises: on failure it returns the last cached snapshot (marked
        ``stale``) or an explicit ``unavailable`` payload.
        """
        symbols = [s for s in symbols if s]
        key = (tuple(symbols), timeframe, limit)
        now = time.monotonic()
        cached = self._cache.get(key)

        if cached and not force and now - cached[0] < self.ttl_seconds:
            return {**cached[1], "cache": "hit"}

        # If another request is already fetching, serve stale data rather than
        # queueing up duplicate exchange calls.
        if self._lock.locked() and cached:
            return {**cached[1], "cache": "stale"}

        async with self._lock:
            cached = self._cache.get(key)
            if cached and not force and time.monotonic() - cached[0] < self.ttl_seconds:
                return {**cached[1], "cache": "hit"}
            try:
                payload = await asyncio.to_thread(self._fetch, symbols, timeframe, limit)
                self._cache[key] = (time.monotonic(), payload)
                return {**payload, "cache": "miss"}
            except Exception as exc:  # network/exchange failures must not break the UI
                logger.warning("market data fetch failed: %s", exc)
                if cached:
                    return {**cached[1], "cache": "stale", "error": str(exc)}
                return {
                    "source": "unavailable",
                    "error": "Market data is temporarily unavailable",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "quotes": {},
                    "candles": {},
                    "cache": "none",
                }

    def _fetch(self, symbols: list[str], timeframe: str, limit: int) -> dict:
        exchange = self._get_exchange()
        quotes: dict[str, dict] = {}
        candles: dict[str, list] = {}

        tickers: dict[str, dict] = {}
        try:
            result = exchange.fetch_tickers(symbols)
            if isinstance(result, dict):
                tickers = result
        except Exception:
            tickers = {}

        for symbol in symbols:
            ticker = tickers.get(symbol) or {}
            if not ticker:
                try:
                    ticker = exchange.fetch_ticker(symbol) or {}
                except Exception:
                    ticker = {}
            if ticker:
                last = _as_float(ticker.get("last"))
                previous = _as_float(ticker.get("previousClose")) or _as_float(ticker.get("open"))
                if last is not None and last > 0:
                    quotes[symbol] = {
                        "last": last,
                        "change_pct": _change_pct(last, previous),
                        "high": _as_float(ticker.get("high")),
                        "low": _as_float(ticker.get("low")),
                        "volume": _as_float(ticker.get("quoteVolume"))
                        or _as_float(ticker.get("volume")),
                    }

            try:
                rows = exchange.fetch_ohlcv(symbol, timeframe, limit=limit) or []
            except Exception:
                rows = []
            parsed = []
            for row in rows:
                if len(row) < 6:
                    continue
                try:
                    parsed.append(
                        [int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])]
                    )
                except (TypeError, ValueError, OverflowError):
                    continue
            if parsed:
                candles[symbol] = parsed

        return {
            "source": "live" if (quotes or candles) else "unavailable",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "quotes": quotes,
            "candles": candles,
        }

    def last_price(self, symbol: str) -> float | None:
        """Return the freshest cached price for ``symbol`` without network I/O."""
        for (symbols, _tf, _limit), (_ts, payload) in self._cache.items():
            if symbol in symbols:
                quote = payload.get("quotes", {}).get(symbol)
                if quote and quote.get("last"):
                    return float(quote["last"])
                rows = payload.get("candles", {}).get(symbol) or []
                if rows:
                    return float(rows[-1][4])
        return None


def _as_float(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _change_pct(last: float, previous: float | None) -> float | None:
    if previous is None or previous <= 0:
        return None
    return round((last - previous) / previous * 100.0, 2)
