"""
Polymarket Data API client.
https://data-api.polymarket.com

Provides: historical prices, trade history, open interest,
positions, user activity.
"""

from __future__ import annotations

import asyncio
import ssl
from typing import Any, Dict, List, Optional

import aiohttp

try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = None

from src.core.config import Settings
from src.core.exceptions import DataFetchError
from src.core.logging import get_logger

log = get_logger(__name__)


class DataAPIClient:
    """Async client for Polymarket Data API."""

    def __init__(self, settings: Settings) -> None:
        self._base = settings.polymarket.data_api_url
        self._semaphore = asyncio.Semaphore(settings.rate_limits.data_api_rps)
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "DataAPIClient":
        await self.init()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def init(self) -> None:
        connector = aiohttp.TCPConnector(ssl=_SSL_CONTEXT) if _SSL_CONTEXT else None
        self._session = aiohttp.ClientSession(
            base_url=self._base,
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"Accept": "application/json"},
            connector=connector,
        )

    async def close(self) -> None:
        if self._session:
            await self._session.close()

    async def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        assert self._session, "Call init() first"
        async with self._semaphore:
            for attempt in range(3):
                try:
                    async with self._session.get(path, params=params) as resp:
                        resp.raise_for_status()
                        return await resp.json()
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    log.warning(
                        "data_api.request_failed",
                        path=path,
                        attempt=attempt + 1,
                        error=str(exc),
                    )
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)
                    else:
                        raise DataFetchError(f"Data API {path} failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Price history
    # ------------------------------------------------------------------

    async def get_price_history(
        self,
        market_id: str,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        interval: str = "1h",
        fidelity: int = 60,
    ) -> List[Dict]:
        """
        Fetch OHLCV-style price history for a market.
        interval: '1m'|'1h'|'1d'
        fidelity: resolution in minutes (1, 5, 60, 1440)
        """
        params: Dict[str, Any] = {
            "market": market_id,
            "interval": interval,
            "fidelity": fidelity,
        }
        if start_ts:
            params["startTs"] = start_ts
        if end_ts:
            params["endTs"] = end_ts
        data = await self._get("/prices-history", params)
        history = data.get("history", []) if isinstance(data, dict) else []
        return history

    # ------------------------------------------------------------------
    # Trades & volume
    # ------------------------------------------------------------------

    async def get_trades(
        self,
        condition_id: str,
        limit: int = 200,
        offset: int = 0,
    ) -> List[Dict]:
        params = {
            "market": condition_id,
            "limit": limit,
            "offset": offset,
        }
        data = await self._get("/trades", params)
        return data if isinstance(data, list) else []

    async def get_volume(self, condition_id: str) -> Dict:
        data = await self._get(f"/volume/{condition_id}")
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------
    # Open interest & positions
    # ------------------------------------------------------------------

    async def get_open_interest(self, condition_id: str) -> Dict:
        data = await self._get("/open-interest", params={"market": condition_id})
        return data if isinstance(data, dict) else {}

    async def get_positions(
        self,
        user: Optional[str] = None,
        condition_id: Optional[str] = None,
    ) -> List[Dict]:
        params: Dict = {}
        if user:
            params["user"] = user
        if condition_id:
            params["market"] = condition_id
        data = await self._get("/positions", params)
        return data if isinstance(data, list) else []

    async def get_global_stats(self) -> Dict:
        data = await self._get("/stats")
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------
    # Market analytics helpers
    # ------------------------------------------------------------------

    async def get_market_analytics(self, condition_id: str) -> Dict:
        """Combine volume, OI and trade data for feature engineering."""
        volume, oi, trades = await asyncio.gather(
            self.get_volume(condition_id),
            self.get_open_interest(condition_id),
            self.get_trades(condition_id, limit=50),
            return_exceptions=True,
        )
        return {
            "condition_id": condition_id,
            "volume": volume if not isinstance(volume, Exception) else {},
            "open_interest": oi if not isinstance(oi, Exception) else {},
            "recent_trades": trades if not isinstance(trades, Exception) else [],
        }
