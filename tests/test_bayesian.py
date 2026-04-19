"""Tests for Bayesian predictor."""
import pytest
from src.prediction.bayesian import BayesianPredictor


@pytest.fixture
def predictor():
    return BayesianPredictor(prior_alpha=1.0, prior_beta=1.0)


def test_prediction_in_range(predictor):
    result = predictor.predict(market_price=0.60)
    assert 0 < result.mean < 1
    assert result.lower < result.mean < result.upper


def test_high_market_price_shifts_up(predictor):
    low = predictor.predict(market_price=0.20)
    high = predictor.predict(market_price=0.80)
    assert high.mean > low.mean


def test_positive_sentiment_increases_prob(predictor):
    neutral = predictor.predict(market_price=0.50, sentiment_score=0.0)
    positive = predictor.predict(market_price=0.50, sentiment_score=0.8)
    assert positive.mean > neutral.mean


def test_credible_interval_narrows_with_data(predictor):
    sparse = predictor.predict(market_price=0.50, market_price_weight=1.0)
    rich = predictor.predict(market_price=0.50, market_price_weight=50.0)
    assert (rich.upper - rich.lower) < (sparse.upper - sparse.lower)


def test_brier_contribution(predictor):
    # Perfect prediction
    assert predictor.brier_contribution(1.0, 1.0) == 0.0
    # Worst prediction
    assert predictor.brier_contribution(1.0, 0.0) == 1.0
    # Middle
    assert 0 < predictor.brier_contribution(0.7, 0.0) < 1.0
