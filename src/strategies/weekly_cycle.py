"""
Weekly Cycle Strategy.

Edge source: Prediction markets have documented day-of-week patterns:
- Monday/Tuesday: fresh news cycle, markets reprice from weekend → entry window
- Wednesday: highest liquidity, tightest spreads → best fills
- Thursday/Friday: position building before weekend resolution events
- Weekend: avoid — low liquidity, wide spreads, manual resolution lag

Additionally, markets resolving within 7 days (weekly events: sports, weekly
crypto/economic releases, weekly political polls) tend to have the sharpest
price convergence and best Kelly returns due to short duration uncertainty.

This strategy overlays a time-quality filter on top of the ensemble signal,
concentrating bets on the highest-quality windows of the week.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.strategies.base import BaseStrategy


class WeeklyCycleStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "weekly_cycle"

    def should_trade(self, signal: Dict) -> bool:
        net_edge = float(signal.get("net_edge", 0.0))
        confidence = float(signal.get("confidence", 0.0))
        uncertainty = float(signal.get("uncertainty", 1.0))
        dte = float(signal.get("dte_days", 999))
        volume = float(signal.get("volume_24h", 0.0))

        min_edge = float(self.params.get("min_net_edge", 0.04))
        min_confidence = float(self.params.get("min_confidence", 0.58))
        max_uncertainty = float(self.params.get("max_uncertainty", 0.12))
        min_dte = float(self.params.get("min_dte", 1))
        max_dte = float(self.params.get("max_dte", 7))
        min_volume = float(self.params.get("min_volume_24h", 3000))
        allowed_days = self.params.get("allowed_weekdays", [0, 1, 2, 3, 4])  # Mon–Fri

        # Standard quality gates
        if net_edge < min_edge:
            return False
        if confidence < min_confidence:
            return False
        if uncertainty > max_uncertainty:
            return False
        if volume < min_volume:
            return False

        # Weekly resolution window — target markets closing within the week
        if not (min_dte <= dte <= max_dte):
            return False

        # Day-of-week filter (skip weekends by default)
        today = datetime.now(timezone.utc).weekday()  # 0=Mon, 6=Sun
        if today not in allowed_days:
            return False

        # Peak liquidity window: avoid the dead hours (00:00–06:00 UTC)
        hour = datetime.now(timezone.utc).hour
        avoid_hours = self.params.get("avoid_utc_hours", list(range(0, 6)))
        if hour in avoid_hours:
            return False

        return True

    def size_override(self, signal: Dict, bankroll: float) -> Optional[float]:
        dte = float(signal.get("dte_days", 7))
        net_edge = float(signal.get("net_edge", 0.04))
        base_pct = float(self.params.get("base_position_pct", 0.05))
        max_pct = float(self.params.get("max_position_pct", 0.09))

        # Slightly larger on Wed (highest liquidity = better fills)
        today = datetime.now(timezone.utc).weekday()
        liquidity_boost = 1.15 if today == 2 else 1.0  # Wednesday bonus

        # Edge scaling
        edge_mult = 1.0 + min(net_edge / 0.08, 1.0) * 0.4

        pct = min(base_pct * liquidity_boost * edge_mult, max_pct)
        return bankroll * pct
