"""
Main Trader — the central orchestration engine.

Ties together:
  DataFetcher → FeatureEngineer → PredictorEnsemble → EdgeDetector
  → RiskManager → KellyCriterion → OrderManager → Database

Event-driven architecture:
  1. WebSocket price updates trigger re-evaluation
  2. Market scanner runs on schedule
  3. Orders are placed, tracked, and reconciled
  4. Portfolio state is updated in real-time
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import numpy as np

from src.core.config import Settings
from src.core.database import DatabaseManager, Order, Position, PortfolioSnapshot, Prediction as DbPrediction
from src.core.exceptions import CircuitBreakerOpen, RiskLimitExceeded
from src.core.logging import get_logger
from src.data.data_api import DataAPIClient
from src.data.gamma_api import GammaAPIClient
from src.data.polymarket_client import PolymarketClient
from src.data.sentiment import SentimentAnalyzer
from src.data.websocket_feed import WebSocketFeed
from src.features.engineer import FeatureEngineer
from src.prediction.edge_detector import EdgeDetector, EdgeSignal
from src.prediction.ensemble import PredictorEnsemble
from src.trading.hedger import Hedger
from src.trading.kelly import KellyCriterion
from src.trading.order_manager import OrderManager
from src.trading.risk_manager import RiskManager

log = get_logger(__name__)


class Trader:
    """Central trading orchestrator."""

    def __init__(
        self,
        settings: Settings,
        db: DatabaseManager,
        polymarket_client: PolymarketClient,
        gamma_api: GammaAPIClient,
        data_api: DataAPIClient,
        ws_feed: WebSocketFeed,
        sentiment: SentimentAnalyzer,
        ensemble: PredictorEnsemble,
        risk_manager: RiskManager,
    ) -> None:
        self._settings = settings
        self._db = db
        self._client = polymarket_client
        self._gamma = gamma_api
        self._data_api = data_api
        self._ws = ws_feed
        self._sentiment = sentiment
        self._ensemble = ensemble
        self._risk = risk_manager

        self._feature_eng = FeatureEngineer()
        self._kelly = KellyCriterion(
            kelly_fraction=settings.risk.kelly_fraction,
            min_kelly_edge=settings.risk.min_kelly_edge,
            max_fraction=settings.risk.max_single_market,
        )
        self._order_mgr = OrderManager(settings, polymarket_client)
        self._hedger = Hedger(settings)
        self._edge_detector = EdgeDetector(
            min_edge=settings.prediction.min_edge,
            min_confidence=settings.prediction.min_confidence,
            max_uncertainty=settings.prediction.uncertainty_threshold,
            max_spread_pct=settings.execution.max_spread_pct,
        )

        self._active_markets: Dict[str, Dict] = {}
        self._market_tokens: Dict[str, List[str]] = {}  # condition_id -> [yes_token, no_token]
        self._running = False
        self._scan_interval = settings.scanner.rescan_interval
        self._mode = settings.system.mode

        # Register fill callback
        self._order_mgr.on_fill(self._on_order_fill)
        # Register WS handler
        self._ws.on("price_change", self._on_price_update)
        self._ws.on("book", self._on_book_update)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start the trading loop."""
        self._running = True
        log.info("trader.starting", mode=self._mode)

        await self._ensemble.init()
        await self._initial_market_scan()

        # Concurrent tasks
        tasks = [
            asyncio.create_task(self._market_scanner_loop(), name="scanner"),
            asyncio.create_task(self._order_sync_loop(), name="order_sync"),
            asyncio.create_task(self._portfolio_snapshot_loop(), name="portfolio_snap"),
            asyncio.create_task(self._ws.start(), name="websocket"),
            asyncio.create_task(self._analysis_loop(), name="analysis"),
        ]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            log.info("trader.shutting_down")
        finally:
            await self._shutdown()

    async def stop(self) -> None:
        self._running = False
        await self._ws.stop()

    # ------------------------------------------------------------------
    # Market scanning
    # ------------------------------------------------------------------

    async def _initial_market_scan(self) -> None:
        log.info("trader.initial_scan_starting")
        await self._scan_markets()

    async def _market_scanner_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._scan_interval)
            await self._scan_markets()

    async def _scan_markets(self) -> None:
        try:
            cfg = self._settings.scanner
            markets = await self._gamma.scan_markets(
                min_volume=cfg.min_volume_24h,
                min_liquidity=cfg.min_liquidity,
                min_days=cfg.min_days_to_expiry,
                max_days=cfg.max_days_to_expiry,
                categories=cfg.categories or None,
                max_results=cfg.max_markets,
            )

            new_markets = 0
            for market in markets:
                cid = market.get("conditionId") or market.get("condition_id", "")
                if not cid:
                    continue
                if cid not in self._active_markets:
                    new_markets += 1
                    # Subscribe to WS for YES token
                    tokens = market.get("clobTokenIds", [])
                    for tok in tokens:
                        if tok:
                            await self._ws.subscribe_live(tok)
                            self._market_tokens.setdefault(cid, []).append(tok)
                self._active_markets[cid] = market

            log.info("trader.scan_complete", total=len(markets), new=new_markets)
        except Exception as exc:
            log.error("trader.scan_error", error=str(exc))

    # ------------------------------------------------------------------
    # Core analysis loop
    # ------------------------------------------------------------------

    async def _analysis_loop(self) -> None:
        """Periodically analyze all active markets for trading opportunities."""
        while self._running:
            try:
                await self._analyze_all_markets()
            except Exception as exc:
                log.error("trader.analysis_error", error=str(exc))
            await asyncio.sleep(60)  # Analyze every 60 seconds

    async def _analyze_all_markets(self) -> None:
        semaphore = asyncio.Semaphore(5)  # Limit concurrency

        async def analyze_one(cid: str, market: Dict) -> None:
            async with semaphore:
                await self._analyze_market(cid, market)

        tasks = [
            asyncio.create_task(analyze_one(cid, m))
            for cid, m in list(self._active_markets.items())
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _analyze_market(self, condition_id: str, market: Dict) -> None:
        try:
            tokens = self._market_tokens.get(condition_id, [])
            yes_token = tokens[0] if tokens else None
            if not yes_token:
                return

            # Fetch current data
            orderbook = self._ws.get_orderbook(yes_token)
            ob_dict = orderbook.to_dict() if orderbook else {}
            midpoint = ob_dict.get("midpoint") or 0.5

            if midpoint <= 0.01 or midpoint >= 0.99:
                return

            # Price history
            price_history = await self._data_api.get_price_history(
                market_id=yes_token, interval="1h", fidelity=60
            )
            # Analytics
            analytics = await self._data_api.get_market_analytics(condition_id)
            # Sentiment
            question = market.get("question", "")
            sentiment = await self._sentiment.analyze(question)

            # Feature engineering
            features = self._feature_eng.extract(
                market=market,
                orderbook=ob_dict,
                price_history=price_history,
                analytics=analytics,
                sentiment_score=sentiment.score,
                sentiment_confidence=sentiment.confidence,
            )
            feature_names, feature_values = self._feature_eng.to_vector(features)
            feature_vector = np.array(feature_values, dtype=np.float32)

            # Ensemble prediction
            prediction = await self._ensemble.predict(
                condition_id=condition_id,
                market=market,
                features=features,
                feature_vector=feature_vector,
                market_price=midpoint,
                orderbook=ob_dict,
                analytics=analytics,
                sentiment_score=sentiment.score,
                sentiment_confidence=sentiment.confidence,
                context=sentiment.query,
            )

            # Edge detection
            signal = self._edge_detector.evaluate(
                prediction=prediction,
                orderbook=ob_dict,
                analytics=analytics,
            )

            if signal and signal.is_tradeable:
                await self._execute_signal(signal, market, ob_dict)

            # Persist prediction to DB
            await self._save_prediction(condition_id, prediction, midpoint)

        except CircuitBreakerOpen as exc:
            log.warning("trader.circuit_breaker", error=str(exc))
        except Exception as exc:
            log.error("trader.analyze_market_error", condition_id=condition_id[:12], error=str(exc))

    # ------------------------------------------------------------------
    # Trade execution
    # ------------------------------------------------------------------

    async def _execute_signal(
        self,
        signal: EdgeSignal,
        market: Dict,
        orderbook: Dict,
    ) -> None:
        tokens = self._market_tokens.get(signal.condition_id, [])
        yes_token = tokens[0] if tokens else None
        no_token = tokens[1] if len(tokens) > 1 else None

        if signal.side == "YES" and not yes_token:
            return
        if signal.side == "NO" and not no_token:
            return

        token_id = yes_token if signal.side == "YES" else no_token
        category = market.get("category", "Other")

        # Kelly sizing
        kelly_result = self._kelly.compute(
            model_prob=signal.model_prob,
            entry_price=signal.entry_price,
            side=signal.side,
            bankroll=self._risk.bankroll,
            uncertainty=signal.uncertainty,
        )

        if kelly_result.adjusted_fraction <= 0:
            return

        requested_size = kelly_result.bet_size_usd

        # Risk check
        try:
            risk_result = self._risk.check_new_position(
                condition_id=signal.condition_id,
                category=category,
                side=signal.side,
                requested_size_usd=requested_size,
            )
        except CircuitBreakerOpen as exc:
            log.warning("trader.blocked_by_risk", reason=str(exc))
            return

        if not risk_result.allowed:
            log.info(
                "trader.position_rejected",
                condition_id=signal.condition_id[:12],
                reason=risk_result.reason,
            )
            return

        final_size = risk_result.adjusted_size_usd

        log.info(
            "trader.executing_trade",
            condition_id=signal.condition_id[:12],
            side=signal.side,
            edge=round(signal.net_edge, 4),
            size_usd=round(final_size, 2),
            kelly_pct=round(kelly_result.adjusted_fraction, 4),
        )

        order = await self._order_mgr.place_limit_order(
            condition_id=signal.condition_id,
            token_id=token_id,
            token_side=signal.side,
            price=signal.entry_price,
            size_usd=final_size,
            orderbook=orderbook,
        )

        if order:
            self._risk.record_position_opened(
                condition_id=signal.condition_id,
                category=category,
                side=signal.side,
                size_usd=final_size,
                entry_price=signal.entry_price,
            )
            await self._save_order(order, signal)

    # ------------------------------------------------------------------
    # WebSocket event handlers
    # ------------------------------------------------------------------

    async def _on_price_update(self, event_type: str, event: Dict) -> None:
        """Handle real-time price updates from WebSocket."""
        asset_id = event.get("asset_id", "")
        ob = event.get("_orderbook", {})
        midpoint = ob.get("midpoint")
        if midpoint and self._risk:
            # Find condition_id for this token
            for cid, tokens in self._market_tokens.items():
                if asset_id in tokens:
                    self._risk.update_prices({cid: float(midpoint)})
                    break

    async def _on_book_update(self, event_type: str, event: Dict) -> None:
        """Handle full orderbook updates — trigger re-analysis if significant change."""
        pass  # Analysis loop handles re-evaluation periodically

    # ------------------------------------------------------------------
    # Order fill handler
    # ------------------------------------------------------------------

    async def _on_order_fill(self, order: Any) -> None:
        log.info(
            "trader.order_filled",
            order_id=str(order.order_id)[:12],
            size=order.filled_size,
            price=order.avg_fill_price,
        )

    # ------------------------------------------------------------------
    # Maintenance loops
    # ------------------------------------------------------------------

    async def _order_sync_loop(self) -> None:
        while self._running:
            await asyncio.sleep(30)
            try:
                await self._order_mgr.sync_order_status()
            except Exception as exc:
                log.error("trader.order_sync_error", error=str(exc))

    async def _portfolio_snapshot_loop(self) -> None:
        while self._running:
            await asyncio.sleep(300)  # every 5 min
            try:
                summary = self._risk.get_portfolio_summary()
                async with self._db.session() as sess:
                    snap = PortfolioSnapshot(**{
                        k: summary[k]
                        for k in [
                            "total_value", "cash", "invested",
                            "unrealized_pnl", "daily_pnl",
                            "drawdown",
                        ]
                        if k in summary
                    })
                    snap.num_open_positions = summary.get("num_positions", 0)
                    snap.realized_pnl = summary.get("total_pnl", 0)
                    sess.add(snap)
                    await sess.commit()
            except Exception as exc:
                log.error("trader.snapshot_error", error=str(exc))

    # ------------------------------------------------------------------
    # DB persistence helpers
    # ------------------------------------------------------------------

    async def _save_prediction(self, condition_id: str, prediction: Any, market_price: float) -> None:
        try:
            async with self._db.session() as sess:
                pred = DbPrediction(
                    condition_id=condition_id,
                    model_name="ensemble",
                    yes_probability=prediction.yes_probability,
                    confidence=prediction.confidence,
                    uncertainty=prediction.uncertainty,
                    edge=prediction.edge,
                    market_price=market_price,
                )
                sess.add(pred)
                await sess.commit()
        except Exception as exc:
            log.debug("trader.save_prediction_error", error=str(exc))

    async def _save_order(self, order: Any, signal: EdgeSignal) -> None:
        try:
            async with self._db.session() as sess:
                db_order = DbOrder(
                    order_id=order.order_id,
                    condition_id=order.condition_id,
                    token_id=order.token_id,
                    side=order.token_side,
                    order_type=order.order_type,
                    price=order.price,
                    size=order.size,
                    status=order.status,
                )
                sess.add(db_order)
                await sess.commit()
        except Exception as exc:
            log.debug("trader.save_order_error", error=str(exc))

    async def _shutdown(self) -> None:
        log.info("trader.shutdown_cancel_all_orders")
        await self._order_mgr.cancel_all()
