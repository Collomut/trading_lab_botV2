import pandas as pd
import pytest

from models.features import FeatureEngine
from models.calibration import PlattCalibrator, IsotonicCalibrator, brier_score, reliability_curve
from models.sklearn_model import SklearnGradientModel


def test_feature_engine_returns_all_features(synthetic_df):
    engine = FeatureEngine()
    features = engine.compute(synthetic_df)
    assert features is not None
    assert set(features) == set(engine.get_feature_names())
    assert all(isinstance(v, float) for v in features.values())


def test_feature_engine_requires_warmup(synthetic_df):
    engine = FeatureEngine()
    assert engine.compute(synthetic_df.iloc[:100]) is None


def test_feature_engine_no_lookahead():
    """Adding later bars must not change earlier computed features."""
    from data.synthetic import generate_ohlcv

    df = generate_ohlcv(n=800, seed=3)
    engine = FeatureEngine()
    prefix = engine.compute_matrix(df.iloc[:600])
    full = engine.compute_matrix(df)
    pd.testing.assert_frame_equal(prefix, full.iloc[:600])


def test_calibration_improves_brier():
    rng = __import__("numpy").random.default_rng(0)
    raw = rng.uniform(0.2, 0.8, size=400)
    labels = (rng.uniform(0, 1, size=400) < raw * 0.5 + 0.3).astype(int)
    # Build miscalibrated raw scores.
    raw = 0.5 + (raw - 0.5) * 1.8
    raw = __import__("numpy").clip(raw, 0.01, 0.99)
    cal = PlattCalibrator().fit(raw, labels)
    calibrated = cal.calibrate(raw)
    assert brier_score(calibrated, labels) <= brier_score(raw, labels)


def test_isotonic_calibrator_fits():
    import numpy as np

    raw = np.linspace(0, 1, 200)
    labels = (np.linspace(0, 1, 200) < 0.5 + raw * 0.2).astype(int)
    cal = IsotonicCalibrator().fit(raw, labels)
    assert cal.calibrate(raw).min() >= 0.0
    assert cal.calibrate(raw).max() <= 1.0


def test_sklearn_model_train_and_predict(synthetic_df):
    from models.trainer import ModelTrainer
    from config.schemas import ModelConfig

    trainer = ModelTrainer(FeatureEngine(), ModelConfig(model_type="sklearn"))
    model, metrics = trainer.train(synthetic_df)
    assert model.feature_names
    features = FeatureEngine().compute(synthetic_df)
    p, r = model.predict(features)
    assert 0.0 <= p <= 1.0
    assert isinstance(r, float)


def test_reliability_curve_structure():
    import numpy as np

    p = np.linspace(0, 1, 100)
    y = (np.linspace(0, 1, 100) < 0.6).astype(int)
    curve = reliability_curve(p, y, n_bins=5)
    assert len(curve["bin_edges"]) == 6
    assert len(curve["predicted"]) == 5