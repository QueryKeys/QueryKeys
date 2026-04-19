#!/usr/bin/env python3
"""
QueryKeys — Backtesting runner.

Usage:
    python scripts/run_backtest.py \
        --start 2024-01-01 \
        --end 2025-12-31 \
        --capital 10000 \
        --data data/historical_markets.json \
        --output data/backtest_results.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.backtesting.backtester import Backtester
from src.core.config import get_settings
from src.core.logging import get_logger, setup_logging


def parse_args():
    parser = argparse.ArgumentParser(description="QueryKeys Backtester")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--start", default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="End date YYYY-MM-DD")
    parser.add_argument("--capital", type=float, default=None)
    parser.add_argument("--data", default="data/historical_markets.json",
                        help="Path to historical market data JSON")
    parser.add_argument("--output", default="data/backtest_results.json")
    parser.add_argument("--folds", type=int, default=None)
    parser.add_argument("--mc-runs", type=int, default=None)
    return parser.parse_args()


def generate_synthetic_data(n: int = 500) -> list:
    """Generate synthetic market data for demo/testing when no real data available."""
    import random
    import numpy as np
    from datetime import datetime, timedelta

    random.seed(42)
    np.random.seed(42)
    categories = ["Politics", "Sports", "Crypto", "Economics"]
    data = []
    base_date = datetime(2024, 1, 1)

    for i in range(n):
        entry_dt = base_date + timedelta(days=random.randint(0, 300))
        dte = random.randint(3, 60)
        exit_dt = entry_dt + timedelta(days=dte)
        # True probability: biased toward 0.5 (market is efficient on average)
        true_prob = np.clip(np.random.normal(0.5, 0.2), 0.05, 0.95)
        outcome = 1.0 if random.random() < true_prob else 0.0
        # Market price: true prob + noise (our edge source)
        noise = np.random.normal(0, 0.05)
        yes_price = float(np.clip(true_prob + noise, 0.05, 0.95))
        # Sentiment: correlated with true_prob
        sentiment = float(np.clip((true_prob - 0.5) * 2 + np.random.normal(0, 0.3), -1, 1))

        data.append({
            "condition_id": f"market_{i:04d}",
            "timestamp": entry_dt.isoformat(),
            "question": f"Synthetic market {i}",
            "category": random.choice(categories),
            "yes_price": yes_price,
            "volume_24h": random.uniform(1000, 100000),
            "liquidity": random.uniform(500, 50000),
            "dte_days": dte,
            "resolved": True,
            "outcome": outcome,
            "sentiment_score": sentiment,
            "price_momentum": float(np.random.normal(0, 0.1)),
        })

    return data


async def run_backtest(args) -> None:
    settings = get_settings(args.config)
    setup_logging(settings.system.log_level)
    log = get_logger("run_backtest")

    # Override settings if provided
    if args.start:
        settings.backtesting.start_date = args.start
    if args.end:
        settings.backtesting.end_date = args.end
    if args.capital:
        settings.backtesting.initial_capital = args.capital
    if args.folds:
        settings.backtesting.walk_forward_folds = args.folds
    if args.mc_runs:
        settings.backtesting.monte_carlo_runs = args.mc_runs

    # Load market data
    data_path = Path(args.data)
    if data_path.exists():
        log.info("backtest.loading_data", path=str(data_path))
        with open(data_path) as f:
            market_data = json.load(f)
    else:
        log.warning(
            "backtest.data_not_found_using_synthetic",
            path=str(data_path),
        )
        market_data = generate_synthetic_data(500)
        # Save synthetic data for reference
        os.makedirs("data", exist_ok=True)
        with open(data_path, "w") as f:
            json.dump(market_data, f, indent=2)
        log.info("backtest.synthetic_data_saved", n=len(market_data))

    log.info("backtest.starting", n_markets=len(market_data))

    backtester = Backtester(settings)
    result = await backtester.run(market_data)

    # Save results
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    backtester.save_results(result, args.output)

    # Print summary table
    m = result.metrics
    print("\n" + "=" * 60)
    print("  QUERYKEYS BACKTEST RESULTS")
    print("=" * 60)
    print(f"  Period:          {result.start_date} → {result.end_date}")
    print(f"  Initial Capital: ${result.initial_capital:,.2f}")
    print(f"  Final Capital:   ${result.final_capital:,.2f}")
    print(f"  Total Return:    {m.total_return:.2%}")
    print(f"  Ann. Return:     {m.annualized_return:.2%}")
    print(f"  Sharpe Ratio:    {m.sharpe_ratio:.3f}")
    print(f"  Sortino Ratio:   {m.sortino_ratio:.3f}")
    print(f"  Calmar Ratio:    {m.calmar_ratio:.3f}")
    print(f"  Max Drawdown:    {m.max_drawdown:.2%}")
    print(f"  Win Rate:        {m.win_rate:.2%}")
    print(f"  Profit Factor:   {m.profit_factor:.2f}")
    print(f"  Num Trades:      {m.num_trades}")
    print(f"  Avg Edge:        {m.avg_edge:.3f}")
    print(f"  Brier Score:     {m.brier_score:.4f}")
    if result.monte_carlo:
        mc = result.monte_carlo
        print(f"\n  Monte Carlo ({mc.n_runs} runs):")
        print(f"  Equity P10/P50/P90: ${mc.equity_p10:,.0f} / ${mc.equity_p50:,.0f} / ${mc.equity_p90:,.0f}")
        print(f"  Sharpe P50:         {mc.sharpe_p50:.3f}")
        print(f"  Prob. of Ruin:      {mc.prob_ruin:.1%}")
    print("=" * 60)
    print(f"\nResults saved to: {args.output}")


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run_backtest(args))
