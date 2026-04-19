"""
Sentiment Momentum Strategy.

Trades when strong sentiment momentum aligns with a modest price edge.
Focuses on markets where crowd psychology is lagging reality.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.strategies.base import BaseStrategy


class SentimentMomentumStrategy(BaseStrategy):
    """Trades on sentiment + volume momentum signals."""

    @property
    def name(self) -> str:
        return "sentiment_momentum"

    def should_trade(self, signal: Dict) -> bool:
        sent_threshold = self.params.get("sentiment_threshold", 0.6)
        min_vol_spike = self.params.get("min_volume_spike", 2.0)

        edge = signal.get("net_edge", 0)
        sentiment = signal.get("sentiment_signal", 0)
        vol_spike = signal.get("volume_spike", 1.0)
        confidence = signal.get("confidence", 0)

        sentiment_aligned = (
            (sentiment > sent_threshold and signal.get("side") == "YES")
            or (sentiment < -sent_threshold and signal.get("side") == "NO")
        )

        return (
            edge > 0.01
            and sentiment_aligned
            and vol_spike >= min_vol_spike
            and confidence > 0.45
        )

    def size_override(self, signal: Dict, bankroll: float) -> Optional[float]:
        max_pct = self.params.get("max_position_pct", 0.05)
        kelly = self.params.get("kelly_fraction", 0.15)
        raw_kelly = signal.get("kelly_fraction", 0)
        if raw_kelly <= 0:
            return None
        return bankroll * min(raw_kelly * kelly, max_pct)
