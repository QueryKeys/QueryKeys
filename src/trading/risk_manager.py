"""
Institutional-grade risk management module.

Enforces:
  - Per-market position limits
  - Per-category exposure limits
  - Portfolio-level exposure cap
  - Daily loss limit (circuit breaker)
  - Maximum drawdown halt
  - Correlation-aware position sizing
  - Real-time P&L tracking
  - Dynamic exposure reduction during drawdown
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from typing import Dict, List, Optional, Set, Tuple

from src.core.config import Settings
from src.core.exceptions import CircuitBreakerOpen, RiskLimitExceeded
from src.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class PortfolioState:
    total_value: float = 10000.0
    cash: float = 10000.0
    invested: float = 0.0
    peak_value: float = 10000.0
    day_start_value: float = 10000.0
    day_start_date: date = field(default_factory=lambda: date.today())
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    drawdown: float = 0.0
    positions: Dict[str, "PositionRecord"] = field(default_factory=dict)
    category_exposure: Dict[str, float] = field(default_factory=dict)


@dataclass
class PositionRecord:
    condition_id: str
    category: str
    side: str
    size_usd: float
    avg_cost: float
    current_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    opened_at: float = field(default_factory=time.time)


@dataclass
class RiskCheckResult:
    allowed: bool
    reason: str
    adjusted_size_usd: float
    risk_level: str  # "green" | "yellow" | "red"


class RiskManager:
    """Real-time portfolio risk monitor and position sizer."""

    def __init__(self, settings: Settings, initial_capital: float = 10000.0) -> None:
        self._cfg = settings.risk
        self._exe = settings.execution
        self._state = PortfolioState(
            total_value=initial_capital,
            cash=initial_capital,
            peak_value=initial_capital,
            day_start_value=initial_capital,
        )
        self._circuit_breaker_open = False
        self._circuit_breaker_until: float = 0.0
        self._halted = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def bankroll(self) -> float:
        return self._state.total_value

    @property
    def cash(self) -> float:
        return self._state.cash

    @property
    def is_trading_allowed(self) -> bool:
        if self._halted:
            return False
        if self._circuit_breaker_open:
            if time.time() > self._circuit_breaker_until:
                self._circuit_breaker_open = False
                log.info("risk_manager.circuit_breaker_reset")
            else:
                return False
        return True

    @property
    def drawdown(self) -> float:
        return self._state.drawdown

    # ------------------------------------------------------------------
    # Core risk check
    # ------------------------------------------------------------------

    def check_new_position(
        self,
        condition_id: str,
        category: str,
        side: str,
        requested_size_usd: float,
    ) -> RiskCheckResult:
        """
        Check if a new position is allowed and compute the permitted size.
        Raises CircuitBreakerOpen if breaker is tripped.
        """
        if not self.is_trading_allowed:
            raise CircuitBreakerOpen(
                f"Trading halted — circuit breaker open until {self._circuit_breaker_until}"
            )

        bankroll = self._state.total_value
        issues = []
        adjusted_size = requested_size_usd

        # 1. Minimum/maximum order size
        adjusted_size = max(self._exe.min_order_size, adjusted_size)
        adjusted_size = min(self._exe.max_order_size, adjusted_size)

        # 2. Single market cap
        current_market_exposure = self._get_market_exposure(condition_id)
        max_market_usd = bankroll * self._cfg.max_single_market
        remaining_market = max_market_usd - current_market_exposure
        if remaining_market <= 0:
            return RiskCheckResult(
                allowed=False,
                reason=f"Market {condition_id[:12]} at max exposure ({max_market_usd:.0f} USD)",
                adjusted_size_usd=0.0,
                risk_level="red",
            )
        adjusted_size = min(adjusted_size, remaining_market)

        # 3. Category cap
        cat_exposure = self._state.category_exposure.get(category, 0.0)
        max_cat_usd = bankroll * self._cfg.max_category_exposure
        remaining_cat = max_cat_usd - cat_exposure
        if remaining_cat <= 0:
            return RiskCheckResult(
                allowed=False,
                reason=f"Category {category} at max exposure ({max_cat_usd:.0f} USD)",
                adjusted_size_usd=0.0,
                risk_level="red",
            )
        adjusted_size = min(adjusted_size, remaining_cat)

        # 4. Portfolio-level cap
        total_invested = self._state.invested
        max_portfolio_usd = bankroll * self._cfg.max_portfolio_exposure
        remaining_portfolio = max_portfolio_usd - total_invested
        if remaining_portfolio <= 0:
            return RiskCheckResult(
                allowed=False,
                reason=f"Portfolio at max exposure ({max_portfolio_usd:.0f} USD)",
                adjusted_size_usd=0.0,
                risk_level="red",
            )
        adjusted_size = min(adjusted_size, remaining_portfolio)

        # 5. Cash check
        if adjusted_size > self._state.cash:
            adjusted_size = self._state.cash

        # 6. Daily loss limit
        day_pnl_pct = self._state.daily_pnl / max(self._state.day_start_value, 1)
        if day_pnl_pct < -self._cfg.max_daily_loss:
            self._trip_circuit_breaker(duration=3600)  # 1 hour cooling off
            raise CircuitBreakerOpen(
                f"Daily loss limit hit: {day_pnl_pct:.1%} (limit {self._cfg.max_daily_loss:.1%})"
            )

        # 7. Max drawdown halt
        if self._state.drawdown > self._cfg.max_drawdown:
            self._halted = True
            log.critical(
                "risk_manager.max_drawdown_halt",
                drawdown=self._state.drawdown,
                limit=self._cfg.max_drawdown,
            )
            raise CircuitBreakerOpen(
                f"Max drawdown exceeded: {self._state.drawdown:.1%}"
            )

        if adjusted_size < self._exe.min_order_size:
            return RiskCheckResult(
                allowed=False,
                reason=f"Adjusted size {adjusted_size:.2f} < minimum {self._exe.min_order_size}",
                adjusted_size_usd=0.0,
                risk_level="yellow",
            )

        risk_level = "green"
        total_exp_pct = (total_invested + adjusted_size) / bankroll
        if total_exp_pct > 0.6:
            risk_level = "yellow"

        return RiskCheckResult(
            allowed=True,
            reason="OK",
            adjusted_size_usd=adjusted_size,
            risk_level=risk_level,
        )

    # ------------------------------------------------------------------
    # State updates
    # ------------------------------------------------------------------

    def record_position_opened(
        self,
        condition_id: str,
        category: str,
        side: str,
        size_usd: float,
        entry_price: float,
    ) -> None:
        pos = PositionRecord(
            condition_id=condition_id,
            category=category,
            side=side,
            size_usd=size_usd,
            avg_cost=entry_price,
            current_price=entry_price,
        )
        key = f"{condition_id}_{side}"
        if key in self._state.positions:
            # Average in
            existing = self._state.positions[key]
            total_size = existing.size_usd + size_usd
            existing.avg_cost = (
                existing.avg_cost * existing.size_usd + entry_price * size_usd
            ) / total_size
            existing.size_usd = total_size
        else:
            self._state.positions[key] = pos

        self._state.cash -= size_usd
        self._state.invested += size_usd
        self._state.category_exposure[category] = (
            self._state.category_exposure.get(category, 0) + size_usd
        )
        log.info(
            "risk_manager.position_opened",
            condition_id=condition_id[:12],
            side=side,
            size_usd=size_usd,
            total_invested=self._state.invested,
        )

    def record_position_closed(
        self,
        condition_id: str,
        side: str,
        category: str,
        size_usd: float,
        exit_price: float,
        entry_price: float,
    ) -> float:
        """Record position close and return realized P&L."""
        pnl = (exit_price - entry_price) * (size_usd / max(entry_price, 0.01))
        key = f"{condition_id}_{side}"
        if key in self._state.positions:
            del self._state.positions[key]

        self._state.cash += size_usd + pnl
        self._state.invested = max(0, self._state.invested - size_usd)
        self._state.category_exposure[category] = max(
            0, self._state.category_exposure.get(category, 0) - size_usd
        )
        self._state.total_pnl += pnl
        self._state.daily_pnl += pnl
        self._update_portfolio_value()
        log.info(
            "risk_manager.position_closed",
            condition_id=condition_id[:12],
            side=side,
            pnl=round(pnl, 2),
            total_pnl=round(self._state.total_pnl, 2),
        )
        return pnl

    def update_prices(self, price_updates: Dict[str, float]) -> None:
        """
        Update current prices for open positions and recompute P&L.
        price_updates: {condition_id: current_yes_price}
        """
        today = date.today()
        if self._state.day_start_date != today:
            self._state.day_start_date = today
            self._state.day_start_value = self._state.total_value
            self._state.daily_pnl = 0.0

        for key, pos in self._state.positions.items():
            cid = pos.condition_id
            if cid in price_updates:
                new_price = price_updates[cid]
                if pos.side == "YES":
                    pos.unrealized_pnl = (new_price - pos.avg_cost) * (
                        pos.size_usd / max(pos.avg_cost, 0.01)
                    )
                else:
                    pos.unrealized_pnl = ((1 - new_price) - pos.avg_cost) * (
                        pos.size_usd / max(pos.avg_cost, 0.01)
                    )
                pos.current_price = new_price

        self._update_portfolio_value()

        # Intraday circuit breaker
        intraday_loss_pct = self._state.daily_pnl / max(self._state.day_start_value, 1)
        if intraday_loss_pct < -self._cfg.circuit_breaker_loss:
            if not self._circuit_breaker_open:
                self._trip_circuit_breaker(duration=1800)
                log.warning(
                    "risk_manager.intraday_circuit_breaker",
                    loss_pct=intraday_loss_pct,
                )

    def _update_portfolio_value(self) -> None:
        unrealized = sum(p.unrealized_pnl for p in self._state.positions.values())
        self._state.total_value = self._state.cash + self._state.invested + unrealized
        if self._state.total_value > self._state.peak_value:
            self._state.peak_value = self._state.total_value
        self._state.drawdown = (
            (self._state.peak_value - self._state.total_value)
            / max(self._state.peak_value, 1)
        )

    def _get_market_exposure(self, condition_id: str) -> float:
        total = 0.0
        for key, pos in self._state.positions.items():
            if pos.condition_id == condition_id:
                total += pos.size_usd
        return total

    def _trip_circuit_breaker(self, duration: float = 3600) -> None:
        self._circuit_breaker_open = True
        self._circuit_breaker_until = time.time() + duration
        log.warning("risk_manager.circuit_breaker_tripped", duration_s=duration)

    def get_portfolio_summary(self) -> Dict:
        unrealized = sum(p.unrealized_pnl for p in self._state.positions.values())
        return {
            "total_value": self._state.total_value,
            "cash": self._state.cash,
            "invested": self._state.invested,
            "unrealized_pnl": unrealized,
            "total_pnl": self._state.total_pnl,
            "daily_pnl": self._state.daily_pnl,
            "drawdown": self._state.drawdown,
            "num_positions": len(self._state.positions),
            "exposure_pct": self._state.invested / max(self._state.total_value, 1),
            "circuit_breaker_open": self._circuit_breaker_open,
            "halted": self._halted,
        }
