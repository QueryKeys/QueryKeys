"""
LLM-based probabilistic predictor using Anthropic Claude API.

Strategies:
  1. Structured probability elicitation with detailed reasoning chain
  2. Narrative extraction (what information asymmetry does the market miss?)
  3. Crowd psychology analysis (is the crowd over/under-reacting?)
  4. Historical analogy retrieval (what similar events resolved how?)
  5. Multi-turn debate (internally argues both sides, then synthesizes)

Uses prompt caching for efficiency on repeated similar market questions.
Falls back to OpenAI GPT-4 if Anthropic is unavailable.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from src.core.config import Settings
from src.core.exceptions import PredictionError
from src.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class LLMPrediction:
    probability: float
    confidence: float
    reasoning: str
    bull_case: str
    bear_case: str
    key_factors: List[str]
    model_used: str
    cached: bool = False
    tokens_used: int = 0


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an elite prediction market analyst with deep expertise in probabilistic \
reasoning, political science, economics, sports analytics, and crowd psychology. \
You have a track record of superior calibration in Polymarket and Metaculus-style \
markets. Your job is to output well-calibrated probability estimates with rigorous \
reasoning.

CRITICAL RULES:
1. Output ONLY valid JSON matching the schema below. No markdown, no prose outside JSON.
2. Probabilities must be between 0.01 and 0.99 — never 0 or 1.
3. Account for uncertainty, unknown unknowns, and base rates.
4. Consider whether the crowd price reflects all available information or has \
   systematic biases (overconfidence, recency bias, narrative bias).
5. Provide a balanced bull/bear case before synthesizing a final probability.

OUTPUT SCHEMA:
{
  "probability": <float 0.01-0.99>,
  "confidence": <float 0-1, your confidence in this estimate>,
  "bull_case": "<2-3 sentences: strongest case for YES>",
  "bear_case": "<2-3 sentences: strongest case for NO>",
  "key_factors": ["<factor 1>", "<factor 2>", "<factor 3>"],
  "reasoning": "<3-5 sentences: synthesis, base rates, information asymmetry>",
  "crowd_bias": "<overpriced|underpriced|fairly_priced>",
  "information_edge": "<what the crowd might be missing, if anything>"
}
"""

USER_PROMPT_TEMPLATE = """\
Market Question: {question}

Current Market Data:
- YES Price (probability implied by market): {market_price:.1%}
- 24h Volume: ${volume_24h:,.0f}
- Days to Expiry: {dte:.1f}
- Category: {category}

Recent Context:
{context}

Sentiment Signal: {sentiment_desc}

Historical Base Rate: approximately {base_rate:.1%} of similar markets resolve YES

Please analyze this market and provide your probability estimate.
"""


