# QueryKeys — Elite Polymarket Prediction & Automated Trading Bot

> The most sophisticated open-source Polymarket trading bot.
> Multi-layer AI ensemble · Institutional risk management · Real-time WebSocket execution · AI strategy generation · Full backtesting

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
              ┌─────────────────────┴────────────────────────┐
              │              CORE INFRASTRUCTURE              │
              │  SQLite/PostgreSQL  │  structlog  │  asyncio  │
              └──────┬─────────────────────────────────┬──────┘
                     │                                 │
              ┌──────▼──────┐    ┌──────────────┐  ┌──▼────────────┐
              │ BACKTESTING  │    │  AI STRATEGY  │  │  STREAMLIT    │
              │ Walk-forward │    │   BUILDER     │  │  DASHBOARD    │
              │ Monte Carlo  │    │  (Claude API) │  │  Live P&L     │
              └─────────────┘    └──────────────┘  └───────────────┘
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

## AI Strategy Builder

The AI Strategy Builder uses Claude to automatically generate new Python trading strategies
based on live market conditions and historical performance data.

```bash
# Generate a strategy from DB trade history
python scripts/generate_strategy.py

# Generate with custom market notes
python scripts/generate_strategy.py --notes "Crypto markets are highly volatile this week"

# Dry run — print the prompt without calling Claude
python scripts/generate_strategy.py --dry-run

# Use a specific trade history file
python scripts/generate_strategy.py --trades data/historical_markets_sample.json
```

**What it does:**
1. Analyzes your trade history — per-category win rates, Sharpe, average edge
2. Sends a structured market context to Claude Opus
3. Claude designs a targeted Python strategy class addressing the specific pattern
4. The code is AST-validated and saved to `src/strategies/generated/<name>.py`
5. The strategy is automatically registered in `config/strategies.yaml`
6. Restart the bot to activate the new strategy

**Auto-generation** (optional): Set `ai_builder.auto_generate_interval_hours: 24` in
`config/config.yaml` to have the bot regenerate strategies daily.

---

## Quick Start

### 1. Install dependencies

