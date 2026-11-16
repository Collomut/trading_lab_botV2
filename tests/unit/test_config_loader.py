import os

import pytest

from config.loader import ConfigError, load_config


def test_load_config_simulated(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_TRADING", "true")
    monkeypatch.setenv("PAPER_ENVIRONMENT", "simulated")
    monkeypatch.setenv("DASHBOARD_TOKEN", "x" * 40)
    cfg = load_config(env_path=str(tmp_path / "nonexistent.env"), require_dashboard_token=True)
    assert cfg.exchange.paper_trading is True
    assert cfg.strategy.trading_pairs


def test_load_config_raises_on_bad_bool(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_TRADING", "maybe")
    monkeypatch.setenv("PAPER_ENVIRONMENT", "simulated")
    with pytest.raises((ValueError, ConfigError)):
        load_config(env_path=str(tmp_path / "nonexistent.env"))


def test_load_config_dashboard_token_required(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_TRADING", "true")
    monkeypatch.setenv("PAPER_ENVIRONMENT", "simulated")
    monkeypatch.setenv("DASHBOARD_TOKEN", "short")
    with pytest.raises(ConfigError):
        load_config(env_path=str(tmp_path / "nonexistent.env"), require_dashboard_token=True)