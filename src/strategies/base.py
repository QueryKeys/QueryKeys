"""
Base strategy interface.

All strategies must inherit from BaseStrategy and implement:
  - name: unique string identifier
  - should_trade(signal) -> bool
  - size_override(signal, bankroll) -> Optional[float]

Strategies are loaded dynamically from config/strategies.yaml.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseStrategy(ABC):
    """Abstract base class for all prediction strategies."""

    def __init__(self, params: Dict[str, Any]) -> None:
        self.params = params

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique strategy name."""
        ...

    @abstractmethod
    def should_trade(self, signal: Dict) -> bool:
        """
        Return True if this strategy approves trading this signal.
        signal contains: condition_id, side, edge, net_edge, confidence,
                         uncertainty, model_prob, market_price, kelly_fraction
        """
        ...

    def size_override(self, signal: Dict, bankroll: float) -> Optional[float]:
        """
        Optionally override the Kelly-computed size.
        Return None to use default Kelly sizing.
        """
        return None

    def on_fill(self, order: Dict) -> None:
        """Called when an order is filled. Override for bookkeeping."""
        pass

    def on_resolution(self, condition_id: str, outcome: float) -> None:
        """Called when a market resolves. Override for model updates."""
        pass
