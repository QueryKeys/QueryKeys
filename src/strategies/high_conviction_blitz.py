"""
High Conviction Blitz Strategy.

RISK WARNING: This strategy uses near-full Kelly sizing on a concentrated set
of very high-edge signals. Expected weekly variance is extreme — possible
to 2-3x in a week, equally possible to lose 60-80%. Do NOT run on capital
you cannot afford to lose entirely.

Edge source: When the ensemble has very high conviction (edge > 12%, confidence
> 75%, low uncertainty), the expected value of a large bet is maximised.
Standard fractional Kelly (0.25x) is too conservative for this regime — this
strategy uses 0.75x Kelly, targeting the highest-quality signals only.

Use on a dedicated sub-account, not your full bankroll.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.strategies.base import BaseStrategy


class HighConvictionBlitzStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "high_conviction_blitz"

    def should_trade(self, signal: Dict) -> bool:
        net_edge     = float(signal.get("net_edge", 0.0))
        confidence   = float(signal.get("confidence", 0.0))
        uncertainty  = float(signal.get("uncertainty", 1.0))
        model_prob   = float(signal.get("model_prob", 0.5))
        market_price = float(signal.get("market_price", 0.5))
        volume       = float(signal.get("volume_24h", 0.0))
        dte          = float(signal.get("dte_days", 999))

        min_edge        = float(self.params.get("min_net_edge", 0.12))
        min_confidence  = float(self.params.get("min_confidence", 0.75))
        max_uncertainty = float(self.params.get("max_uncertainty", 0.08))
        min_volume      = float(self.params.get("min_volume_24h", 10000))
        max_dte         = float(self.params.get("max_dte", 14))

        # Only the very highest-conviction signals
        if net_edge < min_edge:
            return False
        if confidence < min_confidence:
            return False
        if uncertainty > max_uncertainty:
            return False
        if volume < min_volume:
            return False
        if dte > max_dte:
            return False

        # Model must strongly disagree with market (not just noise)
        price_gap = abs(model_prob - market_price)
        if price_gap < float(self.params.get("min_price_gap", 0.10)):
            return False

        return True

    def size_override(self, signal: Dict, bankroll: float) -> Optional[float]:
        model_prob   = float(signal.get("model_prob", 0.5))
        market_price = float(signal.get("market_price", 0.5))
        side         = signal.get("side", "YES")

        # Determine win probability from perspective of the trade
        p = model_prob if side == "YES" else (1.0 - model_prob)
        entry_price = market_price + 0.005  # spread
        b = (1.0 - entry_price) / max(entry_price, 0.01)
        q = 1.0 - p

        # Full Kelly formula
        kelly_full = max(0.0, (p * b - q) / max(b, 0.01))

        # Use 0.75x Kelly — aggressive but not suicidal
        kelly_fraction = float(self.params.get("kelly_fraction", 0.75))
        kelly = kelly_full * kelly_fraction

        # Hard cap per trade (default 25% of bankroll — concentrated but not all-in)
        max_pct = float(self.params.get("max_position_pct", 0.25))
        kelly = min(kelly, max_pct)

        return bankroll * kelly
