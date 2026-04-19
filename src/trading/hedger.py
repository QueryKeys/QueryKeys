"""
Hedging & arbitrage detection module.

Detects and executes:
  1. Complementary YES/NO arbitrage (YES + NO prices ≠ 1.0)
  2. Cross-market correlation hedges (related political markets)
  3. Portfolio delta-neutral hedging
  4. Automatic position rebalancing
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from src.core.config import Settings
from src.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class ArbitrageOpportunity:
    type: str
    condition_id: str
    yes_price: float
    no_price: float
    arb_edge: float
    estimated_profit: float
    size_usd: float
    executable: bool


class Hedger:
    """Detects and signals hedging/arbitrage opportunities."""

    def __init__(self, settings: Settings, min_arb_edge: float = 0.02) -> None:
        self._settings = settings
        self._min_arb_edge = min_arb_edge

    async def scan_arbitrage(
        self,
        markets: List[Dict],
        orderbooks: Dict[str, Dict],
        max_size_usd: float = 100.0,
    ) -> List[ArbitrageOpportunity]:
        """
        Scan a list of markets for YES/NO arbitrage.
        Each Polymarket binary market has YES and NO tokens.
        If YES_ask + NO_ask < 1.0, buying both guarantees a profit.
        """
        opportunities = []
        for market in markets:
            cid = market.get("conditionId") or market.get("condition_id", "")
            yes_token = market.get("clobTokenIds", [None, None])[0]
            no_token = market.get("clobTokenIds", [None, None])[1]

            if not yes_token or not no_token:
                continue

            yes_ob = orderbooks.get(yes_token, {})
            no_ob = orderbooks.get(no_token, {})

            yes_ask = yes_ob.get("best_ask")
            no_ask = no_ob.get("best_ask")

            if yes_ask is None or no_ask is None:
                continue

            total_cost = yes_ask + no_ask
            edge = 1.0 - total_cost

            if edge >= self._min_arb_edge:
                profit = edge * (max_size_usd / max(total_cost, 0.01))
                opp = ArbitrageOpportunity(
                    type="complementary",
                    condition_id=cid,
                    yes_price=yes_ask,
                    no_price=no_ask,
                    arb_edge=edge,
                    estimated_profit=profit,
                    size_usd=max_size_usd,
                    executable=True,
                )
                opportunities.append(opp)
                log.info(
                    "hedger.arb_detected",
                    condition_id=cid[:12],
                    edge=round(edge, 4),
                    profit=round(profit, 2),
                )

        return sorted(opportunities, key=lambda x: x.arb_edge, reverse=True)

    def compute_portfolio_hedge_ratio(
        self,
        positions: List[Dict],
        target_exposure: float = 0.0,
    ) -> List[Dict]:
        """
        Compute hedge trades to bring portfolio delta toward target_exposure.
        Returns list of suggested hedge trades.
        """
        net_yes_exposure = sum(
            p.get("size_usd", 0)
            for p in positions
            if p.get("side") == "YES"
        )
        net_no_exposure = sum(
            p.get("size_usd", 0)
            for p in positions
            if p.get("side") == "NO"
        )
        current_delta = net_yes_exposure - net_no_exposure
        delta_to_hedge = current_delta - target_exposure

        hedges = []
        if abs(delta_to_hedge) > 10:  # $10 minimum hedge size
            if delta_to_hedge > 0:
                hedges.append({
                    "action": "buy_no",
                    "size_usd": abs(delta_to_hedge),
                    "rationale": f"Reducing net long delta ${current_delta:.0f} → ${target_exposure:.0f}",
                })
            else:
                hedges.append({
                    "action": "buy_yes",
                    "size_usd": abs(delta_to_hedge),
                    "rationale": f"Reducing net short delta ${current_delta:.0f} → ${target_exposure:.0f}",
                })

        return hedges

    def find_correlated_markets(
        self,
        target_condition_id: str,
        all_markets: List[Dict],
        category: str,
    ) -> List[Dict]:
        """
        Find markets in the same category that might be correlated
        (e.g., two political election markets in same country).
        Useful for natural hedges.
        """
        related = []
        for m in all_markets:
            cid = m.get("conditionId") or m.get("condition_id", "")
            if cid == target_condition_id:
                continue
            if m.get("category") == category:
                related.append(m)
        return related[:5]
