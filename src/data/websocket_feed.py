"""
Real-time WebSocket feed for Polymarket CLOB.

Subscribes to:
  - price_change (midpoint/spread updates)
  - book (full orderbook snapshots + incremental updates)
  - last_trade_price
  - market_closed

Reconnects automatically with exponential backoff.
Dispatches events to registered async handlers.
"""

from __future__ import annotations

import asyncio
import json
import ssl
import time
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Set

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = None

from src.core.config import Settings
from src.core.logging import get_logger

log = get_logger(__name__)

# Handler type: async (event_type: str, data: Dict) -> None
HandlerFn = Callable[[str, Dict], Any]


class OrderbookState:
    """Maintains local orderbook state for a single token."""

    def __init__(self) -> None:
        self.bids: Dict[float, float] = {}   # price -> size
        self.asks: Dict[float, float] = {}
        self.last_updated: float = 0.0

    def apply_update(self, changes: List[Dict]) -> None:
        for change in changes:
            price = float(change["price"])
            size = float(change["size"])
            side = change.get("side", "")
            if side.upper() in ("BUY", "BID"):
                if size == 0:
                    self.bids.pop(price, None)
                else:
                    self.bids[price] = size
            else:
                if size == 0:
                    self.asks.pop(price, None)
                else:
                    self.asks[price] = size
        self.last_updated = time.monotonic()

    @property
    def best_bid(self) -> Optional[float]:
        return max(self.bids) if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return min(self.asks) if self.asks else None

    @property
    def midpoint(self) -> Optional[float]:
        bb, ba = self.best_bid, self.best_ask
        if bb is not None and ba is not None:
            return (bb + ba) / 2
        return None

    @property
    def spread(self) -> Optional[float]:
        bb, ba = self.best_bid, self.best_ask
        if bb is not None and ba is not None:
            return ba - bb
        return None

    def to_dict(self) -> Dict:
        return {
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "midpoint": self.midpoint,
            "spread": self.spread,
            "bids": dict(sorted(self.bids.items(), reverse=True)[:10]),
            "asks": dict(sorted(self.asks.items())[:10]),
            "last_updated": self.last_updated,
        }


class WebSocketFeed:
    """
    Manages persistent WebSocket connection to Polymarket CLOB.
    All handlers are called in the asyncio event loop.
    """

    def __init__(self, settings: Settings) -> None:
        self._ws_url = settings.websocket.clob_ws_url
        self._reconnect_delay = settings.websocket.reconnect_delay
        self._ping_interval = settings.websocket.ping_interval
        self._max_reconnects = settings.websocket.max_reconnects
        self._subscribed_tokens: Set[str] = set()
        self._handlers: Dict[str, List[HandlerFn]] = defaultdict(list)
        self._orderbooks: Dict[str, OrderbookState] = {}
        self._running = False
        self._ws: Optional[Any] = None
        self._reconnect_count = 0

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    def subscribe_token(self, token_id: str) -> None:
        self._subscribed_tokens.add(token_id)
        if token_id not in self._orderbooks:
            self._orderbooks[token_id] = OrderbookState()

    def unsubscribe_token(self, token_id: str) -> None:
        self._subscribed_tokens.discard(token_id)

    def on(self, event_type: str, handler: HandlerFn) -> None:
        """Register an async handler for a given event type."""
        self._handlers[event_type].append(handler)

    def get_orderbook(self, token_id: str) -> Optional[OrderbookState]:
        return self._orderbooks.get(token_id)

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        while self._running:
            try:
                await self._connect_and_run()
            except Exception as exc:
                self._reconnect_count += 1
                if self._reconnect_count > self._max_reconnects:
                    log.error("websocket.max_reconnects_exceeded", count=self._reconnect_count)
                    raise
                delay = min(
                    self._reconnect_delay * (2 ** (self._reconnect_count - 1)), 120
                )
                log.warning(
                    "websocket.reconnecting",
                    error=str(exc),
                    delay=delay,
                    attempt=self._reconnect_count,
                )
                await asyncio.sleep(delay)

    async def stop(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()

    async def _connect_and_run(self) -> None:
        log.info("websocket.connecting", url=self._ws_url)
        async with websockets.connect(
            self._ws_url + "market",
            ping_interval=self._ping_interval,
            ping_timeout=20,
            max_size=10 * 1024 * 1024,
            ssl=_SSL_CONTEXT,
        ) as ws:
            self._ws = ws
            self._reconnect_count = 0
            log.info("websocket.connected")

            await self._subscribe_all(ws)

            async for raw in ws:
                if not self._running:
                    break
                try:
                    events = json.loads(raw)
                    if not isinstance(events, list):
                        events = [events]
                    for event in events:
                        await self._dispatch(event)
                except json.JSONDecodeError:
                    log.debug("websocket.bad_json", raw=raw[:200])

    async def _subscribe_all(self, ws: Any) -> None:
        if not self._subscribed_tokens:
            return
        msg = {
            "type": "subscribe",
            "assets_ids": list(self._subscribed_tokens),
        }
        await ws.send(json.dumps(msg))
        log.info("websocket.subscribed", tokens=len(self._subscribed_tokens))

    async def subscribe_live(self, token_id: str) -> None:
        """Subscribe to a new token on a live connection."""
        self.subscribe_token(token_id)
        if self._ws:
            msg = {"type": "subscribe", "assets_ids": [token_id]}
            await self._ws.send(json.dumps(msg))

    # ------------------------------------------------------------------
    # Event dispatch
    # ------------------------------------------------------------------

    async def _dispatch(self, event: Dict) -> None:
        event_type = event.get("event_type") or event.get("type", "unknown")
        asset_id = event.get("asset_id") or event.get("token_id", "")

        # Update local orderbook state
        if asset_id in self._orderbooks:
            ob = self._orderbooks[asset_id]
            if event_type == "book":
                bids = event.get("bids", [])
                asks = event.get("asks", [])
                ob.apply_update(
                    [{"price": b["price"], "size": b["size"], "side": "BID"} for b in bids]
                    + [{"price": a["price"], "size": a["size"], "side": "ASK"} for a in asks]
                )
            elif event_type == "price_change":
                changes = event.get("changes", [])
                ob.apply_update(changes)

        # Enrich event with derived fields
        if asset_id in self._orderbooks:
            ob_data = self._orderbooks[asset_id].to_dict()
            event["_orderbook"] = ob_data

        # Call handlers
        handlers = self._handlers.get(event_type, []) + self._handlers.get("*", [])
        for handler in handlers:
            try:
                result = handler(event_type, event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                log.error("websocket.handler_error", event_type=event_type, error=str(exc))
