#!/usr/bin/env python3
"""trade_v2 entry point.

Modes:
  train      Train the decision model on historical data
  compare    Run baseline vs challenger vs ablations
  backtest   Run a single candidate backtest
  paper      Run the paper/testnet trading loop
  live       Run the live loop (guarded; requires explicit confirmation)
  dashboard  Start the surveillance dashboard
  download   Download historical OHLCV into the cache

Examples:
  python main.py train --synthetic --symbol BTC/USDT
  python main.py compare --synthetic --symbol BTC/USDT
  python main.py paper --interval 60
"""
from __future__ import annotations

import argparse
import logging
import sys

from config.loader import ConfigError, load_config, validate_model_artifact


def _print_banner() -> None:
    print(
        r"""
+------------------------------------------------------+
|  trade_v2 -- model-based trading, hard risk controls  |
|  Paper/testnet by default. Live trading is guarded.   |
+------------------------------------------------------+
"""
    )


def _build_store(config):
    from state import build_store

    return build_store(config.database_url, f"{config.data_dir}/state.sqlite3")


def _load_dataframe(config, symbol: str, args):
    import pandas as pd

    from data.ohlcv_cache import OHLCVCache
    from data.synthetic import generate_ohlcv

    if getattr(args, "data", ""):
        df = pd.read_parquet(args.data)
        print(f"Loaded {len(df)} bars from {args.data}")
        return df
    if getattr(args, "synthetic", False):
        df = generate_ohlcv(n=getattr(args, "synthetic_bars", 6000), seed=7)
        print(f"Generated {len(df)} synthetic bars (NOT market data)")
        return df
    cache = OHLCVCache(f"{config.data_dir}/ohlcv")
    cached = cache.load(symbol, config.strategy.timeframe)
    if cached is not None:
        print(f"Loaded {len(cached)} cached bars for {symbol}")
        return cached
    df = generate_ohlcv(n=getattr(args, "synthetic_bars", 6000), seed=7)
    print(
        f"No cached data for {symbol}; using synthetic data. "
        "Run `python main.py download --symbol ...` for real data."
    )
    return df


def cmd_train(config, args) -> int:
    from models.features import FeatureEngine
    from models.registry import ModelRegistry
    from models.trainer import ModelTrainer

    df = _load_dataframe(config, args.symbol, args)
    engine = FeatureEngine(config.model.feature_version)
    trainer = ModelTrainer(engine, config.model)
    model, metrics = trainer.train(df, cost_pct=config.execution.fee_rate * 2)
    version = f"v{int(__import__('time').time())}"
    registry = ModelRegistry("models/artifacts")
    path = registry.save(model, version, metrics)
    print(f"Saved model: {path}")
    print(f"Metrics: {metrics}")
    return 0


def cmd_compare(config, args) -> int:
    from backtest.compare import comparison_table, run_full_comparison
    from backtest.reporter import write_json_report, write_text_report
    from models.features import FeatureEngine
    from models.trainer import ModelTrainer

    df = _load_dataframe(config, args.symbol, args)
    split = int(len(df) * args.train_ratio)
    train_df, test_df = df.iloc[:split], df.iloc[split:]
    trainer = ModelTrainer(FeatureEngine(config.model.feature_version), config.model)
    model, metrics = trainer.train(train_df, cost_pct=config.execution.fee_rate * 2)
    print(f"Model trained on {len(train_df)} bars; testing on {len(test_df)} untouched bars")
    print(f"Train metrics: {metrics}")
    results = run_full_comparison(test_df, args.symbol, config, model)
    table = comparison_table(results)
    print()
    print(table)
    if args.output:
        write_json_report(results, args.output + ".json")
        write_text_report(table, results, args.output + ".txt")
        print(f"\nReports written to {args.output}.json/.txt")
    if results["challenger"]["metrics"].get("total_trades", 0) == 0:
        print("\nNOTE: challenger made zero trades -> INCONCLUSIVE, not evidence of safety or accuracy.")
    return 0


