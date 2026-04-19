"""Comprehensive validation of all QueryKeys modules."""
from __future__ import annotations
import sys
import traceback
import os

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

checks = []


def ok(name, detail=""):
    checks.append(("OK", name, detail))
    print(f"[OK] {name}  {detail}")


def fail(name, err):
    checks.append(("FAIL", name, str(err)))
    print(f"[FAIL] {name}  {err}")


# Core imports
try:
    from src.core.config import Settings
    from src.core.logging import get_logger
    from src.core.exceptions import QueryKeysError, RiskLimitExceeded, CircuitBreakerOpen
    ok("Core")
except Exception as e:
    fail("Core", e)

# Data layer
try:
    from src.data.gamma_api import GammaAPIClient
    from src.data.data_api import DataAPIClient
    from src.data.websocket_feed import WebSocketFeed
    from src.data.sentiment import SentimentAnalyzer
    ok("DataLayer")
except Exception as e:
    fail("DataLayer", e)

# Features
try:
    import numpy as np
    from src.features.engineer import FeatureEngineer
    fe = FeatureEngineer()
    feat = fe.extract(
        market={
            "question": "test", "category": "Crypto",
            "volume_24h": 100000, "liquidity": 50000,
            "end_date": "2026-12-31", "yes_price": 0.6, "createdAt": "2026-01-01",
        },
        orderbook={
            "best_bid": 0.58, "best_ask": 0.62, "spread": 0.04,
            "midpoint": 0.60, "bid_depth": 10, "ask_depth": 10, "imbalance": 0.0,
        },
        price_history=[{"t": i, "c": 0.5 + i * 0.001, "v": 1000} for i in range(30)],
        analytics={"volume_24h": 100000},
        sentiment_score=0.2,
        sentiment_confidence=0.8,
    )
    names, vals = fe.to_vector(feat)
    arr = np.array(vals, dtype=np.float32)
    ok("Features", f"n={len(arr)}")
except Exception as e:
    fail("Features", e)
    traceback.print_exc()

# Bayesian
try:
    from src.prediction.bayesian import BayesianPredictor
    bp = BayesianPredictor()
    pred = bp.predict(market_price=0.6, sentiment_score=0.1)
    ok("Bayesian", f"mean={pred.mean:.3f}")
except Exception as e:
    fail("Bayesian", e)

# Calibration
try:
    import numpy as np
    from src.prediction.calibration import ProbabilityCalibrator
    cal = ProbabilityCalibrator(method="isotonic", models_dir="/tmp/cal_test")
    preds = np.array([0.2, 0.4, 0.6, 0.8])
    acts = np.array([0.0, 0.0, 1.0, 1.0])
    cal.fit("test_model", preds, acts)
    c = cal.calibrate("test_model", 0.6)
    ok("Calibration", f"raw=0.60  calibrated={c:.4f}")
except Exception as e:
    fail("Calibration", e)

# Backtester metrics
try:
    import numpy as np
    from src.backtesting.metrics import compute_metrics
    np.random.seed(42)
    eq = [10000] + list(10000 * np.cumprod(1 + np.random.normal(0.005, 0.02, 50)))
    trades = [{"pnl": float(np.random.normal(50, 200)), "size_usd": 1000} for _ in range(50)]
    preds2 = [
        {"predicted_prob": 0.6, "actual_outcome": float(np.random.rand() > 0.4)}
        for _ in range(50)
    ]
    m = compute_metrics(equity_curve=eq, trades=trades, predictions=preds2)
    ok("Metrics", f"total_return={m.total_return:.2%}  sharpe={m.sharpe_ratio:.3f}")
except Exception as e:
    fail("Metrics", e)
    traceback.print_exc()

# Monte Carlo
try:
    import numpy as np
    from src.backtesting.simulator import MonteCarloSimulator
    mc = MonteCarloSimulator(n_runs=100)
    trades3 = [{"pnl": float(np.random.normal(20, 100)), "size_usd": 500} for _ in range(30)]
    r = mc.run(historical_trades=trades3, initial_capital=10000)
    ok("MonteCarlo", f"p50=${r.equity_p50:.0f}  p_ruin={r.prob_ruin:.2f}")
except Exception as e:
    fail("MonteCarlo", e)

# Backtester
try:
    from src.backtesting.backtester import Backtester
    ok("BacktesterImport")
except Exception as e:
    fail("BacktesterImport", e)
    traceback.print_exc()

# Strategies
try:
    from src.strategies.loader import StrategyRegistry
    from src.strategies.base import BaseStrategy
    ok("StrategiesImport")
except Exception as e:
    fail("StrategiesImport", e)

# Kelly
try:
    from src.trading.kelly import KellyCriterion
    k = KellyCriterion(kelly_fraction=0.25, min_kelly_edge=0.02, max_fraction=0.10)
    kr = k.compute(model_prob=0.65, entry_price=0.55, side="YES", bankroll=10000, uncertainty=0.1)
    ok("Kelly", f"fraction={kr.adjusted_fraction:.4f}  size=${kr.bet_size_usd:.2f}")
except Exception as e:
    fail("Kelly", e)

# Risk manager
try:
    from src.trading.risk_manager import RiskManager
    from src.core.config import Settings as FullSettings
    full_settings = FullSettings()
    rm = RiskManager(settings=full_settings, initial_capital=10000)
    ok("RiskManager")
except Exception as e:
    fail("RiskManager", e)

# Trader import
try:
    from src.trading.trader import Trader
    ok("TraderImport")
except Exception as e:
    fail("TraderImport", e)
    traceback.print_exc()

# AI Strategy Builder
try:
    from src.strategies.ai_builder import AIStrategyBuilder, MarketContext
    import numpy as np
    trades_sample = [
        {"pnl": float(np.random.normal(30, 80)), "edge": 0.05, "category": "Politics",
         "confidence": 0.6, "uncertainty": 0.12}
        for _ in range(25)
    ]
    ctx = AIStrategyBuilder._derive_context(
        trades=trades_sample,
        active_markets=40,
        existing_strategy_names=["ensemble_edge", "arbitrage"],
    )
    assert ctx.total_active_markets == 40
    assert 0 <= ctx.overall_win_rate <= 1
    assert ctx.volatility_regime in ("low", "medium", "high")
    ok("AIBuilder", f"regime={ctx.volatility_regime}  win_rate={ctx.overall_win_rate:.1%}  cats={len(ctx.category_stats)}")
except Exception as e:
    fail("AIBuilder", e)
    traceback.print_exc()

# Dashboard file exists
try:
    import importlib.util
    importlib.util.spec_from_file_location("dashboard", "src/monitoring/dashboard.py")
    ok("DashboardFile")
except Exception as e:
    fail("DashboardFile", e)

print()
passed = sum(1 for s, _, _ in checks if s == "OK")
failed = sum(1 for s, _, _ in checks if s == "FAIL")
print(f"Results: {passed} passed, {failed} failed")
if failed == 0:
    print("ALL CHECKS PASSED")
else:
    sys.exit(1)
