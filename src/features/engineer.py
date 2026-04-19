"""
Feature engineering pipeline.

Produces a unified feature vector for each market from:
  1. Orderbook microstructure (bid/ask depth, spread, imbalance)
  2. Price time-series (momentum, volatility, mean-reversion signals)
  3. Volume & liquidity metrics
  4. Market meta-features (days-to-expiry, category encoding)
  5. Sentiment scores
  6. Historical calibration residuals

All features are normalised to [0,1] or z-scored where appropriate.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.core.logging import get_logger

log = get_logger(__name__)


class FeatureEngineer:
    """Stateless feature extractor — call extract() with raw data."""

    # Categorical encoding maps
    CATEGORY_MAP: Dict[str, int] = {
        "Politics": 0,
        "Sports": 1,
        "Crypto": 2,
        "Economics": 3,
        "Science": 4,
        "Entertainment": 5,
        "Other": 6,
    }

    def extract(
        self,
        market: Dict,
        orderbook: Optional[Dict],
        price_history: List[Dict],
        analytics: Dict,
        sentiment_score: float = 0.0,
        sentiment_confidence: float = 0.0,
    ) -> Dict[str, float]:
        """
        Extract all features for a single market snapshot.
        Returns a flat dict of feature_name -> float.
        """
        features: Dict[str, float] = {}

        features.update(self._meta_features(market))
        features.update(self._orderbook_features(orderbook))
        features.update(self._price_history_features(price_history))
        features.update(self._volume_features(analytics))
        features.update(self._sentiment_features(sentiment_score, sentiment_confidence))

        return features

    # ------------------------------------------------------------------
    # Meta features
    # ------------------------------------------------------------------

    def _meta_features(self, market: Dict) -> Dict[str, float]:
        now = datetime.now(timezone.utc)
        features: Dict[str, float] = {}

        # Days to expiry (log-scaled)
        end_raw = market.get("endDate") or market.get("end_date_iso")
        if end_raw:
            try:
                if isinstance(end_raw, str):
                    end_dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
                else:
                    end_dt = datetime.fromtimestamp(end_raw, tz=timezone.utc)
                dte = max(0.0, (end_dt - now).total_seconds() / 86400)
                features["dte"] = dte
                features["dte_log"] = math.log1p(dte)
                features["dte_inv"] = 1.0 / (dte + 1.0)
            except (ValueError, TypeError):
                features["dte"] = 30.0
                features["dte_log"] = math.log1p(30.0)
                features["dte_inv"] = 1.0 / 31.0

        # Category one-hot
        category = market.get("category", "Other")
        cat_id = self.CATEGORY_MAP.get(category, 6)
        for i in range(7):
            features[f"cat_{i}"] = 1.0 if i == cat_id else 0.0

        # Market creation age (days)
        created_raw = market.get("createdAt") or market.get("created_at")
        if created_raw:
            try:
                if isinstance(created_raw, str):
                    created_dt = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
                else:
                    created_dt = datetime.fromtimestamp(created_raw, tz=timezone.utc)
                age = max(0.0, (now - created_dt).total_seconds() / 86400)
                features["market_age_days"] = age
                features["market_age_log"] = math.log1p(age)
            except (ValueError, TypeError):
                features["market_age_days"] = 0.0
                features["market_age_log"] = 0.0

        return features

    # ------------------------------------------------------------------
    # Orderbook features
    # ------------------------------------------------------------------

    def _orderbook_features(self, ob: Optional[Dict]) -> Dict[str, float]:
        features: Dict[str, float] = {}
        if not ob:
            return {
                "spread": 0.05,
                "spread_pct": 0.1,
                "midpoint": 0.5,
                "bid_depth": 0.0,
                "ask_depth": 0.0,
                "book_imbalance": 0.0,
                "best_bid": 0.45,
                "best_ask": 0.55,
                "bid_ask_skew": 0.0,
            }

        best_bid = ob.get("best_bid") or 0.0
        best_ask = ob.get("best_ask") or 1.0
        midpoint = ob.get("midpoint") or 0.5
        spread = ob.get("spread") or (best_ask - best_bid)

        features["best_bid"] = float(best_bid)
        features["best_ask"] = float(best_ask)
        features["midpoint"] = float(midpoint)
        features["spread"] = float(spread)
        features["spread_pct"] = float(spread) / max(midpoint, 0.01)

        # Book depth imbalance: (bid_vol - ask_vol) / (bid_vol + ask_vol)
        bids = ob.get("bids", {})
        asks = ob.get("asks", {})
        if isinstance(bids, dict):
            bid_vol = float(sum(bids.values()))
            ask_vol = float(sum(asks.values()))
        else:
            bid_vol = ask_vol = 0.0

        total_vol = bid_vol + ask_vol
        imbalance = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0.0
        features["bid_depth"] = bid_vol
        features["ask_depth"] = ask_vol
        features["book_imbalance"] = imbalance

        # Bid-ask skew (weighted average distance from mid)
        if isinstance(bids, dict) and bids and midpoint:
            weighted_bid = sum(p * s for p, s in bids.items()) / max(bid_vol, 1e-9)
            features["bid_ask_skew"] = (weighted_bid - midpoint) / max(midpoint, 0.01)
        else:
            features["bid_ask_skew"] = 0.0

        return features

    # ------------------------------------------------------------------
    # Price time-series features
    # ------------------------------------------------------------------

    def _price_history_features(self, history: List[Dict]) -> Dict[str, float]:
        features: Dict[str, float] = {}

        if not history or len(history) < 2:
            return {
                "price_change_1h": 0.0,
                "price_change_6h": 0.0,
                "price_change_24h": 0.0,
                "price_volatility": 0.05,
                "price_momentum": 0.0,
                "rsi_14": 50.0,
                "price_ma_ratio": 1.0,
                "price_mean_reversion": 0.0,
            }

        prices = [float(c.get("p", c.get("close", 0.5))) for c in history]
        prices = [p for p in prices if 0 < p < 1]

        if not prices:
            return self._price_history_features([])

        current = prices[-1]

        # Changes over lookback windows
        def pct_change(lookback: int) -> float:
            if len(prices) > lookback:
                ref = prices[-lookback - 1]
                return (current - ref) / max(ref, 0.01)
            return 0.0

        features["price_change_1h"] = pct_change(1)
        features["price_change_6h"] = pct_change(6)
        features["price_change_24h"] = pct_change(24)

        # Volatility (std of log returns)
        if len(prices) >= 2:
            log_rets = [
                math.log(prices[i] / prices[i - 1])
                for i in range(1, len(prices))
                if prices[i - 1] > 0 and prices[i] > 0
            ]
            features["price_volatility"] = float(np.std(log_rets)) if log_rets else 0.05
        else:
            features["price_volatility"] = 0.05

        # Momentum (z-score of recent return vs historical)
        window = min(24, len(prices) - 1)
        if window > 2:
            recent_rets = [
                prices[i] - prices[i - 1] for i in range(max(1, len(prices) - window), len(prices))
            ]
            mean_ret = np.mean(recent_rets)
            std_ret = np.std(recent_rets) + 1e-9
            features["price_momentum"] = float(mean_ret / std_ret)
        else:
            features["price_momentum"] = 0.0

        # RSI(14)
        features["rsi_14"] = self._rsi(prices, period=14)

        # Price vs moving average ratio
        ma_window = min(20, len(prices))
        ma = np.mean(prices[-ma_window:])
        features["price_ma_ratio"] = current / max(ma, 0.01)

        # Mean reversion z-score
        if len(prices) >= 5:
            hist_mean = np.mean(prices)
            hist_std = np.std(prices) + 1e-9
            features["price_mean_reversion"] = (current - hist_mean) / hist_std
        else:
            features["price_mean_reversion"] = 0.0

        return features

    def _rsi(self, prices: List[float], period: int = 14) -> float:
        if len(prices) < period + 1:
            return 50.0
        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains = [max(d, 0) for d in deltas[-period:]]
        losses = [abs(min(d, 0)) for d in deltas[-period:]]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    # ------------------------------------------------------------------
    # Volume & liquidity features
    # ------------------------------------------------------------------

    def _volume_features(self, analytics: Dict) -> Dict[str, float]:
        features: Dict[str, float] = {}
        volume = analytics.get("volume", {})
        oi = analytics.get("open_interest", {})
        trades = analytics.get("recent_trades", [])

        vol_24h = float(volume.get("volume24hr", volume.get("volume_24h", 0)) or 0)
        vol_total = float(volume.get("volume", 0) or 0)
        oi_val = float(oi.get("openInterest", oi.get("open_interest", 0)) or 0)

        features["volume_24h"] = vol_24h
        features["volume_24h_log"] = math.log1p(vol_24h)
        features["volume_total_log"] = math.log1p(vol_total)
        features["open_interest_log"] = math.log1p(oi_val)

        # Trade activity metrics
        if trades:
            sizes = [float(t.get("size", 0)) for t in trades if t.get("size")]
            prices = [float(t.get("price", 0)) for t in trades if t.get("price")]
            features["trade_count_recent"] = float(len(trades))
            features["avg_trade_size"] = float(np.mean(sizes)) if sizes else 0.0
            features["trade_size_std"] = float(np.std(sizes)) if sizes else 0.0
            # Buy-sell imbalance from trades
            buys = sum(1 for t in trades if t.get("side") in ("BUY", "buy"))
            features["trade_buy_ratio"] = buys / max(len(trades), 1)
        else:
            features["trade_count_recent"] = 0.0
            features["avg_trade_size"] = 0.0
            features["trade_size_std"] = 0.0
            features["trade_buy_ratio"] = 0.5

        return features

    # ------------------------------------------------------------------
    # Sentiment features
    # ------------------------------------------------------------------

    def _sentiment_features(
        self, score: float, confidence: float
    ) -> Dict[str, float]:
        # Score: -1 to +1; convert to 0-1 range for easier ML consumption
        return {
            "sentiment_score": score,
            "sentiment_score_norm": (score + 1.0) / 2.0,
            "sentiment_confidence": confidence,
            "sentiment_signal": score * confidence,  # combined signal
        }

    # ------------------------------------------------------------------
    # Feature vector utilities
    # ------------------------------------------------------------------

    def to_vector(self, features: Dict[str, float]) -> Tuple[List[str], List[float]]:
        """Return sorted (names, values) arrays for ML models."""
        sorted_items = sorted(features.items())
        names = [k for k, _ in sorted_items]
        values = [v for _, v in sorted_items]
        return names, values

    def to_numpy(self, features: Dict[str, float]) -> np.ndarray:
        _, values = self.to_vector(features)
        return np.array(values, dtype=np.float32)
