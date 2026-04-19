"""Custom exceptions for QueryKeys bot."""


class QueryKeysError(Exception):
    """Base exception."""


class ConfigError(QueryKeysError):
    """Bad or missing configuration."""


class AuthenticationError(QueryKeysError):
    """API authentication failure."""


class InsufficientFundsError(QueryKeysError):
    """Not enough collateral for order."""


class OrderError(QueryKeysError):
    """Order placement or cancellation failure."""


class MarketNotFoundError(QueryKeysError):
    """Requested market does not exist."""


class RiskLimitExceeded(QueryKeysError):
    """Position would breach risk limits."""


class CircuitBreakerOpen(QueryKeysError):
    """Circuit breaker tripped — trading paused."""


class PredictionError(QueryKeysError):
    """Prediction engine failure."""


class DataFetchError(QueryKeysError):
    """Upstream data fetch failure."""


class BacktestError(QueryKeysError):
    """Backtesting engine failure."""


class StrategyError(QueryKeysError):
    """Strategy plugin error."""
