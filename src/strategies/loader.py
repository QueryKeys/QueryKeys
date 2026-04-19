"""
Strategy marketplace loader.

Dynamically loads strategy classes from config/strategies.yaml,
instantiates them with their params, and provides a registry.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

from src.core.logging import get_logger
from src.strategies.base import BaseStrategy

log = get_logger(__name__)


class StrategyRegistry:
    """Loads and manages all active strategies."""

    def __init__(self, config_path: str = "config/strategies.yaml") -> None:
        self._strategies: Dict[str, BaseStrategy] = {}
        self._config_path = config_path

    def load(self) -> None:
        """Load all enabled strategies from YAML config."""
        path = Path(self._config_path)
        if not path.exists():
            log.warning("strategy_registry.config_not_found", path=str(path))
            return

        with open(path) as f:
            cfg = yaml.safe_load(f) or {}

        for strat_cfg in cfg.get("strategies", []):
            if not strat_cfg.get("enabled", False):
                continue
            name = strat_cfg["name"]
            cls_path = strat_cfg["class"]
            params = strat_cfg.get("params", {})

            try:
                module_path, cls_name = cls_path.rsplit(".", 1)
                module = importlib.import_module(module_path)
                cls = getattr(module, cls_name)
                instance: BaseStrategy = cls(params)
                self._strategies[name] = instance
                log.info("strategy_registry.loaded", name=name)
            except Exception as exc:
                log.error("strategy_registry.load_failed", name=name, error=str(exc))

    def get_all(self) -> List[BaseStrategy]:
        return list(self._strategies.values())

    def get(self, name: str) -> BaseStrategy:
        return self._strategies[name]

    def should_any_trade(self, signal: Dict) -> bool:
        """Return True if any enabled strategy approves this signal."""
        return any(s.should_trade(signal) for s in self._strategies.values())

    def get_size_override(
        self, signal: Dict, bankroll: float
    ) -> float | None:
        """
        Return the smallest approved size from all strategies,
        or None if no strategy overrides.
        """
        overrides = []
        for s in self._strategies.values():
            if s.should_trade(signal):
                override = s.size_override(signal, bankroll)
                if override is not None:
                    overrides.append(override)
        return min(overrides) if overrides else None
