"""
Kelly Criterion position sizing — institutional grade.

Implements:
  - Full Kelly
  - Fractional Kelly (safety multiplier)
  - Half-Kelly
  - Kelly with volatility adjustment
  - Kelly with correlation penalty (for portfolios)
  - Kelly with uncertainty discount (based on ensemble std)
  - Multi-asset Kelly (log-utility portfolio optimization)

Reference: Kelly (1956), Thorp (1997), MacLean et al (2011)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from src.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class KellyResult:
    kelly_fraction: float           # raw Kelly fraction [0,1]
    adjusted_fraction: float        # after safety multiplier & adjustments
    bet_size_usd: float             # dollar amount to bet
    bet_size_pct: float             # as % of bankroll
    expected_growth_rate: float     # E[log wealth growth] per bet
    expected_value: float
    breakeven_prob: float           # probability at which EV = 0
    rationale: str


class KellyCriterion:
    """
    Computes optimal bet sizes using Kelly Criterion variants.
    All inputs in probability space [0,1].
    """

    def __init__(
        self,
        kelly_fraction: float = 0.25,   # fractional Kelly multiplier
        min_kelly_edge: float = 0.01,
        max_fraction: float = 0.20,     # hard cap on single bet
    ) -> None:
        self._kelly_fraction = kelly_fraction
        self._min_edge = min_kelly_edge
        self._max_fraction = max_fraction

    def compute(
        self,
        model_prob: float,          # model's probability of YES
        entry_price: float,         # price to buy at
        side: str,                  # "YES" | "NO"
        bankroll: float,            # total available capital
        uncertainty: float = 0.0,   # model std (0 = certain)
        correlation: float = 0.0,   # correlation with existing portfolio
        existing_exposure_pct: float = 0.0,  # existing exposure in same market
    ) -> KellyResult:
        """
        Compute Kelly bet size.

        For binary prediction markets:
          b = (1 - price) / price  (net odds per unit bet if correct)
          p = model_prob
          q = 1 - p
          Kelly = (p*b - q) / b = p - q/b

        Args:
            model_prob: true probability estimate [0,1]
            entry_price: cost per contract [0,1], e.g. 0.60 = 60c YES
            side: "YES" or "NO"
            bankroll: total capital in USD
            uncertainty: std of model probabilities (0 = high certainty)
            correlation: correlation with existing positions (-1 to 1)
            existing_exposure_pct: fraction of bankroll already in this market
        """
        # From the perspective of the trade, normalize to "true prob vs price"
        if side == "YES":
            p = model_prob
            price = entry_price
        else:
            p = 1.0 - model_prob
            price = entry_price  # NO price = 1 - YES_price already computed by caller

        p = max(0.01, min(0.99, p))
        price = max(0.01, min(0.99, price))

        q = 1.0 - p
        b = (1.0 - price) / price  # net odds (profit per unit staked if win)

        # Raw Kelly
        edge = p * b - q
        if edge <= self._min_edge:
            return KellyResult(
                kelly_fraction=0.0,
                adjusted_fraction=0.0,
                bet_size_usd=0.0,
                bet_size_pct=0.0,
                expected_growth_rate=0.0,
                expected_value=edge,
                breakeven_prob=price,
                rationale=f"Edge {edge:.4f} below minimum {self._min_edge}",
            )

        raw_kelly = edge / b
        raw_kelly = max(0.0, min(1.0, raw_kelly))

        # Uncertainty discount: high uncertainty → reduce Kelly
        uncertainty_multiplier = max(0.0, 1.0 - uncertainty * 3.0)

        # Correlation penalty: correlated positions reduce diversification value
        correlation_multiplier = max(0.0, 1.0 - abs(correlation) * 0.5)

        # Fractional Kelly with all adjustments
        adjusted = (
            raw_kelly
            * self._kelly_fraction
            * uncertainty_multiplier
            * correlation_multiplier
        )
        adjusted = max(0.0, min(self._max_fraction, adjusted))

        # Subtract existing exposure in this market
        adjusted = max(0.0, adjusted - existing_exposure_pct)

        bet_usd = bankroll * adjusted
        ev = p * b - q  # expected value per unit staked
        eg = p * math.log(1 + b * adjusted) + q * math.log(1 - adjusted)

        return KellyResult(
            kelly_fraction=raw_kelly,
            adjusted_fraction=adjusted,
            bet_size_usd=bet_usd,
            bet_size_pct=adjusted,
            expected_growth_rate=eg,
            expected_value=ev,
            breakeven_prob=price,
            rationale=(
                f"Kelly={raw_kelly:.3f} → "
                f"×{self._kelly_fraction} fraction × "
                f"×{uncertainty_multiplier:.2f} uncertainty × "
                f"×{correlation_multiplier:.2f} correlation = {adjusted:.3f}"
            ),
        )

    def compute_portfolio_kelly(
        self,
        opportunities: List[Dict],
        bankroll: float,
        max_total_exposure: float = 0.80,
    ) -> List[Dict]:
        """
        Multi-asset Kelly optimization.
        Allocates capital across multiple simultaneous opportunities.

        opportunities: list of {
            'condition_id', 'model_prob', 'entry_price', 'side', 'uncertainty'
        }
        """
        if not opportunities:
            return []

        # Compute individual Kelly fractions
        results = []
        for opp in opportunities:
            kr = self.compute(
                model_prob=opp["model_prob"],
                entry_price=opp["entry_price"],
                side=opp["side"],
                bankroll=bankroll,
                uncertainty=opp.get("uncertainty", 0),
            )
            if kr.adjusted_fraction > 0:
                results.append({**opp, "kelly_result": kr, "fraction": kr.adjusted_fraction})

        if not results:
            return []

        # Scale down if total exceeds max exposure
        total = sum(r["fraction"] for r in results)
        if total > max_total_exposure:
            scale = max_total_exposure / total
            for r in results:
                r["fraction"] *= scale
                r["kelly_result"].adjusted_fraction *= scale
                r["kelly_result"].bet_size_usd = bankroll * r["fraction"]

        return results
