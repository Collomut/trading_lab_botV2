"""End-to-end: simulated paper trading must produce consistent accounting."""

import math

import numpy as np

import pandas as pd

from execution.simulation import SimulatedExchange
from live.trader import LiveTrader
from risk.manager import RiskManager
from state.sqlite_store import SQLiteStore
from config.schemas import BotConfig, ExchangeConfig, ModelConfig, RiskConfig, StrategyConfig
from data.synthetic import generate_ohlcv


def _config(tmp_path):
    cfg = BotConfig(
        exchange=ExchangeConfig(paper_trading=True, paper_environment="simulated"),
        risk=RiskConfig(max_risk_per_trade=1.0, max_notional_pct=10.0),
        model=ModelConfig(model_type="sklearn", confidence_threshold=0.60),
        strategy=StrategyConfig(trading_pairs=["BTC/USDT"], timeframe="1h", lookback_candles=1000),
    )
    cfg.data_dir = str(tmp_path / "data")
    return cfg


class AbstainModel:
    confidence_threshold = 0.60
    min_expected_return_pct = 1.5

    def predict(self, features):
        return 0.3, -1.0

    def predict_batch(self, X):
        return np.full(len(X), 0.3), np.full(len(X), -1.0)

    def should_enter_long(self, features):
        return False


class AlwaysBuyModel:
    confidence_threshold = 0.60
    min_expected_return_pct = 1.5

    def predict(self, features):
        return 0.9, 5.0

    def predict_batch(self, X):
        return np.full(len(X), 0.9), np.full(len(X), 5.0)

    def should_enter_long(self, features):
        return True


def _wire_sim(sim, df):
    latest = float(df["close"].iloc[-1])
    sim.set_price_provider(lambda symbol: latest)
    candles = [
        [int(ts.timestamp() * 1000), float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume)]
        for ts, r in df.iterrows()
    ]
    sim.fetch_closed_ohlcv = lambda symbol, timeframe, limit=100: candles[-limit:]
    sim.get_market_limits = lambda symbol: {
        "min_amount": 0.0,
        "max_amount": None,
        "min_cost": 0.0,
        "max_cost": None,
        "active": True,
    }
    sim.fetch_account_snapshot = lambda: (
        {"total": {"USDT": sim._cash}, "free": {"USDT": sim._cash}, "used": {}},
        [],
    )


def test_paper_cycle_runs_without_network(tmp_path):
    df = generate_ohlcv(n=3000, seed=2)
    store = SQLiteStore(tmp_path / "s.sqlite3")
    cfg = _config(tmp_path)
    risk = RiskManager(cfg.risk, store)
    sim = SimulatedExchange(initial_balance=10000.0, fee_rate=cfg.execution.fee_rate)
    _wire_sim(sim, df)

    trader = LiveTrader(cfg, AbstainModel(), sim, risk)
    ok = trader.run_cycle()
    assert ok is True
    assert len(risk.open_positions) == 0


def test_paper_cycle_enters_and_exits_with_confident_model(tmp_path):
    df = generate_ohlcv(n=3000, seed=2)
    store = SQLiteStore(tmp_path / "s.sqlite3")
    cfg = _config(tmp_path)
    risk = RiskManager(cfg.risk, store)
    sim = SimulatedExchange(initial_balance=10000.0, fee_rate=cfg.execution.fee_rate)
    _wire_sim(sim, df)

    trader = LiveTrader(cfg, AlwaysBuyModel(), sim, risk)
    ok = trader.run_cycle()
    assert ok is True
    assert len(risk.open_positions) == 1
    # A native stop must have been recorded.
    pos = risk.open_positions["BTC/USDT"]
    assert pos.stop_order_id
    assert pos.stop_client_order_id