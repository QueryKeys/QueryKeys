"""
Gamma API client — market discovery, events, tags, categories, volumes.
https://gamma-api.polymarket.com
"""

from __future__ import annotations

import asyncio
import ssl
from datetime import datetime, timezone
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

_GAMMA_BASE = "https://gamma-api.polymarket.com"


class GammaAPIClient:
    """Async HTTP client for the Polymarket Gamma API."""

    def __init__(self, settings: Settings) -> None:
        self._base = settings.polymarket.gamma_api_url
        self._rps = settings.rate_limits.gamma_api_rps
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(self._rps)

    async def __aenter__(self) -> "GammaAPIClient":
        await self.init()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def init(self) -> None:
        timeout = aiohttp.ClientTimeout(total=30)
        connector = aiohttp.TCPConnector(ssl=_SSL_CONTEXT) if _SSL_CONTEXT else None
        self._session = aiohttp.ClientSession(
            base_url=self._base,
            timeout=timeout,
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
                        "gamma_api.request_failed",
                        path=path,
                        attempt=attempt + 1,
                        error=str(exc),
                    )
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)
                    else:
                        raise DataFetchError(f"Gamma API {path} failed: {exc}") from exc
        return None

    # ------------------------------------------------------------------
    # Markets
    # ------------------------------------------------------------------

    async def get_markets(
        self,
        active: bool = True,
        closed: bool = False,
        limit: int = 100,
        offset: int = 0,
        category: Optional[str] = None,
        tag_slug: Optional[str] = None,
        order: str = "volume24hr",
        ascending: bool = False,
    ) -> List[Dict]:
        params: Dict[str, Any] = {
            "active": str(active).lower(),
            "closed": str(closed).lower(),
            "limit": limit,
            "offset": offset,
            "order": order,
            "ascending": str(ascending).lower(),
        }
        if category:
            params["category"] = category
        if tag_slug:
            params["tag_slug"] = tag_slug
        data = await self._get("/markets", params)
        return data if isinstance(data, list) else []

    async def get_market(self, condition_id: str) -> Dict:
        data = await self._get(f"/markets/{condition_id}")
        return data if isinstance(data, dict) else {}

    async def get_market_by_slug(self, slug: str) -> Dict:
        data = await self._get("/markets", params={"slug": slug})
        markets = data if isinstance(data, list) else []
        return markets[0] if markets else {}

    async def scan_markets(
        self,
        min_volume: float = 0,
        min_liquidity: float = 0,
        min_days: int = 1,
        max_days: int = 90,
        categories: Optional[List[str]] = None,
        max_results: int = 100,
    ) -> List[Dict]:
        """Scan and filter active markets by quality criteria."""
        now = datetime.now(timezone.utc)
        candidates: List[Dict] = []
        category_list = categories or [None]  # type: ignore[list-item]

        for cat in category_list:
            offset = 0
            while len(candidates) < max_results * 3:
                batch = await self.get_markets(
                    active=True,
                    limit=100,
                    offset=offset,
                    category=cat,
                )
                if not batch:
                    break
                candidates.extend(batch)
                if len(batch) < 100:
                    break
                offset += 100

        results = []
        for m in candidates:
            vol = float(m.get("volume24hr", 0) or 0)
            liq = float(m.get("liquidityNum", 0) or 0)
            end_raw = m.get("endDate") or m.get("end_date_iso")
            if not end_raw:
                continue
            try:
                if isinstance(end_raw, str):
                    end_dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
                else:
                    end_dt = datetime.fromtimestamp(end_raw, tz=timezone.utc)
            except (ValueError, TypeError):
                continue

            days_to_expiry = (end_dt - now).days
            if (
                vol >= min_volume
                and liq >= min_liquidity
                and min_days <= days_to_expiry <= max_days
            ):
                results.append(m)
                if len(results) >= max_results:
                    break

        log.info("gamma_api.scan_complete", found=len(results))
        return results

    # ------------------------------------------------------------------
    # Events & tags
    # ------------------------------------------------------------------

    async def get_events(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        data = await self._get("/events", params={"limit": limit, "offset": offset})
        return data if isinstance(data, list) else []

    async def get_event(self, event_id: str) -> Dict:
        data = await self._get(f"/events/{event_id}")
        return data if isinstance(data, dict) else {}

    async def get_tags(self) -> List[Dict]:
        data = await self._get("/tags")
        return data if isinstance(data, list) else []
