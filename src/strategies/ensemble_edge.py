"""
Ensemble Edge Strategy — primary strategy.

Trades when:
  - Ensemble model edge > min_edge (default 3%)
  - Confidence > threshold
  - Uncertainty < threshold
  - Kelly fraction > 0
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.strategies.base import BaseStrategy


class EnsembleEdgeStrategy(BaseStrategy):
    """Main ensemble-driven edge strategy."""

    @property
    def name(self) -> str:
        return "ensemble_edge"

    def should_trade(self, signal: Dict) -> bool:
        min_edge = self.params.get("min_edge", 0.03)
        min_conf = self.params.get("min_confidence", 0.55)

        edge = signal.get("net_edge", 0)
        confidence = signal.get("confidence", 0)
        kelly = signal.get("kelly_fraction", 0)

        return (
            edge >= min_edge
            and confidence >= min_conf
            and kelly > 0
        )

    def size_override(self, signal: Dict, bankroll: float) -> Optional[float]:
        max_pct = self.params.get("max_position_pct", 0.08)
        kelly = self.params.get("kelly_fraction", 0.25)
        raw_kelly = signal.get("kelly_fraction", 0)
        if raw_kelly <= 0:
            return None
        size = bankroll * min(raw_kelly * kelly, max_pct)
        return size
