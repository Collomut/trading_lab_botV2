from risk.sizing import PositionSizer


def test_sizing_respects_notional_cap(risk_config):
    sizer = PositionSizer(risk_config)
    # 1% risk on 10000 = 100; stop distance 2 -> 50 units, but 10% notional cap -> 10 units.
    size = sizer.calculate(10000.0, 100.0, 98.0)
    assert abs(size - 10.0) < 1e-9


def test_sizing_confidence_scales_down(risk_config):
    sizer = PositionSizer(risk_config)
    # Use a stop far enough from entry that the risk budget (not the notional cap) binds,
    # so confidence scaling is observable.
    low_prob = sizer.calculate(10000.0, 100.0, 80.0, probability=1.0)  # risk budget binds
    scaled = sizer.calculate(10000.0, 100.0, 80.0, probability=0.55, confidence_threshold=0.60)
    assert scaled < low_prob
    assert abs(sizer.confidence_multiplier(0.55, 0.60) - 0.5) < 1e-9


def test_sizing_rejects_invalid_prices(risk_config):
    sizer = PositionSizer(risk_config)
    assert sizer.calculate(10000.0, 100.0, 100.0) == 0.0
    assert sizer.calculate(10000.0, 100.0, 101.0) == 0.0
    assert sizer.calculate(0.0, 100.0, 98.0) == 0.0
    assert sizer.calculate(-5.0, 100.0, 98.0) == 0.0


def test_sizing_min_notional_rejects(risk_config):
    sizer = PositionSizer(risk_config)
    size = sizer.calculate(10000.0, 100.0, 98.0, min_notional=1_000_000)
    assert size == 0.0


def test_volatility_multiplier_bounds():
    from config.schemas import RiskConfig

    sizer = PositionSizer(RiskConfig())
    assert sizer.volatility_multiplier(None, None) == 1.0
    assert sizer.volatility_multiplier(0.4, 0.8) == 0.5
    assert sizer.volatility_multiplier(0.4, 0.4) == 1.0
    assert sizer.volatility_multiplier(0.4, 0.001) == 1.0


def test_amount_step_rounds_down(risk_config):
    sizer = PositionSizer(risk_config)
    size = sizer.calculate(10000.0, 100.0, 98.0, amount_step=3.0)
    assert size == 9.0
