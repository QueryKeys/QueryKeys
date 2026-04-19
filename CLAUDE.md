# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run all tests
pytest tests/

# Run a single test file
pytest tests/test_kelly.py

# Run a single test by name
pytest tests/test_kelly.py::test_positive_edge_yes -v

# Run tests with async support (already configured via pytest-asyncio)
pytest tests/ -v

# Run the bot in paper mode (safe default)
python scripts/run_bot.py --mode paper

# Run the bot in backtest mode
python scripts/run_bot.py --mode backtest

# Launch Streamlit dashboard (http://localhost:8501)
python scripts/run_dashboard.py

# Run backtest (outputs to data/backtest_results.json)
python scripts/run_backtest.py

# Train ML models from historical data
python scripts/train_models.py --data data/historical_markets.json

# Derive Polymarket L2 API credentials from private key
python scripts/derive_api_keys.py
```

## Environment Setup

Copy `.env.example` to `.env` and fill in at minimum:
- `POLYMARKET_PRIVATE_KEY` — Polygon EOA private key
- `POLYMARKET_API_KEY` / `POLYMARKET_API_SECRET` / `POLYMARKET_API_PASSPHRASE` — from `derive_api_keys.py`
- `ANTHROPIC_API_KEY` — required for the LLM predictor

## Architecture

### Data Flow

```
Polymarket APIs + WebSocket
        ↓
FeatureEngineer (microstructure, time-series, sentiment features)
        ↓
PredictorEnsemble (5 models in parallel)
        ↓
EdgeDetector (liquidity/spread-adjusted edge computation)
        ↓
RiskManager + KellyCriterion (position sizing and risk checks)
        ↓
OrderManager (limit/market order submission via CLOB)
        ↓
DatabaseManager (SQLAlchemy async, SQLite or PostgreSQL)
```

### Configuration System

`src/core/config.py` defines a `Settings` Pydantic model that merges `config/config.yaml` with environment variables. Secrets (API keys, private key) are injected exclusively via environment; YAML holds non-secret tuning parameters. Access the settings singleton anywhere with `get_settings()` (LRU-cached). Changing `config/config.yaml` at runtime requires restarting the bot.

### Prediction Ensemble (`src/prediction/`)

Five models produce independent probability estimates that are weighted and combined:

| Model | File | Notes |
|-------|------|-------|
| Bayesian Beta-Binomial | `bayesian.py` | Prior + evidence; no training required |
| LightGBM / XGBoost / CatBoost | `ml_models.py` | Loaded from `models/` dir; fall back to untrained defaults |
| Claude LLM | `llm_predictor.py` | Async Claude API call; uses prompt caching; falls back to OpenAI |

`ensemble.py` orchestrates all five, applies per-model isotonic/Platt calibration (`calibration.py`), computes weighted average, and gates trades on `uncertainty_threshold` (inter-model std). Dynamic weight rebalancing via inverse Brier score runs after resolved outcomes accumulate.

### Trading Engine (`src/trading/`)

- **`trader.py`** (`Trader`) — central orchestrator; runs 5 concurrent async loops: market scanner, analysis, order sync, portfolio snapshot, WebSocket feed.
- **`risk_manager.py`** (`RiskManager`) — in-memory `PortfolioState`; raises `CircuitBreakerOpen` when daily loss or drawdown limits are hit; enforces per-market, per-category, and portfolio exposure caps.
- **`kelly.py`** (`KellyCriterion`) — fractional Kelly sizing with uncertainty penalty and max-fraction cap; `compute_portfolio_kelly()` for multi-opportunity batches.
- **`order_manager.py`** (`OrderManager`) — submits/cancels orders via `PolymarketClient`; polls fill status; fires `on_fill` callbacks.
- **`hedger.py`** — correlation-based hedge computation; called optionally from `Trader`.

### Strategy Marketplace (`src/strategies/`)

Strategies are YAML-configured plugins loaded dynamically by `loader.py`. Each must subclass `BaseStrategy` and implement `should_trade(signal) -> bool`. The `signal` dict contains: `condition_id`, `side`, `edge`, `net_edge`, `confidence`, `uncertainty`, `model_prob`, `market_price`, `kelly_fraction`. Optionally override `size_override()` to replace Kelly sizing. Register new strategies in `config/strategies.yaml` — no code changes needed elsewhere.

### Data Layer (`src/data/`)

- `polymarket_client.py` — CLOB API wrapper (orders, positions, auth)
- `gamma_api.py` — market discovery and scanning
- `data_api.py` — price history, analytics
- `websocket_feed.py` — real-time orderbook; fires `price_change` / `book` events consumed by `Trader`
- `sentiment.py` — VADER + NewsAPI/Reddit; returns `SentimentResult(score, confidence, query)`

### Database (`src/core/database.py`)

SQLAlchemy 2.x async ORM. Tables: `markets`, `orderbook_snapshots`, `predictions`, `signals`, `orders`, `positions`, `portfolio_snapshots`, `backtest_results`, `model_performance`. Default is SQLite (`data/querykeys.db`); switch to PostgreSQL by setting `db_url` in config or environment.

### Backtesting (`src/backtesting/`)

- `backtester.py` — walk-forward folds + Monte Carlo simulation
- `simulator.py` — order fill simulation with slippage model
- `metrics.py` — Sharpe, Calmar, Sortino, max drawdown

### Key Invariants

- `ensemble_weights` in config must sum to exactly 1.0 (validated by Pydantic).
- `system.mode` must be `paper | live | backtest` — `paper` never submits real orders.
- The LLM predictor uses prompt caching (Anthropic `cache_control` headers); the system prompt is marked as cacheable to reduce latency and cost.
- `CircuitBreakerOpen` and `RiskLimitExceeded` are the canonical exceptions for blocked trades; catch only these when handling risk rejections.
- ML models are persisted under `models/` and loaded at startup via `load_or_create(feature_names)`. If no saved model exists, the predictors return 0.5 as a neutral prior until training data is available.
