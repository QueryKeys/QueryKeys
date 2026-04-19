"""
Sentiment analysis pipeline.

Sources:
  - NewsAPI (news articles)
  - Reddit (praw) via pushshift-compatible endpoints
  - Optional: Twitter/X via API v2

Outputs a composite sentiment score [-1, +1] per market question,
derived from VADER + keyword weighting.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from src.core.config import Settings
from src.core.logging import get_logger

log = get_logger(__name__)

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _VADER = SentimentIntensityAnalyzer()
    HAS_VADER = True
except ImportError:
    HAS_VADER = False
    log.warning("sentiment.vader_not_available")


@dataclass
class SentimentResult:
    query: str
    score: float        # composite: -1 (very negative) to +1 (very positive)
    confidence: float   # 0 to 1
    n_articles: int
    n_positive: int
    n_negative: int
    n_neutral: int
    sources: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


class SentimentAnalyzer:
    """Multi-source sentiment analyzer with caching."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._news_api_key = settings.news_api_key
        self._cache: Dict[str, Tuple[float, SentimentResult]] = {}
        self._cache_ttl = 3600   # 1 hour
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "SentimentAnalyzer":
        await self.init()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def init(self) -> None:
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20)
        )

    async def close(self) -> None:
        if self._session:
            await self._session.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def analyze(
        self,
        question: str,
        keywords: Optional[List[str]] = None,
    ) -> SentimentResult:
        cache_key = hashlib.md5(question.encode()).hexdigest()
        if cache_key in self._cache:
            ts, result = self._cache[cache_key]
            if time.time() - ts < self._cache_ttl:
                return result

        texts: List[str] = []
        sources: List[str] = []

        # Gather in parallel
        tasks = []
        if self._news_api_key and "newsapi" in self._settings.sentiment.sources:
            tasks.append(self._fetch_news(question, keywords))
        if "reddit" in self._settings.sentiment.sources:
            tasks.append(self._fetch_reddit(question, keywords))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                log.debug("sentiment.fetch_error", error=str(r))
                continue
            if isinstance(r, list):
                texts.extend(r)
                sources.append("fetched")

        result = self._score_texts(question, texts, sources)
        self._cache[cache_key] = (time.time(), result)
        return result

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_texts(
        self, query: str, texts: List[str], sources: List[str]
    ) -> SentimentResult:
        if not texts or not HAS_VADER:
            return SentimentResult(
                query=query,
                score=0.0,
                confidence=0.0,
                n_articles=0,
                n_positive=0,
                n_negative=0,
                n_neutral=0,
            )

        scores: List[float] = []
        n_pos = n_neg = n_neu = 0

        for text in texts:
            vs = _VADER.polarity_scores(text)
            compound = vs["compound"]
            scores.append(compound)
            if compound >= 0.05:
                n_pos += 1
            elif compound <= -0.05:
                n_neg += 1
            else:
                n_neu += 1

        n = len(scores)
        avg_score = sum(scores) / n
        std = (sum((s - avg_score) ** 2 for s in scores) / n) ** 0.5
        confidence = min(1.0, n / max(self._settings.sentiment.min_articles, 1)) * (
            1 - min(1.0, std)
        )

        return SentimentResult(
            query=query,
            score=avg_score,
            confidence=confidence,
            n_articles=n,
            n_positive=n_pos,
            n_negative=n_neg,
            n_neutral=n_neu,
            sources=sources,
        )

    # ------------------------------------------------------------------
    # Data fetchers
    # ------------------------------------------------------------------

    async def _fetch_news(
        self,
        query: str,
        keywords: Optional[List[str]] = None,
        page_size: int = 20,
    ) -> List[str]:
        if not self._session or not self._news_api_key:
            return []
        search_q = query
        if keywords:
            search_q = f"{query} {' OR '.join(keywords[:3])}"
        params = {
            "q": search_q[:500],
            "language": "en",
            "sortBy": "relevancy",
            "pageSize": page_size,
            "apiKey": self._news_api_key,
        }
        try:
            async with self._session.get(
                "https://newsapi.org/v2/everything", params=params
            ) as resp:
                data = await resp.json()
            texts = []
            for article in data.get("articles", []):
                parts = []
                if article.get("title"):
                    parts.append(article["title"])
                if article.get("description"):
                    parts.append(article["description"])
                if parts:
                    texts.append(" ".join(parts))
            return texts
        except Exception as exc:
            log.debug("sentiment.newsapi_error", error=str(exc))
            return []

    async def _fetch_reddit(
        self,
        query: str,
        keywords: Optional[List[str]] = None,
    ) -> List[str]:
        if not self._session:
            return []
        params = {
            "q": query[:200],
            "sort": "relevance",
            "limit": 25,
            "type": "link",
        }
        url = "https://www.reddit.com/search.json"
        headers = {"User-Agent": "QueryKeys/1.0"}
        try:
            async with self._session.get(url, params=params, headers=headers) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
            texts = []
            for post in data.get("data", {}).get("children", []):
                pd = post.get("data", {})
                title = pd.get("title", "")
                selftext = pd.get("selftext", "")[:300]
                if title:
                    texts.append(f"{title} {selftext}".strip())
            return texts
        except Exception as exc:
            log.debug("sentiment.reddit_error", error=str(exc))
            return []