```bash
git clone https://github.com/querykeys/querykeys.git
cd querykeys
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Set up API keys (see full guide below)

```bash
cp .env.example .env
# Fill in at minimum: POLYMARKET_PRIVATE_KEY and ANTHROPIC_API_KEY
```

### 3. Derive Polymarket L2 keys

```bash
python scripts/derive_api_keys.py
# Paste the output values into your .env file
```

### 4. Validate everything works

```bash
python scripts/validate_system.py
# All 13 checks should pass
```

### 5. Paper trade (safe default — no real money)

```bash
python scripts/run_bot.py --mode paper
```

### 6. Dashboard

```bash
python scripts/run_dashboard.py
# Open http://localhost:8501
```

### 7. Backtest

```bash
python scripts/run_backtest.py
# Results → data/backtest_results.json → visible in Dashboard → Backtest tab
```

### 8. Generate an AI strategy

```bash
python scripts/generate_strategy.py
```

---

## Full API Setup Guide

### 1. Polymarket (Required — for trading)

Polymarket uses a two-level key system:
- **L1 key**: your Ethereum private key (signs transactions)
- **L2 keys**: API key/secret/passphrase (signs API requests, derived from L1)

**Step-by-step:**

1. **Create a Polygon wallet**

   Option A — MetaMask (browser extension):
   - Install MetaMask at [metamask.io](https://metamask.io)
   - Create a new wallet → save the seed phrase securely
   - Switch network to **Polygon Mainnet** (Chain ID 137)
   - Export private key: MetaMask → three-dot menu → Account Details → Export Private Key
   - The key is 64 hex characters (may have `0x` prefix — that's fine)

   Option B — Generate a fresh dedicated wallet (recommended for bots):
   ```bash
   python -c "
   from eth_account import Account
   import secrets
   key = secrets.token_hex(32)
   acct = Account.from_key('0x' + key)
   print('Private key:', '0x' + key)
   print('Address:', acct.address)
   "
   ```

2. **Fund the wallet with USDC on Polygon**
   - Bridge USDC from Ethereum to Polygon via [Polygon Bridge](https://wallet.polygon.technology/polygon/bridge)
   - Or buy MATIC/USDC directly on Polygon via Binance, Coinbase, etc.
   - Minimum recommended: $100 USDC for initial testing

3. **Create a Polymarket account**
   - Go to [polymarket.com](https://polymarket.com)
   - Connect your MetaMask wallet
   - Approve USDC spending in the Polymarket interface at least once

4. **Derive L2 API keys**
   ```bash
   # Set your L1 key first:
   echo 'POLYMARKET_PRIVATE_KEY=0xyour64hexkey' >> .env

   # Then derive L2 keys automatically:
   python scripts/derive_api_keys.py
   ```
   Copy the printed `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET`,
   `POLYMARKET_API_PASSPHRASE` into your `.env` file.

5. **Set in `.env`**:
   ```
   POLYMARKET_PRIVATE_KEY=0x<your-64-hex-private-key>
   POLYMARKET_API_KEY=<derived>
   POLYMARKET_API_SECRET=<derived>
   POLYMARKET_API_PASSPHRASE=<derived>
   ```

> **Security**: Never commit your private key to git. The `.gitignore` already
> excludes `.env`. Consider using a secrets manager (AWS Secrets Manager,
> HashiCorp Vault) for production deployments.

---

### 2. Anthropic / Claude API (Required — for LLM predictions + AI strategy builder)

The bot uses Claude for:
- Market event analysis and probability elicitation (prediction ensemble)
- AI strategy generation (`scripts/generate_strategy.py`)

**Step-by-step:**

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Sign up or log in
3. Navigate to **API Keys** in the left sidebar
4. Click **Create Key** → give it a name (e.g. "querykeys-bot")
5. Copy the key (starts with `sk-ant-api03-...`) — it is only shown once

6. **Set in `.env`**:
   ```
   ANTHROPIC_API_KEY=sk-ant-api03-...
   ```

**Models used** (configured in `config/config.yaml`):
```yaml
prediction:
  llm:
    model: "claude-opus-4-7"        # main prediction model
    fallback_model: "claude-sonnet-4-6"

ai_builder:
  model: "claude-opus-4-7"          # strategy generation model
```

**Cost estimate**: ~$5–15/day at full trading activity with prompt caching enabled.
The bot uses `cache_control: ephemeral` on system prompts to reduce costs ~60%.

---

### 3. News API (Optional — for sentiment analysis)

Used to fetch news articles for VADER sentiment scoring.

**Step-by-step:**

1. Go to [newsapi.org](https://newsapi.org)
2. Click **Get API Key** → register a free account
3. Free tier: **100 requests/day** (sufficient for light use)
4. Paid plans: Developer ($449/mo) for production volume
5. Copy your API key from the dashboard

6. **Set in `.env`**:
   ```
   NEWS_API_KEY=your_newsapi_key_here
   ```

> If `NEWS_API_KEY` is not set, the sentiment module falls back to Reddit only.
> Sentiment is optional — the bot trades without it if both sources are unavailable.

---

### 4. Reddit API (Optional — for sentiment analysis)

Used to fetch Reddit posts/comments for community sentiment signals.

**Step-by-step:**

1. Log in to [reddit.com](https://reddit.com)
2. Go to [reddit.com/prefs/apps](https://reddit.com/prefs/apps)
3. Scroll down and click **Create App** (or "Create Another App")
4. Fill in:
   - **Name**: `querykeys-sentiment` (any name)
   - **App type**: select **script**
   - **Redirect URI**: `http://localhost:8080` (not actually used)
5. Click **Create App**
6. You'll see:
   - **Client ID**: the string under your app name (14 chars)
   - **Client Secret**: the string labeled "secret"

