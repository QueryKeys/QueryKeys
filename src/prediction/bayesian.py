"""
Bayesian inference model for prediction market probabilities.

Uses a Beta-Binomial conjugate model updated with:
  1. Prior from base rates (historical resolution patterns)
  2. Likelihood from price signal (market price as evidence)
  3. Likelihood from sentiment signal
  4. Decay weighting based on time-to-expiry

Outputs posterior mean + 95% credible interval.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from scipy import stats


@dataclass
class BayesianPrediction:
    mean: float
    lower: float
    upper: float
    concentration: float   # alpha + beta (effective sample size)
    alpha: float
    beta: float


class BayesianPredictor:
    """
    Beta-Binomial Bayesian predictor.

    Prior: Beta(alpha0, beta0) ~ Uniform(0.5, 0.5) by default.
    Updates from multiple evidence sources are multiplicative in likelihood.
    """

    def __init__(
        self,
        prior_alpha: float = 1.0,
        prior_beta: float = 1.0,
    ) -> None:
        self._prior_alpha = prior_alpha
        self._prior_beta = prior_beta

    def predict(
        self,
        market_price: float,
        market_price_weight: float = 5.0,
        sentiment_score: float = 0.0,
        sentiment_weight: float = 1.0,
        volume_signal: float = 0.5,
        volume_weight: float = 1.0,
        dte_days: float = 30.0,
        historical_yes_rate: float = 0.5,
        historical_count: int = 10,
    ) -> BayesianPrediction:
        """
        Compute posterior Beta distribution by combining all evidence.

        market_price:         current market midpoint [0,1]
        market_price_weight:  pseudo-count weight for price signal
        sentiment_score:      [-1, 1] from sentiment analyzer
        sentiment_weight:     pseudo-count weight for sentiment
        volume_signal:        volume-implied direction [0,1]
        dte_days:             days to expiry (used for decay)
        historical_yes_rate:  base rate for YES resolution in this category
        historical_count:     historical N for prior strength
        """
        # Incorporate historical base rate as prior
        alpha = self._prior_alpha + historical_yes_rate * historical_count
        beta_ = self._prior_beta + (1 - historical_yes_rate) * historical_count

        # Time-decay: closer to expiry → price signal is more reliable
        time_decay = 1.0 + math.exp(-dte_days / 30.0)  # 1 to 2

        # Price signal (treat market price as evidence with pseudo-counts)
        effective_price_weight = market_price_weight * time_decay
        alpha += market_price * effective_price_weight
        beta_ += (1 - market_price) * effective_price_weight

        # Sentiment signal (normalise from [-1,1] to [0,1])
        sent_prob = (sentiment_score + 1.0) / 2.0
        alpha += sent_prob * sentiment_weight
        beta_ += (1 - sent_prob) * sentiment_weight

        # Volume signal
        alpha += volume_signal * volume_weight
        beta_ += (1 - volume_signal) * volume_weight

        # Posterior statistics
        posterior_mean = alpha / (alpha + beta_)
        # 95% credible interval
        lower = float(stats.beta.ppf(0.025, alpha, beta_))
        upper = float(stats.beta.ppf(0.975, alpha, beta_))

        return BayesianPrediction(
            mean=float(posterior_mean),
            lower=lower,
            upper=upper,
            concentration=float(alpha + beta_),
            alpha=float(alpha),
            beta=float(beta_),
        )

    def update_from_resolution(
        self,
        resolved_yes: bool,
        current_alpha: float,
        current_beta: float,
    ) -> Tuple[float, float]:
        """Online update after market resolution — for model tracking."""
        if resolved_yes:
            return current_alpha + 1.0, current_beta
        else:
            return current_alpha, current_beta + 1.0

    def brier_contribution(
        self, predicted_prob: float, actual_outcome: float
    ) -> float:
        """Per-prediction Brier score (lower is better, 0 = perfect)."""
        return (predicted_prob - actual_outcome) ** 2

    def log_score(
        self, predicted_prob: float, actual_outcome: float, epsilon: float = 1e-10
    ) -> float:
        """Log-proper scoring rule (higher is better)."""
        p = max(epsilon, min(1 - epsilon, predicted_prob))
        if actual_outcome == 1.0:
            return math.log(p)
        return math.log(1 - p)
