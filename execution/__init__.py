"""Execution package."""
from execution.connector import (
    AccountAccessError,
    ExchangeConnector,
    filter_closed_ohlcv,
    validate_candle_sequence,
)
from execution.fills import FillNormalizer
from execution.order_manager import OrderManager
from execution.reconciliation import Reconciler
from execution.simulation import SimulatedExchange

__all__ = [
    "AccountAccessError",
    "ExchangeConnector",
    "FillNormalizer",
    "OHLCV",
    "OrderManager",
    "Reconciler",
    "SimulatedExchange",
    "filter_closed_ohlcv",
    "validate_candle_sequence",
]

# Backwards-friendly alias documented in the architecture note.
OHLCV = list
