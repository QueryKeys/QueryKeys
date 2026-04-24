"""
BTC 5-Minute Candle Strategy for Polymarket.

Targets Polymarket markets like "Will BTC go UP in the next 5 minutes?"
Uses live Kraken OHLCV data (free, no API key needed) + technical indicators
calculated from historical 5-minute candles to decide direction.

Signals used:
  - RSI(14): overbought >70 → DOWN, oversold <30 → UP
  - EMA crossover (9/21): trend direction
  - Volume spike: confirms signal strength
  - Price momentum: last 3 candles directional agreement
  - Volatility filter: skip if ATR is too wide (noisy)
"""

from __future__ import annotations

import time
import urllib.request
import json
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.strategies.base import BaseStrategy

_CACHE: Dict[str, Any] = {}
_CACHE_TTL = 60  # seconds — refresh candles every 60s max


def _fetch_btc_candles(limit: int = 100) -> List[List[float]]:
    """Fetch BTC/USD 5-min OHLCV from Kraken. Returns list of [ts,o,h,l,c,v]."""
    cache_key = "btc_5m"
    now = time.time()
    if cache_key in _CACHE and now - _CACHE[cache_key]["ts"] < _CACHE_TTL:
        return _CACHE[cache_key]["data"]

    url = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=5"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "QueryKeys/1.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            raw = json.loads(r.read())
        candles = raw["result"]["XXBTZUSD"][-limit:]
        parsed = [
            [float(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[6])]
            for c in candles
        ]
        _CACHE[cache_key] = {"ts": now, "data": parsed}
        return parsed
    except Exception:
        return []


def _calc_rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 99.0
    rs = avg_gain / avg_loss
    return float(100 - 100 / (1 + rs))


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    alpha = 2.0 / (period + 1)
    ema = np.zeros_like(values)
    ema[0] = values[0]
    for i in range(1, len(values)):
        ema[i] = alpha * values[i] + (1 - alpha) * ema[i - 1]
    return ema


def _analyse_candles(candles: List[List[float]]) -> Dict[str, Any]:
    """Return a dict of technical signals from recent 5-min candles."""
    # Drop the last (still-forming) candle — its volume is partial
    candles = candles[:-1]
    if len(candles) < 30:
        return {"signal": "neutral", "strength": 0.0, "score": 0.0}

    closes  = np.array([c[4] for c in candles])
    highs   = np.array([c[2] for c in candles])
    lows    = np.array([c[3] for c in candles])
    volumes = np.array([c[5] for c in candles])

    # RSI
    rsi = _calc_rsi(closes)

    # EMA crossover
    ema9  = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    ema_bull = float(ema9[-1]) > float(ema21[-1])
    ema_cross_strength = abs(float(ema9[-1]) - float(ema21[-1])) / float(closes[-1])

    # Price momentum: last 3 candles all up or all down
    last3 = closes[-4:]
    momentum_up   = all(last3[i] < last3[i+1] for i in range(3))
    momentum_down = all(last3[i] > last3[i+1] for i in range(3))

    # Volume spike: current vol vs 20-candle average
    vol_avg = float(np.mean(volumes[-20:]))
    vol_spike = float(volumes[-1]) / max(vol_avg, 1e-9)

    # ATR (volatility) — 14-period
    tr = np.maximum(highs - lows, np.abs(highs - np.roll(closes, 1)),
                    np.abs(lows - np.roll(closes, 1)))
    atr = float(np.mean(tr[-14:]))
    atr_pct = atr / float(closes[-1])

    # Aggregate score: +1 per bullish signal, -1 per bearish
    score = 0.0
    if rsi < 35:
        score += 1.5
    elif rsi > 65:
        score -= 1.5
    if ema_bull:
        score += 1.0
    else:
        score -= 1.0
    if momentum_up:
        score += 1.5
    elif momentum_down:
        score -= 1.5
    if vol_spike > 1.8:
        score *= 1.2   # amplify conviction when volume confirms

    signal = "up" if score > 1.0 else "down" if score < -1.0 else "neutral"

    return {
        "signal": signal,
        "score": round(score, 2),
        "rsi": round(rsi, 1),
        "ema_bull": ema_bull,
        "ema_cross_pct": round(ema_cross_strength * 100, 3),
        "momentum_up": momentum_up,
        "momentum_down": momentum_down,
        "vol_spike": round(vol_spike, 2),
        "atr_pct": round(atr_pct * 100, 3),
        "last_close": round(float(closes[-1]), 2),
    }


class Btc5mStrategy(BaseStrategy):
    """
    Trade Polymarket BTC 5-minute up/down markets using Kraken live data.
    Only fires on markets whose question contains BTC/bitcoin + 5m/5-minute keywords.
    """

    @property
    def name(self) -> str:
        return "btc_5m"

    def _is_btc_5m_market(self, signal: Dict) -> bool:
        question = str(signal.get("question", "")).lower()
        cid      = str(signal.get("condition_id", "")).lower()
        slug     = str(signal.get("market_slug", "")).lower()
        category = str(signal.get("category", "")).lower()
        dte      = float(signal.get("dte_days", 999))

        # התאמה לפי שאלה מלאה
        btc_kw  = any(k in question for k in ["btc", "bitcoin"])
        time_kw = any(k in question for k in ["5m", "5 min", "5-min", "five min"])
        if btc_kw and time_kw:
            return True

        # התאמה לפי condition_id או slug
        if any(k in cid + slug for k in ["btc", "bitcoin", "xbt"]):
            return True

        # fallback: שוק קריפטו עם DTE קצר מאוד (< 1 שעה) = כנראה שוק 5 דקות
        if category == "crypto" and dte < (1 / 24):
            return True

        return False

    def should_trade(self, signal: Dict) -> bool:
        # Only BTC 5-minute markets
        if not self._is_btc_5m_market(signal):
            return False

        side = signal.get("side", "YES")
        min_strength = float(self.params.get("min_score_strength", 1.5))
        max_atr_pct  = float(self.params.get("max_atr_pct", 0.15))  # skip if too volatile
        min_vol_spike = float(self.params.get("min_vol_spike", 0.8))

        candles = _fetch_btc_candles(100)
        if not candles:
            return False

        analysis = _analyse_candles(candles)

        if analysis["signal"] == "neutral":
            return False
        if abs(analysis["score"]) < min_strength:
            return False
        if analysis["atr_pct"] > max_atr_pct:
            return False  # too noisy to trade
        if analysis["vol_spike"] < min_vol_spike:
            return False  # no volume confirmation

        # Match direction: signal=up → trade YES (price will go up)
        #                  signal=down → trade NO (price will go down → YES resolves NO)
        # The Polymarket question is "Will BTC go UP?" so YES=up, NO=down
        wants_up = analysis["signal"] == "up"
        if side == "YES" and wants_up:
            return True
        if side == "NO" and not wants_up:
            return True
        return False

    def size_override(self, signal: Dict, bankroll: float) -> Optional[float]:
        candles = _fetch_btc_candles(100)
        if not candles:
            return None
        analysis = _analyse_candles(candles)

        base_pct = float(self.params.get("base_position_pct", 0.04))
        max_pct  = float(self.params.get("max_position_pct", 0.08))

        # Scale with signal strength (score range ~1.5-4.5)
        strength_mult = min(abs(analysis.get("score", 1.5)) / 3.0, 1.5)
        pct = min(base_pct * strength_mult, max_pct)
        return bankroll * pct
