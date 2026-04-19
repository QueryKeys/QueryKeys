"""
Official Polymarket CLOB client wrapper.

Wraps py-clob-client with:
- Async-compatible execution via asyncio.to_thread
- Automatic L1→L2 API key derivation
- Retry logic with exponential backoff
- Circuit breaker for persistent failures
- Gasless order support
- Rate limiting
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import (
        ApiCreds,
        BookParams,
        MarketOrderArgs,
        OpenOrderParams,
        OrderArgs,
        OrderBookSummary,
        OrderType,
        PartialCreateOrderOptions,
        TradeParams,
    )
    from py_clob_client.constants import POLYGON
    from py_clob_client.exceptions import PolyException
except ImportError:  # library not installed in test/dev environments
    ClobClient = None  # type: ignore[assignment,misc]
    ApiCreds = BookParams = MarketOrderArgs = OpenOrderParams = None  # type: ignore[assignment,misc]
    OrderArgs = OrderBookSummary = OrderType = PartialCreateOrderOptions = None  # type: ignore[assignment,misc]
    TradeParams = POLYGON = PolyException = None  # type: ignore[assignment,misc]

from src.core.config import Settings
from src.core.exceptions import AuthenticationError, DataFetchError, OrderError
from src.core.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Rate limiter (token bucket)
# ---------------------------------------------------------------------------


class TokenBucket:
    def __init__(self, rate: float, capacity: float) -> None:
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(
                self._capacity, self._tokens + elapsed * self._rate
            )
            self._last_refill = now
            if self._tokens < 1:
                wait = (1 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


class CircuitBreaker:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, failure_threshold: int = 5, reset_timeout: float = 60.0) -> None:
        self._state = self.CLOSED
        self._failures = 0
        self._threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._last_failure: float = 0.0

    @property
    def is_open(self) -> bool:
        if self._state == self.OPEN:
            if time.monotonic() - self._last_failure > self._reset_timeout:
                self._state = self.HALF_OPEN
                return False
            return True
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._state = self.CLOSED

    def record_failure(self) -> None:
        self._failures += 1
        self._last_failure = time.monotonic()
        if self._failures >= self._threshold:
            self._state = self.OPEN
            log.warning("circuit_breaker.opened", failures=self._failures)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class PolymarketClient:
    """Async-friendly wrapper around py-clob-client ClobClient."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._clob: Optional[ClobClient] = None
        self._bucket = TokenBucket(
            rate=settings.rate_limits.clob_api_rps,
            capacity=settings.rate_limits.clob_api_rps * 2,
        )
        self._circuit = CircuitBreaker()
        self._mode = settings.system.mode

    async def init(self) -> None:
        """Initialise client, derive L2 keys if necessary."""
        cfg = self._settings.polymarket
        if not cfg.private_key:
            raise AuthenticationError("POLYMARKET_PRIVATE_KEY not set")

        creds: Optional[ApiCreds] = None
        if cfg.api_key and cfg.api_secret and cfg.api_passphrase:
            creds = ApiCreds(
                api_key=cfg.api_key,
                api_secret=cfg.api_secret,
                api_passphrase=cfg.api_passphrase,
            )

        self._clob = await asyncio.to_thread(
            self._build_client, cfg, creds
        )

        # Derive L2 keys if not supplied
        if creds is None:
            log.info("polymarket_client.deriving_l2_keys")
            derived = await asyncio.to_thread(self._clob.derive_api_key)
            self._clob = await asyncio.to_thread(self._build_client, cfg, derived)
            log.info(
                "polymarket_client.l2_keys_derived",
                api_key=derived.api_key[:8] + "...",
            )

        log.info("polymarket_client.initialized", mode=self._mode)

    def _build_client(
        self,
        cfg: Any,
        creds: Optional[ApiCreds],
    ) -> ClobClient:
        funder = cfg.funder or None
        return ClobClient(
            host=cfg.clob_api_url,
            chain_id=POLYGON,
            key=cfg.private_key,
            creds=creds,
            signature_type=cfg.signature_type,
            funder=funder,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call(self, fn_name: str, *args: Any, **kwargs: Any) -> Any:
        """Throttled, circuit-breaking, retry-wrapped async call."""
        if self._circuit.is_open:
            raise OrderError("Circuit breaker is OPEN — CLOB calls suspended")

        await self._bucket.acquire()
        retries = self._settings.execution.retry_attempts
        delay = float(self._settings.execution.retry_delay)

        for attempt in range(retries):
            try:
                fn = getattr(self._clob, fn_name)
                result = await asyncio.to_thread(fn, *args, **kwargs)
                self._circuit.record_success()
                return result
            except PolyException as exc:
                self._circuit.record_failure()
                log.warning(
                    "polymarket_client.call_failed",
                    fn=fn_name,
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt < retries - 1:
                    await asyncio.sleep(delay * (2 ** attempt))
                else:
                    raise OrderError(f"CLOB {fn_name} failed after {retries} attempts: {exc}") from exc
        return None  # unreachable

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    async def get_markets(self, next_cursor: str = "") -> Dict[str, Any]:
        return await self._call("get_markets", next_cursor=next_cursor)

    async def get_market(self, condition_id: str) -> Dict[str, Any]:
        return await self._call("get_market", condition_id)

    async def get_orderbook(self, token_id: str) -> OrderBookSummary:
        params = BookParams(token_id=token_id)
        return await self._call("get_order_book", params)

    async def get_orderbooks(self, token_ids: List[str]) -> List[OrderBookSummary]:
        params = [BookParams(token_id=tid) for tid in token_ids]
        return await self._call("get_order_books", params)

    async def get_midpoint(self, token_id: str) -> float:
        result = await self._call("get_midpoint", token_id)
        return float(result.get("mid", 0.5))

    async def get_spread(self, token_id: str) -> float:
        result = await self._call("get_spread", token_id)
        return float(result.get("spread", 0.0))

    async def get_last_trade_price(self, token_id: str) -> Optional[float]:
        result = await self._call("get_last_trade_price", token_id)
        price = result.get("price")
        return float(price) if price is not None else None

    async def get_trades(
        self,
        token_id: Optional[str] = None,
        after: Optional[int] = None,
        limit: int = 100,
    ) -> List[Dict]:
        params = TradeParams(token_id=token_id, after=after, limit=limit)
        result = await self._call("get_trades", params)
        return result if isinstance(result, list) else []

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    async def place_limit_order(
        self,
        token_id: str,
        side: str,      # "BUY" | "SELL"
        price: float,
        size: float,
        expiration: int = 0,
    ) -> Dict[str, Any]:
        if self._mode != "live":
            log.info(
                "paper_trade.limit_order",
                token_id=token_id[:12],
                side=side,
                price=price,
                size=size,
            )
            return {"orderId": f"paper_{int(time.time()*1000)}", "status": "paper"}

        args = OrderArgs(
            token_id=token_id,
            price=price,
            size=size,
            side=side,
            expiration=expiration,
        )
        opts = PartialCreateOrderOptions(neg_risk=False)
        order = await self._call("create_limit_order", args, opts)
        result = await self._call("post_order", order, OrderType.GTC)
        log.info(
            "order.placed",
            order_id=result.get("orderID"),
            side=side,
            price=price,
            size=size,
        )
        return result

    async def place_market_order(
        self,
        token_id: str,
        amount: float,
    ) -> Dict[str, Any]:
        if self._mode != "live":
            log.info("paper_trade.market_order", token_id=token_id[:12], amount=amount)
            return {"orderId": f"paper_mkt_{int(time.time()*1000)}", "status": "paper"}

        args = MarketOrderArgs(token_id=token_id, amount=amount)
        result = await self._call("create_market_order", args)
        return result

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        if self._mode != "live":
            return {"status": "cancelled", "orderId": order_id}
        return await self._call("cancel", order_id)

    async def cancel_all_orders(self) -> Dict[str, Any]:
        if self._mode != "live":
            return {"status": "cancelled_all"}
        return await self._call("cancel_all")

    async def get_open_orders(self, condition_id: Optional[str] = None) -> List[Dict]:
        if self._mode != "live":
            return []
        params = OpenOrderParams(market=condition_id)
        result = await self._call("get_orders", params)
        return result if isinstance(result, list) else []

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    async def get_balance(self) -> float:
        """Return USDC balance on Polygon."""
        if self._mode != "live":
            return 0.0
        result = await self._call("get_balance_allowance")
        balance = result.get("balance", {})
        return float(balance.get("USDC", 0))

    async def get_positions(self) -> List[Dict]:
        if self._mode != "live":
            return []
        result = await self._call("get_positions")
        return result if isinstance(result, list) else []
