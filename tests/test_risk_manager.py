"""Tests for risk manager."""
import pytest
from unittest.mock import MagicMock
from src.trading.risk_manager import RiskManager
from src.core.exceptions import CircuitBreakerOpen


def make_settings():
    from src.core.config import Settings
    return Settings()


@pytest.fixture
def risk():
    return RiskManager(make_settings(), initial_capital=10_000.0)


def test_initial_state(risk):
    assert risk.bankroll == 10_000.0
    assert risk.cash == 10_000.0
    assert risk.is_trading_allowed


def test_position_allowed(risk):
    result = risk.check_new_position("mkt1", "Politics", "YES", 100.0)
    assert result.allowed
    assert result.adjusted_size_usd > 0


def test_position_size_capped_by_market_limit(risk):
    result = risk.check_new_position("mkt1", "Politics", "YES", 9999.0)
    assert result.allowed
    # Single market max is 10% of 10k = $1000
    assert result.adjusted_size_usd <= 1000.0 + 1e-6


def test_circuit_breaker_triggers_on_daily_loss(risk):
    risk._state.daily_pnl = -600.0  # 6% loss on $10k, limit is 5%
    with pytest.raises(CircuitBreakerOpen):
        risk.check_new_position("mkt1", "Politics", "YES", 100.0)


def test_record_and_close_position(risk):
    risk.record_position_opened("mkt1", "Politics", "YES", 200.0, 0.50)
    assert risk._state.invested == 200.0
    assert risk._state.cash == 9800.0
    pnl = risk.record_position_closed("mkt1", "YES", "Politics", 200.0, 1.0, 0.50)
    assert pnl > 0
    assert risk._state.invested == 0.0


def test_portfolio_summary(risk):
    summary = risk.get_portfolio_summary()
    assert "total_value" in summary
    assert "drawdown" in summary
    assert "num_positions" in summary
    assert summary["circuit_breaker_open"] is False
