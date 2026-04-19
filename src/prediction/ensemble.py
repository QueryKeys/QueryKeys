"""
Ensemble predictor — combines Bayesian, ML, and LLM predictions into a
single well-calibrated probability estimate with uncertainty quantification.

Weighting scheme:
  - Static weights from config (tunable)
  - Dynamic weight adjustment based on recent calibration performance
    (Brier-score-weighted averaging)
  - Uncertainty quantification via bootstrap and inter-model disagreement
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.core.config import Settings
from src.core.logging import get_logger
from src.prediction.bayesian import BayesianPredictor
from src.prediction.calibration import ProbabilityCalibrator
from src.prediction.llm_predictor import LLMPredictor
from src.prediction.ml_models import (
    CatBoostPredictor,
    LightGBMPredictor,
    XGBoostPredictor,
)

log = get_logger(__name__)


@dataclass
class EnsemblePrediction:
    condition_id: str
    yes_probability: float          # final ensemble probability
    confidence: float               # model agreement / confidence
    uncertainty: float              # std across members
    edge: float                     # model_prob - market_price
    market_price: float

    # Per-model breakdown
    bayesian_prob: float = 0.5
    lgbm_prob: float = 0.5
    xgboost_prob: float = 0.5
    catboost_prob: float = 0.5
    llm_prob: float = 0.5

    llm_reasoning: str = ""
    llm_bull_case: str = ""
    llm_bear_case: str = ""
    key_factors: List[str] = field(default_factory=list)

    # Recommendation
    action: str = "HOLD"           # "BUY_YES" | "BUY_NO" | "HOLD"
    recommended_side: str = "NO_TRADE"


class PredictorEnsemble:
    """
    Top-level ensemble: orchestrates all sub-predictors and
    returns a final EnsemblePrediction.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._weights = settings.prediction.ensemble_weights.copy()
        self._min_edge = settings.prediction.min_edge
        self._min_confidence = settings.prediction.min_confidence
        self._max_uncertainty = settings.prediction.uncertainty_threshold

        # Sub-predictors
        self._bayesian = BayesianPredictor()
        self._lgbm = LightGBMPredictor(models_dir=settings.system.models_dir)
        self._xgboost = XGBoostPredictor(models_dir=settings.system.models_dir)
        self._catboost = CatBoostPredictor(models_dir=settings.system.models_dir)
        self._llm = LLMPredictor(settings)
        self._calibrator = ProbabilityCalibrator(
            method=settings.prediction.calibration_method,
            models_dir=settings.system.models_dir,
        )

        # Calibration-adjusted weights (updated periodically)
        self._dynamic_weights = dict(self._weights)

    async def init(self) -> None:
        await self._llm.init()
        log.info("ensemble.initialized")

    def load_models(self, feature_names: List[str]) -> None:
        """Load serialized ML models from disk."""
        self._lgbm.load_or_create(feature_names)
        self._xgboost.load_or_create(feature_names)
        self._catboost.load_or_create(feature_names)

    # ------------------------------------------------------------------
    # Main prediction entry point
    # ------------------------------------------------------------------

    async def predict(
        self,
        condition_id: str,
        market: Dict,
        features: Dict[str, float],
        feature_vector: "np.ndarray",
        market_price: float,
        orderbook: Optional[Dict] = None,
        analytics: Optional[Dict] = None,
        sentiment_score: float = 0.0,
        sentiment_confidence: float = 0.0,
        context: str = "",
    ) -> EnsemblePrediction:
        """Run all models and synthesize ensemble prediction."""
        dte = features.get("dte", 30.0)
        category = market.get("category", "Other")
        volume_24h = features.get("volume_24h", 0)
        volume_signal = features.get("trade_buy_ratio", 0.5)
        question = market.get("question", "")

        # 1. Bayesian
        bayes_pred = self._bayesian.predict(
            market_price=market_price,
            market_price_weight=5.0,
            sentiment_score=sentiment_score,
            sentiment_weight=1.0,
            volume_signal=volume_signal,
            volume_weight=0.5,
            dte_days=dte,
            historical_yes_rate=0.50,
            historical_count=10,
        )
        bayes_prob = self._calibrator.calibrate("bayesian", bayes_pred.mean)

        # 2. ML models (sync, wrapped)
        lgbm_pred = self._lgbm.make_prediction(feature_vector)
        xgb_pred = self._xgboost.make_prediction(feature_vector)
        cat_pred = self._catboost.make_prediction(feature_vector)

        lgbm_prob = self._calibrator.calibrate("lgbm", lgbm_pred.probability)
        xgb_prob = self._calibrator.calibrate("xgboost", xgb_pred.probability)
        cat_prob = self._calibrator.calibrate("catboost", cat_pred.probability)

        # 3. LLM (async)
        llm_pred = await self._llm.predict(
            question=question,
            market_price=market_price,
            volume_24h=volume_24h,
            dte_days=dte,
            category=category,
            sentiment_score=sentiment_score,
            sentiment_confidence=sentiment_confidence,
            context=context,
            base_rate=0.50,
        )
        llm_prob = self._calibrator.calibrate("llm", llm_pred.probability)

        # 4. Weighted ensemble
        w = self._dynamic_weights
        probs = {
            "bayesian": bayes_prob,
            "lgbm": lgbm_prob,
            "xgboost": xgb_prob,
            "catboost": cat_prob,
            "llm": llm_prob,
        }
        yes_prob = sum(probs[k] * w.get(k, 0) for k in probs)
        all_probs = list(probs.values())
        uncertainty = float(np.std(all_probs))

        # 5. Confidence: inter-model agreement weighted by individual confidences
        per_model_confidence = {
            "bayesian": min(1.0, bayes_pred.concentration / 20.0),
            "lgbm": lgbm_pred.confidence,
            "xgboost": xgb_pred.confidence,
            "catboost": cat_pred.confidence,
            "llm": llm_pred.confidence,
        }
        ensemble_confidence = sum(
            per_model_confidence[k] * w.get(k, 0) for k in per_model_confidence
        )
        # Penalize for high uncertainty
        ensemble_confidence *= max(0.0, 1.0 - uncertainty / 0.2)

        # 6. Edge detection
        edge = yes_prob - market_price

        # 7. Action recommendation
        action, side = self._recommend_action(
            yes_prob, market_price, edge, ensemble_confidence, uncertainty
        )

        log.info(
            "ensemble.prediction",
            condition_id=condition_id[:12],
            yes_prob=round(yes_prob, 4),
            market_price=round(market_price, 4),
            edge=round(edge, 4),
            uncertainty=round(uncertainty, 4),
            confidence=round(ensemble_confidence, 4),
            action=action,
        )

        return EnsemblePrediction(
            condition_id=condition_id,
            yes_probability=yes_prob,
            confidence=ensemble_confidence,
            uncertainty=uncertainty,
            edge=edge,
            market_price=market_price,
            bayesian_prob=bayes_prob,
            lgbm_prob=lgbm_prob,
            xgboost_prob=xgb_prob,
            catboost_prob=cat_prob,
            llm_prob=llm_prob,
            llm_reasoning=llm_pred.reasoning,
            llm_bull_case=llm_pred.bull_case,
            llm_bear_case=llm_pred.bear_case,
            key_factors=llm_pred.key_factors,
            action=action,
            recommended_side=side,
        )

    def _recommend_action(
        self,
        yes_prob: float,
        market_price: float,
        edge: float,
        confidence: float,
        uncertainty: float,
    ) -> Tuple[str, str]:
        if confidence < self._min_confidence:
            return "HOLD", "NO_TRADE"
        if uncertainty > self._max_uncertainty:
            return "HOLD", "NO_TRADE"

        abs_edge = abs(edge)
        if abs_edge < self._min_edge:
            return "HOLD", "NO_TRADE"

        if edge > 0:
            return "BUY_YES", "YES"
        else:
            return "BUY_NO", "NO"

    def update_dynamic_weights(self) -> None:
        """
        Adjust model weights based on recent Brier scores.
        Models with lower Brier scores get higher weight.
        Called periodically (e.g., after each batch of resolutions).
        """
        evals = self._calibrator.evaluate()
        if not evals:
            return

        # Inverse Brier score weighting
        inv_brier = {}
        for name, result in evals.items():
            if result.n_samples >= 10:
                inv_brier[name] = 1.0 / max(result.brier_score, 1e-6)

        if not inv_brier:
            return

        total = sum(inv_brier.values())
        model_map = {
            "bayesian": "bayesian",
            "lgbm": "lgbm",
            "xgboost": "xgboost",
            "catboost": "catboost",
            "llm": "llm",
        }

        # Blend 50/50 with static weights to avoid overfitting
        for key in self._weights:
            if key in inv_brier:
                dynamic = inv_brier[key] / total
                self._dynamic_weights[key] = 0.5 * self._weights[key] + 0.5 * dynamic

        # Renormalize
        total_w = sum(self._dynamic_weights.values())
        self._dynamic_weights = {k: v / total_w for k, v in self._dynamic_weights.items()}
        log.info("ensemble.weights_updated", weights=self._dynamic_weights)
