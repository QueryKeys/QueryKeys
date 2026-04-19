"""Tests for Kelly Criterion position sizing."""
import pytest
from src.trading.kelly import KellyCriterion


@pytest.fixture
def kelly():
    return KellyCriterion(kelly_fraction=0.25, min_kelly_edge=0.01, max_fraction=0.20)


def test_positive_edge_yes(kelly):
    result = kelly.compute(
        model_prob=0.65,
        entry_price=0.55,
        side="YES",
        bankroll=10_000,
    )
    assert result.kelly_fraction > 0
    assert result.adjusted_fraction > 0
    assert result.bet_size_usd > 0
    assert result.expected_value > 0


def test_no_edge_returns_zero(kelly):
    result = kelly.compute(
        model_prob=0.55,
        entry_price=0.55,
        side="YES",
        bankroll=10_000,
    )
    assert result.adjusted_fraction == 0.0
    assert result.bet_size_usd == 0.0


def test_max_fraction_cap(kelly):
    result = kelly.compute(
        model_prob=0.99,
        entry_price=0.10,
        side="YES",
        bankroll=10_000,
    )
    assert result.adjusted_fraction <= 0.20


def test_uncertainty_reduces_size(kelly):
    r_no_uncertainty = kelly.compute(
        model_prob=0.70, entry_price=0.55, side="YES", bankroll=10_000, uncertainty=0.0
    )
    r_high_uncertainty = kelly.compute(
        model_prob=0.70, entry_price=0.55, side="YES", bankroll=10_000, uncertainty=0.30
    )
    assert r_high_uncertainty.adjusted_fraction <= r_no_uncertainty.adjusted_fraction


def test_no_side(kelly):
    result = kelly.compute(
        model_prob=0.30,  # Model says 30% → NO side should have edge
        entry_price=0.30,  # NO price = 1 - 0.70 = 0.30
        side="NO",
        bankroll=10_000,
    )
    # model says NO is more likely than 1-entry_price, should have edge
    assert result.expected_value != 0  # has some view


def test_portfolio_kelly(kelly):
    opps = [
        {"condition_id": "m1", "model_prob": 0.65, "entry_price": 0.55, "side": "YES", "uncertainty": 0.05},
        {"condition_id": "m2", "model_prob": 0.70, "entry_price": 0.50, "side": "YES", "uncertainty": 0.05},
        {"condition_id": "m3", "model_prob": 0.60, "entry_price": 0.50, "side": "YES", "uncertainty": 0.10},
    ]
    results = kelly.compute_portfolio_kelly(opps, bankroll=10_000, max_total_exposure=0.80)
    total_fraction = sum(r["fraction"] for r in results)
    assert total_fraction <= 0.80 + 1e-9  # never exceeds max exposure
