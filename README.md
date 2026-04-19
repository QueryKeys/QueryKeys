# QueryKeys — Elite Polymarket Prediction & Automated Trading Bot

> The most sophisticated open-source Polymarket trading bot (2026).
> Multi-layer AI ensemble · Institutional risk management · Real-time WebSocket execution · Full backtesting

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                      QUERYKEYS POLYMARKET BOT                        │
└──────────────────────────────────────────────────────────────────────┘

                          ┌─────────────────┐
                          │  config/*.yaml   │
                          │  .env (secrets)  │
                          └────────┬────────┘
                                   │
     ┌─────────────────────────────┼──────────────────────────────┐
     │                             │                              │
┌────▼──────┐               ┌──────▼──────┐              ┌───────▼──────┐
│ DATA LAYER │               │  PREDICTION  │              │   TRADING    │
│            │               │   ENGINE     │              │   ENGINE     │
│ CLOB Client│◄─────────────►│              │◄────────────►│              │
│ Gamma API  │               │ BayesianModel│              │ RiskManager  │
│ Data API   │               │ LightGBM     │              │ KellyCrit.   │
│ WebSocket  │               │ XGBoost      │              │ OrderManager │
│ Sentiment  │               │ CatBoost     │              │ Hedger       │
└────┬───────┘               │ Claude LLM   │              └──────┬───────┘
     │                       │ Calibrator   │                     │
     │                       │ EdgeDetector │                     │
     │                       └──────┬───────┘                     │
     └──────────────────────────────┼─────────────────────────────┘
                                    │
              ┌─────────────────────┴────────────────────┐
              │            CORE INFRASTRUCTURE            │
              │  SQLite/PostgreSQL  │  structlog  │  async│
              └──────┬─────────────────────────────┬──────┘
                     │                             │
              ┌──────▼──────┐             ┌────────▼──────┐
              │ BACKTESTING  │             │  STREAMLIT    │
              │ Walk-forward │             │  DASHBOARD    │
              │ Monte Carlo  │             │  Live P&L     │
              └─────────────┘             └───────────────┘
```

---

## Prediction Engine — 5-Layer Ensemble

| Model | Role | Default Weight |
|-------|------|----------------|
| **Bayesian Beta-Binomial** | Prior + evidence update from price/sentiment/volume | 20% |
| **LightGBM** | Gradient boosting on microstructure + time-series features | 25% |
| **XGBoost** | Diversity via alternative tree structure | 20% |
| **CatBoost** | Categorical-aware boosting | 15% |
| **Claude LLM (Anthropic)** | Deep event analysis, narrative extraction, crowd psychology | 20% |

- **Calibration**: Isotonic regression or Platt scaling per model
- **Dynamic weights**: Brier-score-weighted rebalancing from resolved outcomes
- **Uncertainty quantification**: inter-model std gates trades — high disagreement = no trade
- **Edge detection**: liquidity-adjusted, spread-adjusted net edge computed per signal

---

## Quick Start

### 1. Install

```bash
git clone https://github.com/querykeys/querykeys.git
cd querykeys
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure secrets

```bash
cp .env.example .env
# Fill in POLYMARKET_PRIVATE_KEY and ANTHROPIC_API_KEY at minimum
python scripts/derive_api_keys.py   # auto-derive L2 API keys
```

### 3. Paper trade (safe default)

```bash
python scripts/run_bot.py --mode paper
```

### 4. Dashboard

```bash
python scripts/run_dashboard.py
# http://localhost:8501
```

### 5. Backtest

```bash
python scripts/run_backtest.py
# Results in data/backtest_results.json, visible in Dashboard → Backtest
```

### 6. Train ML models

```bash
# After accumulating resolved market data:
python scripts/train_models.py --data data/historical_markets.json
```

---

## API Keys

| Variable | Source | Required |
|----------|--------|----------|
| `POLYMARKET_PRIVATE_KEY` | Your Polygon EOA private key | Yes |
| `POLYMARKET_API_KEY/SECRET/PASSPHRASE` | `python scripts/derive_api_keys.py` | Yes |
| `ANTHROPIC_API_KEY` | console.anthropic.com | Yes (LLM) |
| `NEWS_API_KEY` | newsapi.org | Optional |
| `OPENAI_API_KEY` | platform.openai.com | Optional fallback |

---

## Docker (Production 24/7)

```bash
cp .env.example .env    # fill in keys
export BOT_MODE=paper   # start safe

cd docker
docker-compose up -d

# Logs
docker-compose logs -f bot

# Dashboard at :8501
```

---

## Configuration

Key settings in `config/config.yaml`:

```yaml
system:
  mode: "paper"           # paper → live when confident

prediction:
  min_edge: 0.03          # trade only with 3%+ edge
  min_confidence: 0.55    # ensemble must agree

risk:
  kelly_fraction: 0.25    # fractional Kelly (conservative)
  max_single_market: 0.10 # 10% of bankroll per market
  max_daily_loss: 0.05    # halt after 5% daily loss
  max_drawdown: 0.20      # 20% total drawdown halt

scanner:
  min_volume_24h: 5000
  categories: ["Politics", "Crypto", "Sports", "Economics"]
```

---

## Adding a Custom Strategy

```python
# src/strategies/my_strategy.py
from src.strategies.base import BaseStrategy

class MyStrategy(BaseStrategy):
    @property
    def name(self) -> str:
        return "my_strategy"

    def should_trade(self, signal: dict) -> bool:
        return signal["net_edge"] > self.params.get("min_edge", 0.03)
```

Enable in `config/strategies.yaml`:
```yaml
- name: "my_strategy"
  enabled: true
  class: "src.strategies.my_strategy.MyStrategy"
  params:
    min_edge: 0.04
```

---

## Project Structure

```
querykeys/
├── config/
│   ├── config.yaml          # Master configuration
│   └── strategies.yaml      # Strategy marketplace
├── src/
│   ├── core/                # Config, DB, logging, exceptions
│   ├── data/                # CLOB client, APIs, WebSocket, sentiment
│   ├── features/            # Feature engineering pipeline
│   ├── prediction/          # Bayesian, ML, LLM, calibration, ensemble
│   ├── trading/             # Kelly, risk, orders, hedger, trader
│   ├── backtesting/         # Walk-forward, Monte Carlo, metrics
│   ├── monitoring/          # Streamlit dashboard
│   └── strategies/          # Strategy marketplace + loader
├── scripts/                 # run_bot, run_backtest, train_models, ...
├── tests/                   # pytest suite
├── docker/                  # Dockerfile + docker-compose
├── .env.example
└── requirements.txt
```

---

## Going Live Checklist

- [ ] Paper trade for ≥ 2 weeks — verify P&L logic
- [ ] Backtest Sharpe > 1.5, max drawdown < 15%
- [ ] Start live with small capital (< $500)
- [ ] Confirm `max_daily_loss` and `max_drawdown` in config
- [ ] Set `ALERT_WEBHOOK_URL` for Slack/Discord alerts
- [ ] Private key secured (never committed to git, ideally in a secrets manager)
- [ ] Monitor dashboard daily

---

## Risk Warning

Prediction market trading involves **substantial risk of loss**. Past backtest
performance does not guarantee future results. The LLM component can produce
incorrect probabilities. Never trade with capital you cannot afford to lose.
This software is provided AS-IS with no warranty.

---

MIT License