def cmd_paper(config, args) -> int:
    from monitoring.alerts import AlertManager
    from monitoring.logger import setup_logging
    from live.trader import LiveTrader
    from models.model import get_model
    from risk.manager import RiskManager

    setup_logging(config.log_file, config.log_level)
    errors = validate_model_artifact(config, base_dir=".")
    if errors:
        print("Model artifact missing. Run `python main.py train` first.")
        for e in errors:
            print(" -", e)
        return 2
    store = _build_store(config)
    risk = RiskManager(config.risk, store)
    model = get_model(config.model)
    model.load(config.model.model_path)
    exchange = _build_exchange(config)
    trader = LiveTrader(config, model, exchange, risk, AlertManager(config))
    trader.run(interval_seconds=args.interval)
    return 0


def cmd_live(config, args) -> int:
    if not args.confirm_live:
        print("Refusing live start: pass --confirm-live only after the LIVE_READINESS checklist is complete.")
        return 2
    if config.exchange.paper_trading:
        print("PAPER_TRADING is true; use --mode paper. Refusing to start live.")
        return 2
    if not config.exchange.allow_live_trading:
        print("ALLOW_LIVE_TRADING is false; refusing live start.")
        return 2
    print("!!! LIVE TRADING ENABLED — real money at risk !!!")
    return cmd_paper(config, args)


def cmd_dashboard(config, args) -> int:
    from monitoring.dashboard import WebDashboard
    from risk.manager import RiskManager

    if len(config.dashboard.dashboard_token) < 32:
        print("DASHBOARD_TOKEN must be at least 32 characters.")
        return 2
    store = _build_store(config)
    risk = RiskManager(config.risk, store)
    WebDashboard(config, risk).run(port=args.port)
    return 0


def cmd_download(config, args) -> int:
    from datetime import datetime

    import ccxt

    from data.downloader import OHLCVDownloader
    from data.ohlcv_cache import OHLCVCache

    exchange = getattr(ccxt, config.exchange.name)({"enableRateLimit": True})
    downloader = OHLCVDownloader(exchange)
    cache = OHLCVCache(f"{config.data_dir}/ohlcv")
    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)
    path = downloader.download_to_cache(args.symbol, config.strategy.timeframe, start, end, cache)
    print(f"Saved {args.symbol} to {path}")
    return 0


def _build_exchange(config):
    if config.exchange.paper_trading and config.exchange.paper_environment == "simulated":
        from execution.simulation import SimulatedExchange

        return SimulatedExchange(initial_balance=config.initial_balance, fee_rate=config.execution.fee_rate)
    from execution.connector import ExchangeConnector

    return ExchangeConnector(config.exchange)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="trade_v2 trading system")
    parser.add_argument("--mode", default="dashboard", choices=["train", "compare", "backtest", "paper", "live", "dashboard", "download"])
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--data", default="", help="Path to a parquet OHLCV file")
    parser.add_argument("--synthetic", action="store_true", help="Use synthetic data (offline demo)")
    parser.add_argument("--synthetic-bars", type=int, default=6000)
    parser.add_argument("--train-ratio", type=float, default=0.6)
    parser.add_argument("--output", default="", help="Report output prefix")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-01-01")
    parser.add_argument("--confirm-live", action="store_true")
    return parser


def main(argv=None) -> int:
    _print_banner()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(require_dashboard_token=(args.mode == "dashboard"))
    except ConfigError as exc:
        print("Configuration error:")
        for part in str(exc).split("; "):
            print(" -", part)
        return 2

    logging.getLogger("trade_v2").setLevel(getattr(logging, config.log_level.upper(), logging.INFO))
    dispatch = {
        "train": cmd_train,
        "compare": cmd_compare,
        "backtest": cmd_compare,
        "paper": cmd_paper,
        "live": cmd_live,
        "dashboard": cmd_dashboard,
        "download": cmd_download,
    }
    return dispatch[args.mode](config, args)


if __name__ == "__main__":
    raise SystemExit(main())
