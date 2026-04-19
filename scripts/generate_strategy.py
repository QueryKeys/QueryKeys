"""
AI Strategy Generator — CLI script.

Usage:
  python scripts/generate_strategy.py                    # use live DB data
  python scripts/generate_strategy.py --dry-run          # print result, don't save
  python scripts/generate_strategy.py --trades data/historical_markets_sample.json
  python scripts/generate_strategy.py --notes "Crypto markets are trending bearish"

The script:
  1. Loads recent resolved trades from DB (or a JSON file with --trades)
  2. Derives a MarketContext snapshot
  3. Calls Claude to generate a new strategy class
  4. Saves the .py file to src/strategies/generated/
  5. Appends the strategy to config/strategies.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# ── path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.config import get_settings
from src.core.logging import get_logger
from src.strategies.ai_builder import AIStrategyBuilder, MarketContext
from src.strategies.loader import StrategyRegistry

log = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate a new trading strategy via AI")
    p.add_argument("--trades", help="Path to JSON file with trade records (overrides DB)")
    p.add_argument("--dry-run", action="store_true", help="Print strategy but do not save")
    p.add_argument("--notes", default="", help="Free-text market notes appended to the prompt")
    p.add_argument("--active-markets", type=int, default=50)
    return p.parse_args()


async def load_trades_from_db(settings) -> list[dict]:
    """Pull recent resolved trades from DB."""
    try:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy import text

        engine = create_async_engine(settings.system.db_url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as sess:
            result = await sess.execute(text("""
                SELECT condition_id, side, price, filled_size, avg_fill_price,
                       status, created_at
                FROM orders
                WHERE status = 'filled'
                ORDER BY created_at DESC
                LIMIT 500
            """))
            rows = result.mappings().all()
            return [dict(r) for r in rows]
    except Exception as exc:
        log.warning("generate_strategy.db_load_failed", error=str(exc))
        return []


async def main() -> None:
    args = parse_args()
    settings = get_settings()

    if not settings.anthropic.api_key:
        print("ERROR: ANTHROPIC_API_KEY is not set. See README for setup instructions.")
        sys.exit(1)

    builder = AIStrategyBuilder(settings)

    # Load existing strategy names so AI avoids collisions
    registry = StrategyRegistry()
    registry.load()
    existing_names = [s.name for s in registry.get_all()]

    # Load trade data
    if args.trades:
        raw = json.loads(Path(args.trades).read_text())
        trades = raw if isinstance(raw, list) else raw.get("trades", [])
        print(f"Loaded {len(trades)} trades from {args.trades}")
    else:
        trades = await load_trades_from_db(settings)
        print(f"Loaded {len(trades)} trades from database")

    if not trades:
        print("No trade history found — using default market context.")

    # Build context
    context = AIStrategyBuilder._derive_context(
        trades=trades,
        active_markets=args.active_markets,
        existing_strategy_names=existing_names,
    )
    if args.notes:
        context.recent_notes = args.notes

    print("\n── Market Context ──────────────────────────────────────")
    print(f"  Active markets   : {context.total_active_markets}")
    print(f"  Overall win rate : {context.overall_win_rate:.1%}")
    print(f"  Overall Sharpe   : {context.overall_sharpe:.2f}")
    print(f"  Avg edge         : {context.avg_edge:.3f}")
    print(f"  Volatility regime: {context.volatility_regime}")
    print(f"  Dominant category: {context.dominant_category}")
    if context.outperforming_categories:
        print(f"  Outperforming    : {', '.join(context.outperforming_categories)}")
    if context.underperforming_categories:
        print(f"  Underperforming  : {', '.join(context.underperforming_categories)}")
    print()

    if args.dry_run:
        # Still generate but skip saving
        from src.strategies.ai_builder import _build_user_prompt
        print("── Prompt that would be sent to Claude ─────────────────")
        print(_build_user_prompt(context))
        print("\n(Dry run — not calling Claude)")
        return

    print("Asking Claude to generate a strategy...")
    strategy = await builder.build_from_context(context)

    if not strategy:
        print("ERROR: Strategy generation failed. Check logs for details.")
        sys.exit(1)

    print("\n── Generated Strategy ──────────────────────────────────")
    print(f"  Name           : {strategy.name}")
    print(f"  Description    : {strategy.description}")
    print(f"  Expected edge  : {strategy.expected_edge_range}")
    print(f"  File           : {strategy.file_path}")
    print(f"\n  Rationale:\n    {strategy.rationale}")
    print(f"\n  Params: {json.dumps(strategy.params, indent=4)}")
    print("\n── Strategy Code ───────────────────────────────────────")
    print(strategy.code)
    print()
    print(f"✓ Saved to {strategy.file_path}")
    print(f"✓ Registered in config/strategies.yaml")
    print("\nRestart the bot or strategy registry to activate.")


if __name__ == "__main__":
    asyncio.run(main())
