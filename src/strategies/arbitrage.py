"""
Arbitrage Strategy — executes complementary YES/NO book arbitrage.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.strategies.base import BaseStrategy


class ArbitrageStrategy(BaseStrategy):
    """Trades pure YES+NO complementary arbitrage when total cost < 1.0."""

    @property
    def name(self) -> str:
        return "arbitrage"

    def should_trade(self, signal: Dict) -> bool:
        min_arb_edge = self.params.get("min_arb_edge", 0.02)
        arb_edge = signal.get("arb_edge", 0)
        return arb_edge >= min_arb_edge

    def size_override(self, signal: Dict, bankroll: float) -> Optional[float]:
        max_pct = self.params.get("max_position_pct", 0.05)
        arb_edge = signal.get("arb_edge", 0)
        if arb_edge <= 0:
            return None
        # Size proportional to edge confidence
        size = bankroll * min(arb_edge * 2, max_pct)
        return size
