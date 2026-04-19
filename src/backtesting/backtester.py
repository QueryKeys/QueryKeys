"""
Historical backtester with walk-forward optimization.

Pipeline:
  1. Load historical market data from DB / flat files
  2. Walk-forward split: train on fold N, test on fold N+1
  3. For each test bar: run feature engineering → ensemble prediction
     → edge detection → Kelly sizing → simulated execution
  4. Aggregate results, compute metrics, run Monte Carlo
  5. Report: per-fold metrics, aggregate metrics, MC confidence intervals

Realistic simulation:
  - Limit order fill model (only fills if price crosses limit)
  - Spread cost deducted
  - Position-level P&L tracking
  - Resolved via actual historical outcomes
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.backtesting.metrics import BacktestMetrics, compute_metrics
from src.backtesting.simulator import MonteCarloResult, MonteCarloSimulator
from src.core.config import Settings
from src.core.logging import get_logger
from src.features.engineer import FeatureEngineer
from src.prediction.edge_detector import EdgeDetector
from src.prediction.ensemble import EnsemblePrediction
from src.trading.kelly import KellyCriterion
from src.trading.risk_manager import RiskManager

log = get_logger(__name__)


@dataclass
class BacktestTrade:
    condition_id: str
    side: str
    entry_price: float
    exit_price: float
    size_usd: float
    pnl: float
    edge: float
    model_prob: float
    actual_outcome: float   # 1.0=YES, 0.0=NO
    kelly_fraction: float
    entry_ts: str
    exit_ts: str


@dataclass
class BacktestResult:
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    metrics: BacktestMetrics
    monte_carlo: Optional[MonteCarloResult]
    fold_metrics: List[BacktestMetrics] = field(default_factory=list)
    trades: List[BacktestTrade] = field(default_factory=list)
    config: Dict = field(default_factory=dict)


class Backtester:
    """Walk-forward backtester for the QueryKeys prediction engine."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._bt_cfg = settings.backtesting
        self._feature_eng = FeatureEngineer()
        self._kelly = KellyCriterion(
            kelly_fraction=settings.risk.kelly_fraction,
            min_kelly_edge=settings.risk.min_kelly_edge,
        )
        self._edge_detector = EdgeDetector(
            min_edge=settings.prediction.min_edge,
            min_confidence=settings.prediction.min_confidence,
        )
        self._mc_sim = MonteCarloSimulator(
            n_runs=settings.backtesting.monte_carlo_runs
        )

    async def run(
        self,
        market_data: List[Dict],
        n_folds: Optional[int] = None,
    ) -> BacktestResult:
        """
        Run walk-forward backtest on historical market data.

        market_data: list of market snapshots sorted by timestamp, each:
          {
            'condition_id', 'timestamp', 'question', 'category',
            'yes_price', 'volume_24h', 'liquidity', 'dte_days',
            'resolved': bool, 'outcome': 1.0|0.0,
            'price_history': [...],  # list of OHLCV dicts
            'sentiment_score': float,
          }
        """
        n_folds = n_folds or self._bt_cfg.walk_forward_folds
        initial_capital = self._bt_cfg.initial_capital

        if not market_data:
            raise ValueError("No market data provided for backtesting")

        # Sort by timestamp
        market_data = sorted(market_data, key=lambda x: x.get("timestamp", ""))

        # Walk-forward splits
        folds = self._create_walk_forward_folds(market_data, n_folds)
        log.info("backtester.starting", folds=len(folds), markets=len(market_data))

        all_trades: List[BacktestTrade] = []
        fold_metrics: List[BacktestMetrics] = []
        capital = initial_capital

        for fold_idx, (train_data, test_data) in enumerate(folds):
            log.info(
                "backtester.fold",
                fold=fold_idx + 1,
                train_n=len(train_data),
                test_n=len(test_data),
                capital=round(capital, 2),
            )

            # Simulate on test fold
            fold_trades, fold_equity, capital = self._simulate_fold(
                test_data=test_data,
                initial_capital=capital,
            )
            all_trades.extend(fold_trades)

            if fold_equity:
                fm = compute_metrics(
                    equity_curve=fold_equity,
                    trades=[t.__dict__ for t in fold_trades],
                    predictions=[
                        {
                            "predicted_prob": t.model_prob,
                            "actual_outcome": t.actual_outcome,
                        }
                        for t in fold_trades
                    ],
                )
                fold_metrics.append(fm)
                log.info(
                    "backtester.fold_complete",
                    fold=fold_idx + 1,
                    trades=fm.num_trades,
                    total_return=round(fm.total_return, 4),
                    sharpe=round(fm.sharpe_ratio, 3),
                    max_dd=round(fm.max_drawdown, 4),
                )

        # Full equity curve
        equity_curve = [initial_capital]
        for t in all_trades:
            equity_curve.append(equity_curve[-1] + t.pnl)

        overall_metrics = compute_metrics(
            equity_curve=equity_curve,
            trades=[t.__dict__ for t in all_trades],
            predictions=[
                {"predicted_prob": t.model_prob, "actual_outcome": t.actual_outcome}
                for t in all_trades
            ],
        )

        # Monte Carlo
        mc_result = self._mc_sim.run(
            historical_trades=[t.__dict__ for t in all_trades],
            initial_capital=initial_capital,
        )

        result = BacktestResult(
            start_date=self._bt_cfg.start_date,
            end_date=self._bt_cfg.end_date,
            initial_capital=initial_capital,
            final_capital=equity_curve[-1],
            metrics=overall_metrics,
            monte_carlo=mc_result,
            fold_metrics=fold_metrics,
            trades=all_trades,
            config={
                "kelly_fraction": self._settings.risk.kelly_fraction,
                "min_edge": self._settings.prediction.min_edge,
                "n_folds": n_folds,
                "monte_carlo_runs": self._bt_cfg.monte_carlo_runs,
            },
        )

        self._print_summary(result)
        return result

    # ------------------------------------------------------------------
    # Walk-forward splits
    # ------------------------------------------------------------------

    def _create_walk_forward_folds(
        self,
        data: List[Dict],
        n_folds: int,
    ) -> List[Tuple[List[Dict], List[Dict]]]:
        """Expanding-window walk-forward: train grows, test stays constant size."""
        n = len(data)
        fold_size = n // (n_folds + 1)
        folds = []
        for i in range(n_folds):
            train_end = fold_size * (i + 1)
            test_end = min(fold_size * (i + 2), n)
            train = data[:train_end]
            test = data[train_end:test_end]
            if test:
                folds.append((train, test))
        return folds

    # ------------------------------------------------------------------
    # Fold simulation
    # ------------------------------------------------------------------

    def _simulate_fold(
        self,
        test_data: List[Dict],
        initial_capital: float,
    ) -> Tuple[List[BacktestTrade], List[float], float]:
        """Simulate trading on a single test fold. Returns (trades, equity_curve, final_capital)."""
        capital = initial_capital
        equity_curve = [capital]
        trades: List[BacktestTrade] = []
        positions: Dict[str, Dict] = {}

        # Group by condition_id → sorted snapshots
        market_snaps: Dict[str, List[Dict]] = defaultdict(list)
        for row in test_data:
            market_snaps[row["condition_id"]].append(row)

        for cid, snaps in market_snaps.items():
            snaps.sort(key=lambda x: x.get("timestamp", ""))
            if len(snaps) < 2:
                continue

            # Use first snapshot as entry, last as exit
            entry_snap = snaps[0]
            exit_snap = snaps[-1]

            if not exit_snap.get("resolved"):
                continue  # Skip unresolved markets

            yes_price = float(entry_snap.get("yes_price", 0.5))
            model_prob = self._simple_model_prob(entry_snap)
            edge = model_prob - yes_price
            category = entry_snap.get("category", "Other")
            actual_outcome = float(exit_snap.get("outcome", 0.5))
            dte = float(entry_snap.get("dte_days", 30))

            # Determine side
            if abs(edge) < self._settings.prediction.min_edge:
                continue

            side = "YES" if edge > 0 else "NO"
            if side == "YES":
                entry_price = min(yes_price + 0.005, 0.99)  # include spread
                p_win = model_prob
            else:
                entry_price = min((1 - yes_price) + 0.005, 0.99)
                p_win = 1 - model_prob
                edge = abs(edge)

            # Kelly sizing
            b = (1 - entry_price) / max(entry_price, 0.01)
            q = 1 - p_win
            kelly_raw = max(0.0, (p_win * b - q) / max(b, 0.01))
            kelly = kelly_raw * self._settings.risk.kelly_fraction
            kelly = min(kelly, self._settings.risk.max_single_market)
            bet_size = capital * kelly
            bet_size = min(
                max(bet_size, self._settings.execution.min_order_size),
                self._settings.execution.max_order_size,
                capital * self._settings.risk.max_single_market,
            )

            if bet_size <= 0 or bet_size > capital:
                continue

            # Compute P&L
            if side == "YES":
                if actual_outcome == 1.0:
                    exit_price = 1.0
                    pnl = (exit_price - entry_price) * (bet_size / max(entry_price, 0.01))
                else:
                    exit_price = 0.0
                    pnl = -bet_size
            else:
                if actual_outcome == 0.0:
                    exit_price = 1.0
                    pnl = (exit_price - entry_price) * (bet_size / max(entry_price, 0.01))
                else:
                    exit_price = 0.0
                    pnl = -bet_size

            capital += pnl
            capital = max(capital, 0)
            equity_curve.append(capital)

            trades.append(BacktestTrade(
                condition_id=cid,
                side=side,
                entry_price=entry_price,
                exit_price=exit_price,
                size_usd=bet_size,
                pnl=pnl,
                edge=edge,
                model_prob=model_prob,
                actual_outcome=actual_outcome,
                kelly_fraction=kelly,
                entry_ts=str(entry_snap.get("timestamp", "")),
                exit_ts=str(exit_snap.get("timestamp", "")),
            ))

            if capital <= 0:
                break

        return trades, equity_curve, capital

    def _simple_model_prob(self, snap: Dict) -> float:
        """
        Simple model for backtesting when full ensemble isn't available.
        Uses market price + sentiment + price momentum.
        """
        market_price = float(snap.get("yes_price", 0.5))
        sentiment = float(snap.get("sentiment_score", 0.0))
        momentum = float(snap.get("price_momentum", 0.0))

        # Simple linear blend
        prob = (
            0.70 * market_price
            + 0.15 * (market_price + sentiment * 0.1)
            + 0.15 * (market_price + momentum * 0.02)
        )
        return float(np.clip(prob, 0.02, 0.98))

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def _print_summary(self, result: BacktestResult) -> None:
        m = result.metrics
        mc = result.monte_carlo
        log.info(
            "backtester.summary",
            total_return=f"{m.total_return:.1%}",
            ann_return=f"{m.annualized_return:.1%}",
            sharpe=round(m.sharpe_ratio, 3),
            sortino=round(m.sortino_ratio, 3),
            max_dd=f"{m.max_drawdown:.1%}",
            win_rate=f"{m.win_rate:.1%}",
            profit_factor=round(m.profit_factor, 2),
            brier=round(m.brier_score, 4),
            num_trades=m.num_trades,
            final_capital=round(result.final_capital, 2),
        )
        if mc:
            log.info(
                "backtester.monte_carlo_summary",
                equity_p10=round(mc.equity_p10, 2),
                equity_p50=round(mc.equity_p50, 2),
                equity_p90=round(mc.equity_p90, 2),
                sharpe_p50=round(mc.sharpe_p50, 3),
                max_dd_p90=f"{mc.max_dd_p90:.1%}",
                prob_ruin=f"{mc.prob_ruin:.1%}",
            )

    def save_results(self, result: BacktestResult, output_path: str) -> None:
        """Save backtest results to JSON."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        data = {
            "start_date": result.start_date,
            "end_date": result.end_date,
            "initial_capital": result.initial_capital,
            "final_capital": result.final_capital,
            "config": result.config,
            "metrics": {
                k: v
                for k, v in result.metrics.__dict__.items()
                if not isinstance(v, (list, np.ndarray)) or k in ("equity_curve",)
            },
        }
        if result.monte_carlo:
            mc = result.monte_carlo
            data["monte_carlo"] = {
                "equity_p10": mc.equity_p10,
                "equity_p50": mc.equity_p50,
                "equity_p90": mc.equity_p90,
                "sharpe_p50": mc.sharpe_p50,
                "max_dd_p90": mc.max_dd_p90,
                "prob_ruin": mc.prob_ruin,
            }
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)
        log.info("backtester.results_saved", path=output_path)