7. **Set in `.env`**:
   ```
   REDDIT_CLIENT_ID=your_14_char_client_id
   REDDIT_CLIENT_SECRET=your_secret_here
   REDDIT_USER_AGENT=QueryKeys/1.0 (by u/your_reddit_username)
   ```

> The Reddit API free tier allows ~60 requests/minute — more than enough.
> Subreddits monitored: r/politics, r/crypto, r/sportsbook (configurable).

---

### 5. PostgreSQL (Optional — replaces SQLite for production)

SQLite is the default and works fine for a single bot instance.
Switch to PostgreSQL for multi-instance deployments or heavy write loads.

**Step-by-step (local):**

```bash
# Install PostgreSQL
sudo apt-get install postgresql  # Ubuntu/Debian
brew install postgresql          # macOS

# Create DB and user
sudo -u postgres psql <<EOF
CREATE DATABASE querykeys;
CREATE USER qkbot WITH PASSWORD 'strong_password_here';
GRANT ALL PRIVILEGES ON DATABASE querykeys TO qkbot;
EOF
```

**Set in `.env`**:
```
DATABASE_URL=postgresql+asyncpg://qkbot:strong_password_here@localhost:5432/querykeys
```

**Via Docker** (easiest):
```bash
docker run -d \
  --name querykeys-pg \
  -e POSTGRES_DB=querykeys \
  -e POSTGRES_USER=qkbot \
  -e POSTGRES_PASSWORD=strong_password_here \
  -p 5432:5432 \
  postgres:15
```

---

### 6. All environment variables reference

```bash
# ── Required ──────────────────────────────────────────────────────────
POLYMARKET_PRIVATE_KEY=0x<64-hex-chars>          # Ethereum/Polygon L1 private key
POLYMARKET_API_KEY=<derived-via-script>           # Polymarket L2 API key
POLYMARKET_API_SECRET=<derived-via-script>        # Polymarket L2 secret
POLYMARKET_API_PASSPHRASE=<derived-via-script>    # Polymarket L2 passphrase
ANTHROPIC_API_KEY=sk-ant-api03-...               # Claude API key

# ── Optional: sentiment ───────────────────────────────────────────────
NEWS_API_KEY=<newsapi.org key>
REDDIT_CLIENT_ID=<14-char string>
REDDIT_CLIENT_SECRET=<secret>
REDDIT_USER_AGENT=QueryKeys/1.0 (by u/yourname)

# ── Optional: database ────────────────────────────────────────────────
DATABASE_URL=sqlite:///data/querykeys.db          # default (SQLite)
# DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/querykeys

# ── Optional: operational ─────────────────────────────────────────────
BOT_MODE=paper                                    # paper | live
LOG_LEVEL=INFO                                    # DEBUG | INFO | WARNING
ALERT_WEBHOOK_URL=https://hooks.slack.com/...     # Slack / Discord webhook
```

---

## Docker (Production 24/7)

```bash
cp .env.example .env    # fill in all required keys
export BOT_MODE=paper   # always start in paper mode first

cd docker
docker-compose up -d

# Tail logs
docker-compose logs -f bot

# Dashboard at http://localhost:8501
# Stop
docker-compose down
```

The `docker-compose.yml` starts three services:
| Service | Port | Description |
|---------|------|-------------|
| `bot` | — | Main trading bot |
| `dashboard` | 8501 | Streamlit dashboard |
| `postgres` | 5432 | PostgreSQL (optional, replaces SQLite) |

---

## Configuration

Key settings in `config/config.yaml`:

```yaml
system:
  mode: "paper"           # paper → live when confident

prediction:
  min_edge: 0.03          # trade only with 3%+ edge
  min_confidence: 0.55    # ensemble must agree
  uncertainty_threshold: 0.15   # high disagreement = skip

risk:
  kelly_fraction: 0.25    # fractional Kelly (conservative)
  max_single_market: 0.10 # 10% of bankroll per market
  max_daily_loss: 0.05    # halt after 5% daily loss
  max_drawdown: 0.20      # 20% total drawdown halt

scanner:
  min_volume_24h: 5000
  categories: ["Politics", "Crypto", "Sports", "Economics"]

ai_builder:
  enabled: true
  auto_generate_interval_hours: 24    # 0 = manual only
  min_trades_for_generation: 20
```

