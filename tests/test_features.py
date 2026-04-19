"""Tests for feature engineering pipeline."""
import pytest
from src.features.engineer import FeatureEngineer


@pytest.fixture
def fe():
    return FeatureEngineer()


def test_extract_returns_dict(fe):
    features = fe.extract(
        market={"category": "Politics", "endDate": "2026-06-01T00:00:00Z"},
        orderbook={"best_bid": 0.45, "best_ask": 0.55, "midpoint": 0.50, "spread": 0.10},
        price_history=[{"p": 0.48}, {"p": 0.50}, {"p": 0.52}],
        analytics={"volume": {"volume24hr": 5000}, "open_interest": {}, "recent_trades": []},
        sentiment_score=0.2,
        sentiment_confidence=0.7,
    )
    assert isinstance(features, dict)
    assert len(features) > 10
    assert all(isinstance(v, float) for v in features.values())


def test_rsi_bounds(fe):
    prices = [0.5, 0.52, 0.51, 0.53, 0.54, 0.50, 0.48, 0.49, 0.51, 0.52,
              0.53, 0.54, 0.55, 0.53, 0.50]
    rsi = fe._rsi(prices, period=14)
    assert 0 <= rsi <= 100


def test_feature_vector_sorted(fe):
    features = {"z": 1.0, "a": 2.0, "m": 3.0}
    names, values = fe.to_vector(features)
    assert names == sorted(names)
    assert len(names) == len(values)


def test_empty_orderbook_safe(fe):
    features = fe.extract(
        market={"category": "Crypto"},
        orderbook=None,
        price_history=[],
        analytics={"volume": {}, "open_interest": {}, "recent_trades": []},
    )
    assert "spread" in features
    assert "midpoint" in features


def test_numpy_output(fe):
    import numpy as np
    features = fe.extract(
        market={"category": "Sports"},
        orderbook=None,
        price_history=[{"p": 0.5}] * 10,
        analytics={"volume": {"volume24hr": 1000}, "open_interest": {}, "recent_trades": []},
    )
    arr = fe.to_numpy(features)
    assert isinstance(arr, np.ndarray)
    assert arr.dtype == np.float32
    assert not np.any(np.isnan(arr))
