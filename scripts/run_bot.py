#!/usr/bin/env python3
"""
QueryKeys Polymarket Bot — main entry point.

Usage:
    python scripts/run_bot.py [--config config/config.yaml] [--mode paper|live]

The bot runs continuously until interrupted (Ctrl+C or SIGTERM).
All components are initialized, then the async event loop takes over.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import get_settings
from src.core.database import DatabaseManager
from src.core.logging import get_logger, setup_logging
from src.data.data_api import DataAPIClient
from src.data.gamma_api import GammaAPIClient
from src.data.polymarket_client import PolymarketClient
from src.data.sentiment import SentimentAnalyzer
from src.data.websocket_feed import WebSocketFeed
from src.prediction.ensemble import PredictorEnsemble
from src.trading.risk_manager import RiskManager
from src.trading.trader import Trader


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QueryKeys Polymarket Bot")
    parser.add_argument("--config", default="config/config.yaml", help="Config file path")
    parser.add_argument("--mode", choices=["paper", "live", "backtest"],
                        help="Override trading mode from config")
    parser.add_argument("--capital", type=float, default=None,
                        help="Override initial capital")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    settings = get_settings(args.config)

    if args.mode:
        settings.system.mode = args.mode

    setup_logging(settings.system.log_level)
    log = get_logger("run_bot")

    # Ensure data directories exist
    os.makedirs(settings.system.data_dir, exist_ok=True)
    os.makedirs(settings.system.models_dir, exist_ok=True)

    log.info(
        "querykeys.starting",
        mode=settings.system.mode,
        version="1.0.0",
    )

    # Warn if running live without keys
    if settings.system.mode == "live":
        if not settings.polymarket.private_key:
            log.error("querykeys.no_private_key_live_mode_requires_key")
            sys.exit(1)
        log.warning(
            "querykeys.LIVE_MODE_ACTIVE",
            message="REAL MONEY TRADING — ensure you have reviewed risk settings",
        )

    # Initialize all components
    db = DatabaseManager(settings.system.db_url)
    await db.init()

    polymarket_client = PolymarketClient(settings)
    await polymarket_client.init()

    gamma_api = GammaAPIClient(settings)
    await gamma_api.init()

    data_api = DataAPIClient(settings)
    await data_api.init()

    ws_feed = WebSocketFeed(settings)
    sentiment = SentimentAnalyzer(settings)
    await sentiment.init()

    ensemble = PredictorEnsemble(settings)

    initial_capital = args.capital or 10_000.0
    if settings.system.mode == "live":
        try:
            initial_capital = await polymarket_client.get_balance()
            log.info("querykeys.live_balance", balance=initial_capital)
        except Exception as e:
            log.warning("querykeys.balance_fetch_failed", error=str(e))

    risk_manager = RiskManager(settings, initial_capital=initial_capital)

    trader = Trader(
        settings=settings,
        db=db,
        polymarket_client=polymarket_client,
        gamma_api=gamma_api,
        data_api=data_api,
        ws_feed=ws_feed,
        sentiment=sentiment,
        ensemble=ensemble,
        risk_manager=risk_manager,
    )

    # Graceful shutdown on SIGTERM/SIGINT
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal():
        log.info("querykeys.signal_received_shutting_down")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    # Run bot until stop signal
    bot_task = asyncio.create_task(trader.run())
    await stop_event.wait()
    bot_task.cancel()
    try:
        await bot_task
    except asyncio.CancelledError:
        pass

    # Cleanup
    await trader.stop()
    await gamma_api.close()
    await data_api.close()
    await sentiment.close()
    await db.close()
    log.info("querykeys.shutdown_complete")


if __name__ == "__main__":
    asyncio.run(main())
