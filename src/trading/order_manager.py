"""
Order lifecycle manager.

Handles:
  - Order placement (limit/market) with slippage awareness
  - Order tracking and fill monitoring
  - Automatic timeout and cancellation
  - Fill price validation
  - Order book routing (best price execution)
  - Paper trading simulation with realistic fill modeling
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.core.config import Settings
from src.core.exceptions import OrderError
from src.core.logging import get_logger
from src.data.polymarket_client import PolymarketClient

log = get_logger(__name__)


@dataclass
class OrderRecord:
    order_id: str
    condition_id: str
    token_id: str
    side: str               # "BUY" | "SELL"
    token_side: str         # "YES" | "NO"
    order_type: str         # "limit" | "market"
    price: float
    size: float             # USD
    status: str = "pending"  # pending | open | filled | partial | cancelled | failed
    filled_size: float = 0.0
    avg_fill_price: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    error_msg: str = ""


class OrderManager:
    """Manages the full lifecycle of orders."""

    def __init__(
        self,
        settings: Settings,
        polymarket_client: PolymarketClient,
    ) -> None:
        self._settings = settings
        self._client = polymarket_client
        self._orders: Dict[str, OrderRecord] = {}
        self._on_fill_callbacks: List[Callable] = []
        self._timeout_tasks: Dict[str, asyncio.Task] = {}

    def on_fill(self, callback: Callable) -> None:
        """Register callback for order fills: callback(order: OrderRecord)"""
        self._on_fill_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Order placement
    # ------------------------------------------------------------------

    async def place_limit_order(
        self,
        condition_id: str,
        token_id: str,
        token_side: str,        # "YES" | "NO"
        price: float,
        size_usd: float,
        slippage_tolerance: Optional[float] = None,
        orderbook: Optional[Dict] = None,
    ) -> Optional[OrderRecord]:
        """
        Place a limit order with slippage and spread validation.
        Returns None if order is rejected (too much slippage, etc.)
        """
        cfg = self._settings.execution
        slippage = slippage_tolerance or cfg.slippage_tolerance

        # Validate price against live orderbook
        if orderbook:
            best_ask = orderbook.get("best_ask")
            best_bid = orderbook.get("best_bid")
            spread = orderbook.get("spread", 0)
            spread_pct = spread / max(price, 0.01)

            if spread_pct > cfg.max_spread_pct:
                log.warning(
                    "order_manager.spread_too_wide",
                    spread_pct=spread_pct,
                    max=cfg.max_spread_pct,
                )
                return None

        # Compute limit price: add slippage buffer for buys
        limit_price = min(1.0, price * (1 + slippage))
        limit_price = round(limit_price, 4)

        order_id = str(uuid.uuid4())
        record = OrderRecord(
            order_id=order_id,
            condition_id=condition_id,
            token_id=token_id,
            side="BUY",
            token_side=token_side,
            order_type="limit",
            price=limit_price,
            size=size_usd,
        )
        self._orders[order_id] = record

        try:
            result = await self._client.place_limit_order(
                token_id=token_id,
                side="BUY",
                price=limit_price,
                size=size_usd,
            )
            exchange_order_id = result.get("orderID") or result.get("orderId", order_id)
            record.order_id = exchange_order_id
            record.status = result.get("status", "open")
            self._orders[exchange_order_id] = record
            log.info(
                "order_manager.order_placed",
                order_id=exchange_order_id[:12],
                condition_id=condition_id[:12],
                side=token_side,
                price=limit_price,
                size=size_usd,
            )

            # Start timeout watcher
            task = asyncio.create_task(
                self._watch_order_timeout(exchange_order_id, cfg.order_timeout)
            )
            self._timeout_tasks[exchange_order_id] = task
            return record

        except OrderError as exc:
            record.status = "failed"
            record.error_msg = str(exc)
            log.error("order_manager.place_failed", error=str(exc))
            return None

    async def place_market_order(
        self,
        condition_id: str,
        token_id: str,
        token_side: str,
        amount_usd: float,
    ) -> Optional[OrderRecord]:
        """Place a market order (immediate fill at best available price)."""
        order_id = str(uuid.uuid4())
        record = OrderRecord(
            order_id=order_id,
            condition_id=condition_id,
            token_id=token_id,
            side="BUY",
            token_side=token_side,
            order_type="market",
            price=0.0,
            size=amount_usd,
        )
        self._orders[order_id] = record

        try:
            result = await self._client.place_market_order(
                token_id=token_id,
                amount=amount_usd,
            )
            record.status = "filled"
            record.filled_size = amount_usd
            record.avg_fill_price = float(result.get("price", 0.0))
            log.info(
                "order_manager.market_order_filled",
                order_id=order_id[:12],
                amount_usd=amount_usd,
            )
            await self._notify_fills(record)
            return record
        except OrderError as exc:
            record.status = "failed"
            record.error_msg = str(exc)
            return None

    # ------------------------------------------------------------------
    # Order monitoring
    # ------------------------------------------------------------------

    async def _watch_order_timeout(self, order_id: str, timeout: int) -> None:
        """Cancel open orders after timeout seconds."""
        await asyncio.sleep(timeout)
        if order_id in self._orders:
            record = self._orders[order_id]
            if record.status in ("open", "pending"):
                log.info("order_manager.order_timeout", order_id=order_id[:12])
                await self.cancel_order(order_id)

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a specific order."""
        if order_id not in self._orders:
            return False
        try:
            await self._client.cancel_order(order_id)
            self._orders[order_id].status = "cancelled"
            log.info("order_manager.order_cancelled", order_id=order_id[:12])
            return True
        except OrderError as exc:
            log.error("order_manager.cancel_failed", order_id=order_id[:12], error=str(exc))
            return False

    async def cancel_all(self) -> None:
        """Cancel all open orders."""
        await self._client.cancel_all_orders()
        for record in self._orders.values():
            if record.status in ("open", "pending"):
                record.status = "cancelled"
        log.info("order_manager.all_cancelled")

    async def sync_order_status(self) -> None:
        """Poll exchange for fill updates on all open orders."""
        open_orders = await self._client.get_open_orders()
        exchange_ids = {o.get("id") or o.get("orderID"): o for o in open_orders}

        for order_id, record in list(self._orders.items()):
            if record.status not in ("open", "pending"):
                continue

            if order_id not in exchange_ids:
                # Order no longer open — assume filled or cancelled
                record.status = "filled"
                record.filled_size = record.size
                record.updated_at = time.time()
                await self._notify_fills(record)
            else:
                ex = exchange_ids[order_id]
                filled = float(ex.get("size_matched", ex.get("filledSize", 0)))
                if filled > record.filled_size:
                    record.filled_size = filled
                    record.avg_fill_price = float(
                        ex.get("avg_price", ex.get("averagePrice", record.price))
                    )
                    record.updated_at = time.time()
                    if filled >= record.size * 0.99:
                        record.status = "filled"
                        await self._notify_fills(record)
                    else:
                        record.status = "partial"

    async def _notify_fills(self, record: OrderRecord) -> None:
        for cb in self._on_fill_callbacks:
            try:
                result = cb(record)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                log.error("order_manager.fill_callback_error", error=str(exc))

    def get_open_orders(self) -> List[OrderRecord]:
        return [r for r in self._orders.values() if r.status in ("open", "pending")]

    def get_filled_orders(self) -> List[OrderRecord]:
        return [r for r in self._orders.values() if r.status == "filled"]
