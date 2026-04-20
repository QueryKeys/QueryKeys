"""
Configuration loader — merges YAML config with environment variables.
Provides a single validated Settings object used everywhere in the bot.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator

from src.core.exceptions import ConfigError

load_dotenv()

# ---------------------------------------------------------------------------
# Pydantic settings models
# ---------------------------------------------------------------------------


class SystemSettings(BaseModel):
    mode: str = "paper"
    log_level: str = "INFO"
    db_url: str = "sqlite:///data/querykeys.db"
    data_dir: str = "data"
    models_dir: str = "models"

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        if v not in {"live", "paper", "backtest"}:
            raise ValueError(f"mode must be live|paper|backtest, got {v!r}")
        return v


class PolymarketSettings(BaseModel):
    clob_api_url: str = "https://clob.polymarket.com"
    gamma_api_url: str = "https://gamma-api.polymarket.com"
    data_api_url: str = "https://data-api.polymarket.com"
    neg_risk_adapter: str = "0xd91E80cF2eA078D68776e2f8FE25Dea05D80b5E5"
    chain_id: int = 137
    signature_type: int = 0
    funder: str = ""
    tick_size: float = 0.01

    # Injected from environment
    private_key: str = ""
    api_key: str = ""
    api_secret: str = ""
    api_passphrase: str = ""

    @model_validator(mode="after")
    def inject_env(self) -> "PolymarketSettings":
        self.private_key = os.getenv("POLYMARKET_PRIVATE_KEY", self.private_key)
        self.api_key = os.getenv("POLYMARKET_API_KEY", self.api_key)
        self.api_secret = os.getenv("POLYMARKET_API_SECRET", self.api_secret)
        self.api_passphrase = os.getenv("POLYMARKET_API_PASSPHRASE", self.api_passphrase)
        return self


class WebSocketSettings(BaseModel):
    clob_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/"
    reconnect_delay: int = 5
    ping_interval: int = 30
    max_reconnects: int = 10


class ScannerSettings(BaseModel):
    min_volume_24h: float = 5000
    min_liquidity: float = 2000
    min_days_to_expiry: int = 1
    max_days_to_expiry: int = 90
    max_markets: int = 100
    categories: List[str] = Field(default_factory=list)
    rescan_interval: int = 300


class LLMSettings(BaseModel):
    model: str = "llama-3.3-70b-versatile"
    max_tokens: int = 1024
    temperature: float = 0.1
    fallback_model: str = "mixtral-8x7b-32768"
    cache_ttl: int = 3600


class PredictionSettings(BaseModel):
    ensemble_weights: Dict[str, float] = Field(
        default_factory=lambda: {
            "bayesian": 0.20,
            "lgbm": 0.25,
            "xgboost": 0.20,
            "catboost": 0.15,
            "llm": 0.20,
        }
    )
    min_confidence: float = 0.55
    min_edge: float = 0.03
    calibration_method: str = "isotonic"
    uncertainty_threshold: float = 0.15
    llm: LLMSettings = Field(default_factory=LLMSettings)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "PredictionSettings":
        total = sum(self.ensemble_weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"ensemble_weights must sum to 1.0, got {total}")
        return self


class SentimentSettings(BaseModel):
    enabled: bool = True
    sources: List[str] = Field(default_factory=lambda: ["newsapi"])
    window_hours: int = 24
    min_articles: int = 3


class RiskSettings(BaseModel):
    max_portfolio_exposure: float = 0.80
    max_single_market: float = 0.10
    max_category_exposure: float = 0.30
    max_daily_loss: float = 0.05
    max_drawdown: float = 0.20
    kelly_fraction: float = 0.25
    min_kelly_edge: float = 0.01
    correlation_penalty: bool = True
    circuit_breaker_loss: float = 0.03


class ExecutionSettings(BaseModel):
    default_order_type: str = "limit"
    slippage_tolerance: float = 0.005
    max_spread_pct: float = 0.05
    min_order_size: float = 5.0
    max_order_size: float = 500.0
    order_timeout: int = 60
    retry_attempts: int = 3
    retry_delay: int = 2


class BacktestSettings(BaseModel):
    start_date: str = "2024-01-01"
    end_date: str = "2025-12-31"
    initial_capital: float = 10000.0
    commission: float = 0.0
    monte_carlo_runs: int = 1000
    walk_forward_folds: int = 5


class DashboardSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8501
    refresh_interval: int = 5
    alert_email: str = ""
    alert_webhook: str = ""

    @model_validator(mode="after")
    def inject_env(self) -> "DashboardSettings":
        self.alert_webhook = os.getenv("ALERT_WEBHOOK_URL", self.alert_webhook)
        self.alert_email = os.getenv("ALERT_EMAIL", self.alert_email)
        return self


class RateLimitSettings(BaseModel):
    gamma_api_rps: int = 10
    data_api_rps: int = 10
    clob_api_rps: int = 20
    llm_api_rpm: int = 30


class Settings(BaseModel):
    """Root settings object; singleton accessed via get_settings()."""

    system: SystemSettings = Field(default_factory=SystemSettings)
    polymarket: PolymarketSettings = Field(default_factory=PolymarketSettings)
    websocket: WebSocketSettings = Field(default_factory=WebSocketSettings)
    scanner: ScannerSettings = Field(default_factory=ScannerSettings)
    prediction: PredictionSettings = Field(default_factory=PredictionSettings)
    sentiment: SentimentSettings = Field(default_factory=SentimentSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    backtesting: BacktestSettings = Field(default_factory=BacktestSettings)
    dashboard: DashboardSettings = Field(default_factory=DashboardSettings)
    rate_limits: RateLimitSettings = Field(default_factory=RateLimitSettings)

    # Runtime extras injected after load
    groq_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    news_api_key: str = ""

    @model_validator(mode="after")
    def inject_runtime_env(self) -> "Settings":
        self.groq_api_key = os.getenv("GROQ_API_KEY", "")
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.news_api_key = os.getenv("NEWS_API_KEY", "")
        return self


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open() as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def get_settings(config_path: str = "config/config.yaml") -> Settings:
    """Load and cache settings from YAML + environment variables."""
    raw = _load_yaml(Path(config_path))
    try:
        return Settings(**raw)
    except Exception as exc:
        raise ConfigError(f"Invalid configuration: {exc}") from exc
