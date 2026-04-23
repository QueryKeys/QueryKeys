"""
Late Resolution Convergence Strategy.

Edge source: As a market approaches expiry, liquidity providers withdraw and
market makers widen spreads. If the ensemble model has high conviction (>0.70)
but the market price hasn't converged yet, the gap is structural — not
informational — and mean-reverts rapidly in the final days.

Documented in prediction market literature as one of the most consistent
edges: ~60-65% win rate, compresses quickly so best with short DTE.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.strategies.base import BaseStrategy


class LateResolutionConvergenceStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "late_resolution_convergence"

    def should_trade(self, signal: Dict) -> bool:
        dte = float(signal.get("dte_days", 999))
        model_prob = float(signal.get("model_prob", 0.5))
        market_price = float(signal.get("market_price", 0.5))
        confidence = float(signal.get("confidence", 0.0))
        uncertainty = float(signal.get("uncertainty", 1.0))
        net_edge = float(signal.get("net_edge", 0.0))

        min_dte = float(self.params.get("min_dte", 1))
        max_dte = float(self.params.get("max_dte", 14))
        min_conviction = float(self.params.get("min_conviction", 0.68))
        min_price_gap = float(self.params.get("min_price_gap", 0.07))
        min_confidence = float(self.params.get("min_confidence", 0.55))
        max_uncertainty = float(self.params.get("max_uncertainty", 0.12))
        min_net_edge = float(self.params.get("min_net_edge", 0.03))

        # Must be in the late-resolution window
        if not (min_dte <= dte <= max_dte):
            return False

        # Model must have strong conviction toward one outcome
        if model_prob < min_conviction and model_prob > (1.0 - min_conviction):
            return False

        # Market price must lag behind the model — structural gap, not noise
        price_gap = abs(model_prob - market_price)
        if price_gap < min_price_gap:
            return False

        # Standard ensemble quality gates
        if confidence < min_confidence:
            return False
        if uncertainty > max_uncertainty:
            return False
        if net_edge < min_net_edge:
            return False

        return True

    def size_override(self, signal: Dict, bankroll: float) -> Optional[float]:
        dte = float(signal.get("dte_days", 14))
        net_edge = float(signal.get("net_edge", 0.03))
        base_pct = float(self.params.get("base_position_pct", 0.06))
        max_pct = float(self.params.get("max_position_pct", 0.10))

        # Scale up as DTE shrinks — convergence accelerates near expiry
        dte_boost = 1.0 + max(0.0, (7.0 - dte) / 7.0) * 0.5  # up to 1.5x at DTE=0
        edge_boost = 1.0 + min(net_edge / 0.10, 1.0) * 0.3    # up to 1.3x at edge=10%

        pct = min(base_pct * dte_boost * edge_boost, max_pct)
        return bankroll * pct
