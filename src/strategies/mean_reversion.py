"""
Mean Reversion Strategy.

Trades when market price has deviated significantly from its
historical mean and the ensemble confirms likely reversion.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.strategies.base import BaseStrategy


class MeanReversionStrategy(BaseStrategy):
    """Trades mean reversion when z-score exceeds threshold."""

    @property
    def name(self) -> str:
        return "mean_reversion"

    def should_trade(self, signal: Dict) -> bool:
        z_threshold = self.params.get("zscore_threshold", 2.0)
        z_score = abs(signal.get("price_mean_reversion", 0))
        edge = signal.get("net_edge", 0)
        confidence = signal.get("confidence", 0)

        return z_score >= z_threshold and edge > 0.01 and confidence > 0.45

    def size_override(self, signal: Dict, bankroll: float) -> Optional[float]:
        max_pct = self.params.get("max_position_pct", 0.04)
        kelly = self.params.get("kelly_fraction", 0.10)
        raw_kelly = signal.get("kelly_fraction", 0)
        return bankroll * min(raw_kelly * kelly, max_pct) if raw_kelly > 0 else None
