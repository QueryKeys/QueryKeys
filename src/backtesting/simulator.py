"""
Monte Carlo simulation for prediction market portfolios.

Runs N independent simulations of the trading strategy over the
backtest period, sampling from the historical distribution of:
  - Edge accuracy (modeled vs. realized)
  - Fill rates
  - Market resolution uncertainty

Outputs confidence intervals on key metrics:
  final equity, Sharpe, max drawdown, etc.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from src.backtesting.metrics import BacktestMetrics, compute_metrics
from src.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class MonteCarloResult:
    n_runs: int
    # Percentile statistics on equity final value
    equity_p10: float
    equity_p25: float
    equity_p50: float
    equity_p75: float
    equity_p90: float
    equity_mean: float
    equity_std: float

    # Percentile statistics on Sharpe ratio
    sharpe_p10: float
    sharpe_p50: float
    sharpe_p90: float

    # Percentile statistics on max drawdown
    max_dd_p10: float
    max_dd_p50: float
    max_dd_p90: float

    # Probability of ruin (drawdown > 50%)
    prob_ruin: float

    # All run equity curves (for plotting)
    equity_curves: List[List[float]] = field(default_factory=list)
    all_metrics: List[BacktestMetrics] = field(default_factory=list)


class MonteCarloSimulator:
    """
    Bootstrap Monte Carlo simulator.

    Strategy: resample historical trades with replacement and
    re-simulate the portfolio N times to get distributional outcomes.
    """

    def __init__(self, n_runs: int = 1000, seed: int = 42) -> None:
        self._n_runs = n_runs
        self._rng = np.random.default_rng(seed)

    def run(
        self,
        historical_trades: List[Dict],
        initial_capital: float = 10_000.0,
        n_trades_per_run: Optional[int] = None,
    ) -> MonteCarloResult:
        """
        Bootstrap Monte Carlo over historical trades.

        historical_trades: list of {pnl, edge, model_prob, entry_price,
                                    actual_outcome, kelly_fraction, size_usd}
        """
        if not historical_trades:
            log.warning("monte_carlo.no_trades")
            return self._empty_result()

        n = n_trades_per_run or len(historical_trades)
        all_final_equity: List[float] = []
        all_sharpes: List[float] = []
        all_max_dds: List[float] = []
        all_curves: List[List[float]] = []
        all_metrics: List[BacktestMetrics] = []

        log.info("monte_carlo.starting", n_runs=self._n_runs, trades_per_run=n)

        for run_idx in range(self._n_runs):
            # Resample trades with replacement
            idxs = self._rng.integers(0, len(historical_trades), size=n)
            sampled = [historical_trades[i] for i in idxs]

            # Simulate portfolio
            equity_curve, sim_trades = self._simulate_portfolio(
                sampled, initial_capital
            )

            metrics = compute_metrics(
                equity_curve=equity_curve,
                trades=sim_trades,
                predictions=[
                    {
                        "predicted_prob": t.get("model_prob", 0.5),
                        "actual_outcome": t.get("actual_outcome", 0.5),
                    }
                    for t in sim_trades
                ],
            )
            all_final_equity.append(equity_curve[-1])
            all_sharpes.append(metrics.sharpe_ratio)
            all_max_dds.append(metrics.max_drawdown)
            all_curves.append(equity_curve)
            all_metrics.append(metrics)

        final_eq = np.array(all_final_equity)
        sharpes = np.array(all_sharpes)
        max_dds = np.array(all_max_dds)
        prob_ruin = float(np.mean(max_dds > 0.5))

        log.info(
            "monte_carlo.complete",
            median_final=round(float(np.median(final_eq)), 2),
            median_sharpe=round(float(np.median(sharpes)), 3),
            prob_ruin=round(prob_ruin, 3),
        )

        return MonteCarloResult(
            n_runs=self._n_runs,
            equity_p10=float(np.percentile(final_eq, 10)),
            equity_p25=float(np.percentile(final_eq, 25)),
            equity_p50=float(np.percentile(final_eq, 50)),
            equity_p75=float(np.percentile(final_eq, 75)),
            equity_p90=float(np.percentile(final_eq, 90)),
            equity_mean=float(np.mean(final_eq)),
            equity_std=float(np.std(final_eq)),
            sharpe_p10=float(np.percentile(sharpes, 10)),
            sharpe_p50=float(np.percentile(sharpes, 50)),
            sharpe_p90=float(np.percentile(sharpes, 90)),
            max_dd_p10=float(np.percentile(max_dds, 10)),
            max_dd_p50=float(np.percentile(max_dds, 50)),
            max_dd_p90=float(np.percentile(max_dds, 90)),
            prob_ruin=prob_ruin,
            equity_curves=all_curves[:100],  # Store first 100 for plotting
            all_metrics=all_metrics,
        )

    def _simulate_portfolio(
        self,
        trades: List[Dict],
        initial_capital: float,
    ) -> Tuple[List[float], List[Dict]]:
        """Sequentially apply trades to a portfolio."""
        capital = initial_capital
        equity_curve = [capital]
        sim_trades = []

        for trade in trades:
            size = trade.get("size_usd", 0)
            pnl = trade.get("pnl", 0)

            # Add small random noise to simulate execution variance
            noise = self._rng.normal(0, abs(pnl) * 0.05) if pnl != 0 else 0
            realized_pnl = pnl + noise

            capital += realized_pnl
            capital = max(capital, 0)
            equity_curve.append(capital)

            sim_trades.append({**trade, "pnl": realized_pnl})

            if capital <= 0:
                break

        return equity_curve, sim_trades

    def _empty_result(self) -> MonteCarloResult:
        return MonteCarloResult(
            n_runs=0,
            equity_p10=0, equity_p25=0, equity_p50=0,
            equity_p75=0, equity_p90=0, equity_mean=0, equity_std=0,
            sharpe_p10=0, sharpe_p50=0, sharpe_p90=0,
            max_dd_p10=0, max_dd_p50=0, max_dd_p90=0,
            prob_ruin=1.0,
        )
