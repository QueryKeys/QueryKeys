"""
Performance metrics for backtesting results.

Computes:
  - Sharpe, Sortino, Calmar ratios
  - Maximum drawdown, drawdown duration
  - Win rate, profit factor, expectancy
  - Brier score for probability calibration
  - Kelly growth rate
  - Information ratio
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np


@dataclass
class BacktestMetrics:
    # Returns
    total_return: float
    annualized_return: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float

    # Drawdown
    max_drawdown: float
    max_drawdown_duration_days: float
    avg_drawdown: float

    # Trade stats
    num_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    expectancy: float

    # Calibration
    brier_score: float
    avg_edge: float
    avg_kelly_fraction: float

    # Risk-adjusted
    information_ratio: float
    kelly_growth_rate: float

    # Raw data
    equity_curve: List[float] = field(default_factory=list)
    daily_returns: List[float] = field(default_factory=list)


def compute_metrics(
    equity_curve: List[float],
    trades: List[dict],
    predictions: List[dict],
    risk_free_rate: float = 0.05,
    periods_per_year: int = 252,
) -> BacktestMetrics:
    """
    Compute comprehensive performance metrics from backtest results.

    equity_curve: list of portfolio values at each time step
    trades: list of {pnl, entry_price, model_prob, actual_outcome, side}
    predictions: list of {predicted_prob, actual_outcome}
    """
    eq = np.array(equity_curve, dtype=float)
    if len(eq) < 2:
        return _empty_metrics(equity_curve)

    # Daily returns
    daily_returns = np.diff(eq) / eq[:-1]
    total_return = (eq[-1] / eq[0]) - 1.0

    # Annualized return
    n_days = len(eq)
    ann_return = (1 + total_return) ** (periods_per_year / max(n_days, 1)) - 1

    # Sharpe ratio
    excess_returns = daily_returns - risk_free_rate / periods_per_year
    sharpe = (
        float(np.mean(excess_returns) / (np.std(excess_returns) + 1e-10))
        * math.sqrt(periods_per_year)
    )

    # Sortino ratio (only downside volatility)
    downside = daily_returns[daily_returns < 0]
    sortino_denom = float(np.std(downside)) if len(downside) > 1 else 1e-10
    sortino = (
        float(np.mean(excess_returns) / (sortino_denom + 1e-10))
        * math.sqrt(periods_per_year)
    )

    # Drawdown
    running_max = np.maximum.accumulate(eq)
    drawdowns = (running_max - eq) / running_max
    max_dd = float(np.max(drawdowns))
    avg_dd = float(np.mean(drawdowns))

    # Drawdown duration
    in_dd = drawdowns > 0.01
    max_dd_dur = _max_consecutive(in_dd)

    # Calmar ratio
    calmar = ann_return / max(max_dd, 1e-6)

    # Trade stats
    pnls = [float(t.get("pnl", 0)) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate = len(wins) / max(len(pnls), 1)
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    profit_factor = (
        sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else float("inf")
    )
    expectancy = float(np.mean(pnls)) if pnls else 0.0

    # Brier score
    brier = 0.0
    if predictions:
        brier = float(
            np.mean(
                [
                    (p.get("predicted_prob", 0.5) - p.get("actual_outcome", 0.5)) ** 2
                    for p in predictions
                ]
            )
        )

    avg_edge = float(np.mean([t.get("edge", 0) for t in trades])) if trades else 0.0
    avg_kelly = float(np.mean([t.get("kelly_fraction", 0) for t in trades])) if trades else 0.0

    # Information ratio (mean/std of excess returns)
    ir = float(np.mean(excess_returns) / (np.std(excess_returns) + 1e-10)) * math.sqrt(
        periods_per_year
    )

    # Kelly growth rate approximation
    if trades:
        avg_p = float(np.mean([t.get("model_prob", 0.5) for t in trades]))
        avg_price = float(np.mean([t.get("entry_price", 0.5) for t in trades]))
        b = (1 - avg_price) / max(avg_price, 0.01)
        q = 1 - avg_p
        kg = avg_p * math.log(1 + b * avg_kelly) + q * math.log(1 - avg_kelly) if avg_kelly > 0 else 0.0
    else:
        kg = 0.0

    return BacktestMetrics(
        total_return=total_return,
        annualized_return=ann_return,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        max_drawdown=max_dd,
        max_drawdown_duration_days=float(max_dd_dur),
        avg_drawdown=avg_dd,
        num_trades=len(trades),
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        profit_factor=profit_factor,
        expectancy=expectancy,
        brier_score=brier,
        avg_edge=avg_edge,
        avg_kelly_fraction=avg_kelly,
        information_ratio=ir,
        kelly_growth_rate=kg,
        equity_curve=list(eq),
        daily_returns=list(daily_returns),
    )


def _max_consecutive(arr: np.ndarray) -> int:
    max_run = cur_run = 0
    for v in arr:
        if v:
            cur_run += 1
            max_run = max(max_run, cur_run)
        else:
            cur_run = 0
    return max_run


def _empty_metrics(equity_curve: List[float]) -> BacktestMetrics:
    return BacktestMetrics(
        total_return=0.0, annualized_return=0.0, sharpe_ratio=0.0,
        sortino_ratio=0.0, calmar_ratio=0.0, max_drawdown=0.0,
        max_drawdown_duration_days=0.0, avg_drawdown=0.0, num_trades=0,
        win_rate=0.0, avg_win=0.0, avg_loss=0.0, profit_factor=0.0,
        expectancy=0.0, brier_score=0.5, avg_edge=0.0, avg_kelly_fraction=0.0,
        information_ratio=0.0, kelly_growth_rate=0.0,
        equity_curve=equity_curve, daily_returns=[],
    )