---

## Adding a Custom Strategy Manually

```python
# src/strategies/my_strategy.py
from src.strategies.base import BaseStrategy
from typing import Dict, Optional

class MyStrategy(BaseStrategy):
    @property
    def name(self) -> str:
        return "my_strategy"

    def should_trade(self, signal: Dict) -> bool:
        return (
            signal["net_edge"] > self.params.get("min_edge", 0.04)
            and signal["confidence"] > self.params.get("min_confidence", 0.60)
            and signal.get("category") in self.params.get("categories", ["Politics"])
        )

    def size_override(self, signal: Dict, bankroll: float) -> Optional[float]:
        return None  # use default Kelly sizing
```

Enable in `config/strategies.yaml`:
```yaml
- name: "my_strategy"
  enabled: true
  class: "src.strategies.my_strategy.MyStrategy"
  params:
    min_edge: 0.04
    min_confidence: 0.60
    categories: ["Politics", "Economics"]
```

---

## Project Structure

```
querykeys/
├── config/
│   ├── config.yaml              # Master configuration
│   └── strategies.yaml          # Strategy marketplace
├── src/
│   ├── core/                    # Config, DB, logging, exceptions
│   ├── data/                    # CLOB client, Gamma/Data APIs, WebSocket, sentiment
│   ├── features/                # 38-feature engineering pipeline
│   ├── prediction/              # Bayesian, LightGBM, XGBoost, CatBoost, LLM,
│   │                            #   calibration, edge detector, ensemble
│   ├── trading/                 # Kelly, risk manager, order manager, hedger, trader
│   ├── backtesting/             # Walk-forward, Monte Carlo, metrics
│   ├── monitoring/              # Streamlit dashboard (6 pages)
│   └── strategies/
│       ├── base.py              # BaseStrategy ABC
│       ├── ensemble_edge.py     # Primary ensemble strategy
│       ├── sentiment_momentum.py
│       ├── arbitrage.py
│       ├── mean_reversion.py
│       ├── ai_builder.py        # AI strategy generator (Claude)
│       ├── loader.py            # Dynamic YAML registry
│       └── generated/           # AI-generated strategies (auto-created)
├── scripts/
│   ├── run_bot.py               # Main entry point
│   ├── run_backtest.py
│   ├── run_dashboard.py
│   ├── train_models.py
│   ├── derive_api_keys.py       # Derive Polymarket L2 keys
│   ├── generate_strategy.py     # AI strategy builder CLI
│   └── validate_system.py       # 13-check health test
├── tests/                       # pytest suite (22 tests)
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── data/
│   ├── historical_markets_sample.json
│   └── .gitkeep
├── models/                      # Trained ML model files (.pkl)
├── logs/
├── .env.example
├── requirements.txt
└── conftest.py
```

---

## Going Live Checklist

- [ ] Paper trade for ≥ 2 weeks — verify P&L logic matches expectations
- [ ] Backtest Sharpe > 1.5, max drawdown < 15%
- [ ] Run `python scripts/validate_system.py` — all 13 checks green
- [ ] Start live with small capital (< $500 USDC)
- [ ] Confirm `max_daily_loss: 0.05` and `max_drawdown: 0.20` are set in config
- [ ] Set `ALERT_WEBHOOK_URL` for Slack/Discord notifications
- [ ] Private key stored securely — never in git, ideally in a secrets manager
- [ ] Monitor dashboard daily at http://localhost:8501
- [ ] Generate initial AI strategies: `python scripts/generate_strategy.py`

---

## Risk Warning

Prediction market trading involves **substantial risk of loss**. Past backtest
performance does not guarantee future results. The LLM component can produce
incorrect probabilities. AI-generated strategies are experimental — backtest
them before enabling. Never trade with capital you cannot afford to lose.
This software is provided AS-IS with no warranty.

---

MIT License
