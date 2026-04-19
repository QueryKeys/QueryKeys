"""
Edge detector — converts ensemble predictions into actionable signals.

Computes:
  1. Raw edge (model_prob - market_price)
  2. Liquidity-adjusted edge (penalise thin books)
  3. Spread-adjusted edge (account for entry/exit cost)
  4. Volatility-adjusted edge (Kelly-compatible)
  5. Signals with metadata for downstream risk management

Also detects cross-market arbitrage opportunities (complementary markets
where YES + NO implied probs ≠ 1.0).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from src.core.logging import get_logger
from src.prediction.ensemble import EnsemblePrediction

log = get_logger(__name__)


@dataclass
class EdgeSignal:
    condition_id: str
    side: str                   # "YES" | "NO"
    raw_edge: float
    liquidity_adj_edge: float
    spread_adj_edge: float
    net_edge: float             # final tradeable edge
    entry_price: float
    model_prob: float
    market_price: float
    kelly_fraction: float       # suggested Kelly fraction
    expected_value: float       # EV per unit bet
    confidence: float
    uncertainty: float
    is_tradeable: bool
    reject_reason: str = ""
    metadata: Dict = field(default_factory=dict)


class EdgeDetector:
    """Converts ensemble predictions to tradeable edge signals."""

    def __init__(
        self,
        min_edge: float = 0.03,
        min_confidence: float = 0.55,
        max_uncertainty: float = 0.15,
        max_spread_pct: float = 0.05,
        min_liquidity: float = 500.0,
    ) -> None:
        self._min_edge = min_edge
        self._min_confidence = min_confidence
        self._max_uncertainty = max_uncertainty
        self._max_spread = max_spread_pct
        self._min_liquidity = min_liquidity

    def evaluate(
        self,
        prediction: EnsemblePrediction,
        orderbook: Optional[Dict] = None,
        analytics: Optional[Dict] = None,
    ) -> Optional[EdgeSignal]:
        """
        Evaluate ensemble prediction and return edge signal if tradeable.
        Returns None if no meaningful edge exists.
        """
        yes_prob = prediction.yes_probability
        market_price = prediction.market_price
        raw_edge = yes_prob - market_price

        # Determine side and entry price
        if raw_edge > 0:
            side = "YES"
            entry_price = orderbook.get("best_ask", market_price + 0.01) if orderbook else market_price + 0.01
        else:
            side = "NO"
            entry_price = 1.0 - (orderbook.get("best_bid", market_price - 0.01) if orderbook else market_price - 0.01)
            raw_edge = abs(raw_edge)

        # Reject gate 1: minimum edge
        if raw_edge < self._min_edge:
            return self._rejected(
                prediction, side, entry_price, raw_edge,
                f"Edge {raw_edge:.3f} < min {self._min_edge:.3f}"
            )

        # Reject gate 2: confidence
        if prediction.confidence < self._min_confidence:
            return self._rejected(
                prediction, side, entry_price, raw_edge,
                f"Confidence {prediction.confidence:.3f} < min {self._min_confidence:.3f}"
            )

        # Reject gate 3: uncertainty
        if prediction.uncertainty > self._max_uncertainty:
            return self._rejected(
                prediction, side, entry_price, raw_edge,
                f"Uncertainty {prediction.uncertainty:.3f} > max {self._max_uncertainty:.3f}"
            )

        # Spread adjustment
        spread_cost = 0.0
        liquidity_penalty = 0.0
        if orderbook:
            spread = orderbook.get("spread", 0.0)
            best_bid = orderbook.get("best_bid", 0.0)
            best_ask = orderbook.get("best_ask", 1.0)
            spread_pct = spread / max(market_price, 0.01)

            if spread_pct > self._max_spread:
                return self._rejected(
                    prediction, side, entry_price, raw_edge,
                    f"Spread {spread_pct:.3f} > max {self._max_spread:.3f}"
                )

            spread_cost = spread / 2

            # Liquidity penalty: thin books get penalized
            total_depth = (orderbook.get("bid_depth", 0) + orderbook.get("ask_depth", 0))
            if total_depth < self._min_liquidity:
                liquidity_penalty = min(0.02, self._min_liquidity / max(total_depth, 1) * 0.001)

        if analytics:
            vol_24h = float(analytics.get("volume", {}).get("volume24hr", 0) or 0)
            if vol_24h < 500:
                liquidity_penalty += 0.005

        liquidity_adj_edge = raw_edge - liquidity_penalty
        spread_adj_edge = raw_edge - spread_cost
        net_edge = raw_edge - spread_cost - liquidity_penalty

        if net_edge < self._min_edge * 0.5:
            return self._rejected(
                prediction, side, entry_price, raw_edge,
                f"Net edge {net_edge:.3f} too low after cost adjustments"
            )

        # Kelly fraction (fractional Kelly = net_edge / (entry_price * (1 - entry_price)))
        # Simplified for binary bets: b = (1-p)/p for YES, kelly = (p*b - (1-p)) / b
        model_p = yes_prob if side == "YES" else (1 - yes_prob)
        b = (1 - entry_price) / max(entry_price, 0.01)  # net odds
        kelly = (model_p * b - (1 - model_p)) / max(b, 0.01)
        kelly = max(0.0, kelly)

        ev = model_p * (1 - entry_price) - (1 - model_p) * entry_price

        signal = EdgeSignal(
            condition_id=prediction.condition_id,
            side=side,
            raw_edge=raw_edge,
            liquidity_adj_edge=liquidity_adj_edge,
            spread_adj_edge=spread_adj_edge,
            net_edge=net_edge,
            entry_price=entry_price,
            model_prob=yes_prob,
            market_price=market_price,
            kelly_fraction=kelly,
            expected_value=ev,
            confidence=prediction.confidence,
            uncertainty=prediction.uncertainty,
            is_tradeable=True,
            metadata={
                "llm_reasoning": prediction.llm_reasoning[:200],
                "key_factors": prediction.key_factors,
                "bayesian_prob": prediction.bayesian_prob,
                "lgbm_prob": prediction.lgbm_prob,
                "llm_prob": prediction.llm_prob,
            },
        )
        log.info(
            "edge_detector.signal",
            condition_id=prediction.condition_id[:12],
            side=side,
            net_edge=round(net_edge, 4),
            kelly=round(kelly, 4),
            ev=round(ev, 4),
        )
        return signal

    def detect_arbitrage(
        self,
        yes_market_price: float,
        no_market_price: float,
        condition_id: str,
    ) -> Optional[Dict]:
        """
        Detect arbitrage in complementary YES/NO markets.
        If YES_price + NO_price < 1.0, buy both sides for guaranteed profit.
        If YES_price + NO_price > 1.0, there's an impossible-to-fill arb.
        """
        total = yes_market_price + no_market_price
        arb_edge = abs(1.0 - total)

        if total < 1.0 - 0.01:  # buy both sides
            return {
                "type": "buy_both",
                "condition_id": condition_id,
                "yes_price": yes_market_price,
                "no_price": no_market_price,
                "arb_edge": arb_edge,
                "guaranteed_profit": 1.0 - total,
            }
        return None

    def _rejected(
        self,
        prediction: EnsemblePrediction,
        side: str,
        entry_price: float,
        raw_edge: float,
        reason: str,
    ) -> EdgeSignal:
        return EdgeSignal(
            condition_id=prediction.condition_id,
            side=side,
            raw_edge=raw_edge,
            liquidity_adj_edge=raw_edge,
            spread_adj_edge=raw_edge,
            net_edge=0.0,
            entry_price=entry_price,
            model_prob=prediction.yes_probability,
            market_price=prediction.market_price,
            kelly_fraction=0.0,
            expected_value=0.0,
            confidence=prediction.confidence,
            uncertainty=prediction.uncertainty,
            is_tradeable=False,
            reject_reason=reason,
        )