class LLMPredictor:
    """Claude-powered probabilistic prediction engine."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cache: Dict[str, Tuple[float, LLMPrediction]] = {}
        self._cache_ttl = settings.prediction.llm.cache_ttl
        self._client: Optional[Any] = None
        self._semaphore = asyncio.Semaphore(
            max(1, settings.rate_limits.llm_api_rpm // 10)
        )

    async def init(self) -> None:
        if not self._settings.groq_api_key:
            log.warning("llm_predictor.no_groq_key_llm_disabled")
            return
        try:
            import groq
            self._client = groq.AsyncGroq(
                api_key=self._settings.groq_api_key
            )
            log.info("llm_predictor.initialized", model=self._settings.prediction.llm.model)
        except ImportError:
            log.warning("llm_predictor.groq_not_installed")

    async def predict(
        self,
        question: str,
        market_price: float,
        volume_24h: float = 0,
        dte_days: float = 30,
        category: str = "Other",
        sentiment_score: float = 0.0,
        sentiment_confidence: float = 0.0,
        context: str = "",
        base_rate: float = 0.5,
    ) -> LLMPrediction:
        """Get LLM probability estimate with full reasoning."""
        if self._client is None:
            return self._fallback_prediction(market_price)

        cache_key = self._cache_key(question, market_price, context)
        if cache_key in self._cache:
            ts, cached = self._cache[cache_key]
            if time.time() - ts < self._cache_ttl:
                result = LLMPrediction(**{**cached.__dict__, "cached": True})
                return result

        async with self._semaphore:
            prediction = await self._call_claude(
                question=question,
                market_price=market_price,
                volume_24h=volume_24h,
                dte_days=dte_days,
                category=category,
                sentiment_score=sentiment_score,
                sentiment_confidence=sentiment_confidence,
                context=context,
                base_rate=base_rate,
            )
            self._cache[cache_key] = (time.time(), prediction)
            return prediction

    async def _call_claude(
        self,
        question: str,
        market_price: float,
        volume_24h: float,
        dte_days: float,
        category: str,
        sentiment_score: float,
        sentiment_confidence: float,
        context: str,
        base_rate: float,
    ) -> LLMPrediction:
        cfg = self._settings.prediction.llm

        sentiment_desc = self._format_sentiment(sentiment_score, sentiment_confidence)

        user_content = USER_PROMPT_TEMPLATE.format(
            question=question,
            market_price=market_price,
            volume_24h=volume_24h,
            dte=dte_days,
            category=category,
            context=context or "No additional context available.",
            sentiment_desc=sentiment_desc,
            base_rate=base_rate,
        )

        messages = [
            {"role": "user", "content": user_content},
        ]

        for attempt in range(3):
            try:
                response = await self._client.chat.completions.create(
                    model=cfg.model,
                    max_tokens=cfg.max_tokens,
                    temperature=cfg.temperature,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        *messages,
                    ],
                )
                raw_text = response.choices[0].message.content.strip()
                tokens_used = response.usage.total_tokens

                parsed = self._parse_response(raw_text, market_price)
                parsed.model_used = cfg.model
                parsed.tokens_used = tokens_used

                log.info(
                    "llm_predictor.prediction",
                    question=question[:60],
                    probability=parsed.probability,
                    market_price=market_price,
                    edge=parsed.probability - market_price,
                )
                return parsed

            except Exception as exc:
                log.warning(
                    "llm_predictor.call_failed",
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt * 3)
                else:
                    return self._fallback_prediction(market_price)

        return self._fallback_prediction(market_price)

    def _parse_response(self, raw: str, market_price: float) -> LLMPrediction:
        try:
            # Strip markdown code fences if present
            text = raw
            if "```" in text:
                lines = text.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                text = "\n".join(lines)
            data = json.loads(text)

            prob = float(data.get("probability", market_price))
            prob = max(0.01, min(0.99, prob))
            confidence = float(data.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))

            return LLMPrediction(
                probability=prob,
                confidence=confidence,
                reasoning=str(data.get("reasoning", "")),
                bull_case=str(data.get("bull_case", "")),
                bear_case=str(data.get("bear_case", "")),
                key_factors=[str(f) for f in data.get("key_factors", [])],
                model_used="",
            )
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            log.warning("llm_predictor.parse_error", error=str(exc), raw=raw[:200])
            return self._fallback_prediction(market_price)

    def _fallback_prediction(self, market_price: float) -> LLMPrediction:
        """Return a neutral prediction when LLM is unavailable."""
        return LLMPrediction(
            probability=market_price,
            confidence=0.1,
            reasoning="LLM unavailable — using market price as estimate",
            bull_case="",
            bear_case="",
            key_factors=[],
            model_used="fallback",
            cached=False,
        )

    @staticmethod
    def _format_sentiment(score: float, confidence: float) -> str:
        if confidence < 0.2:
            return "No significant sentiment signal"
        label = "positive" if score > 0.1 else "negative" if score < -0.1 else "neutral"
        strength = "strongly" if abs(score) > 0.5 else "mildly"
        return f"{strength.capitalize()} {label} (score={score:.2f}, confidence={confidence:.2f})"

    @staticmethod
    def _cache_key(question: str, market_price: float, context: str) -> str:
        h = hashlib.md5(f"{question}|{market_price:.2f}|{context[:200]}".encode())
        return h.hexdigest()
