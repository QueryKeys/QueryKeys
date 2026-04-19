"""
AI Strategy Builder — uses Claude to generate trading strategies from market conditions.

Flow:
  1. Collect MarketContext (category stats, recent P&L, win rates, volatility regime)
  2. Send to Claude with BaseStrategy interface + existing examples as context
  3. Claude returns JSON with strategy name, description, Python class code, params
  4. AST-validate the code; reject if it doesn't parse or doesn't extend BaseStrategy
  5. Write to src/strategies/generated/<name>.py
  6. Append entry to config/strategies.yaml so StrategyRegistry picks it up
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import json
import re
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import anthropic

from src.core.config import Settings
from src.core.logging import get_logger
from src.strategies.base import BaseStrategy

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CategoryStat:
    category: str
    num_trades: int
    win_rate: float       # 0–1
    avg_edge: float       # mean edge at entry
    avg_pnl: float        # mean dollar P&L per trade
    sharpe: float


@dataclass
class MarketContext:
    """Snapshot of current trading environment fed to the AI builder."""
    timestamp: str
    total_active_markets: int
    category_stats: List[CategoryStat]
    overall_win_rate: float
    overall_sharpe: float
    max_drawdown: float
    avg_uncertainty: float        # mean ensemble uncertainty
    avg_confidence: float         # mean ensemble confidence
    avg_edge: float               # mean net edge across all signals
    volatility_regime: str        # "low" | "medium" | "high"
    dominant_category: str        # highest-volume category
    underperforming_categories: List[str]
    outperforming_categories: List[str]
    existing_strategy_names: List[str]
    recent_notes: str = ""        # free-text observations


@dataclass
class GeneratedStrategy:
    name: str
    description: str
    code: str
    params: Dict[str, Any]
    rationale: str
    expected_edge_range: str
    file_path: str
    yaml_entry: str


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert quantitative strategy designer specializing in prediction markets (Polymarket).

You will receive a JSON snapshot of current market conditions, recent performance statistics,
and a list of strategies already in use. Your task is to design ONE new trading strategy that
exploits a specific pattern or edge visible in the data.

## BaseStrategy interface (must be extended)

```python
from src.strategies.base import BaseStrategy
from typing import Any, Dict, Optional

class MyStrategy(BaseStrategy):
    @property
    def name(self) -> str:
        return "unique_snake_case_name"   # must be unique

    def should_trade(self, signal: Dict) -> bool:
        # signal keys: condition_id, side, edge, net_edge, confidence,
        #              uncertainty, model_prob, market_price, kelly_fraction,
        #              category, dte_days, volume_24h, liquidity
        return True / False

    def size_override(self, signal: Dict, bankroll: float) -> Optional[float]:
        # return None to use default Kelly sizing
        return None
```

## Rules
- The class MUST extend `BaseStrategy` from `src.strategies.base`
- `name` must be a unique snake_case string not in `existing_strategy_names`
- `should_trade` must return a bool
- Do NOT import anything other than standard library + `src.strategies.base.BaseStrategy`
- Keep logic simple and readable; no external API calls
- Be specific: target a concrete, data-supported edge (not "trade everything")
- Params must be configurable via `self.params.get(...)`

## Response format (JSON only, no markdown fences)
{
  "name": "strategy_snake_case_name",
  "description": "One-sentence summary",
  "rationale": "2-3 sentences explaining what edge this exploits and why the data supports it",
  "expected_edge_range": "e.g. 3–6%",
  "params": { "param_name": default_value, ... },
  "code": "full Python source of the class, including all imports"
}
"""


def _build_user_prompt(context: MarketContext) -> str:
    cat_stats_txt = "\n".join(
        f"  - {s.category}: win_rate={s.win_rate:.1%}, avg_edge={s.avg_edge:.3f}, "
        f"sharpe={s.sharpe:.2f}, trades={s.num_trades}"
        for s in context.category_stats
    )
    return f"""\
## Current Market Context

Timestamp: {context.timestamp}
Active markets: {context.total_active_markets}
Overall win rate: {context.overall_win_rate:.1%}
Overall Sharpe: {context.overall_sharpe:.2f}
Max drawdown: {context.max_drawdown:.1%}
Avg ensemble uncertainty: {context.avg_uncertainty:.3f}
Avg ensemble confidence: {context.avg_confidence:.3f}
Avg net edge: {context.avg_edge:.3f}
Volatility regime: {context.volatility_regime}
Dominant category: {context.dominant_category}

Category stats:
{cat_stats_txt}

Outperforming categories: {', '.join(context.outperforming_categories) or 'None'}
Underperforming categories: {', '.join(context.underperforming_categories) or 'None'}

Existing strategies (must NOT reuse these names): {', '.join(context.existing_strategy_names)}

{('Additional notes: ' + context.recent_notes) if context.recent_notes else ''}

Design a new strategy that specifically exploits the most promising pattern visible above.
Return JSON only.
"""


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

class AIStrategyBuilder:
    """
    Generates new trading strategies via Claude based on live market conditions.
    """

    _GENERATED_DIR = Path("src/strategies/generated")
    _STRATEGIES_YAML = Path("config/strategies.yaml")

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic.api_key)
        self._model = settings.prediction.llm_model
        self._GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        _init_file = self._GENERATED_DIR / "__init__.py"
        if not _init_file.exists():
            _init_file.write_text("")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def build_from_context(self, context: MarketContext) -> Optional[GeneratedStrategy]:
        """
        Ask Claude to design a strategy for the given context.
        Returns the strategy if code passes validation, else None.
        """
        log.info(
            "ai_builder.requesting_strategy",
            dominant=context.dominant_category,
            win_rate=round(context.overall_win_rate, 3),
            sharpe=round(context.overall_sharpe, 3),
        )

        raw = await self._call_claude(context)
        if not raw:
            return None

        strategy = self._parse_and_validate(raw, context)
        if not strategy:
            return None

        self._save_strategy_file(strategy)
        self._register_in_yaml(strategy)

        log.info(
            "ai_builder.strategy_generated",
            name=strategy.name,
            file=strategy.file_path,
            expected_edge=strategy.expected_edge_range,
        )
        return strategy

    async def build_from_db(
        self,
        db_trades: List[Dict],
        active_markets: int,
        existing_strategy_names: List[str],
    ) -> Optional[GeneratedStrategy]:
        """
        Convenience wrapper: derive MarketContext from raw trade records,
        then call build_from_context.
        """
        context = self._derive_context(db_trades, active_markets, existing_strategy_names)
        return await self.build_from_context(context)

    # ------------------------------------------------------------------
    # Claude call
    # ------------------------------------------------------------------

    async def _call_claude(self, context: MarketContext) -> Optional[str]:
        for attempt in range(3):
            try:
                response = await self._client.messages.create(
                    model=self._model,
                    max_tokens=2048,
                    system=[
                        {
                            "type": "text",
                            "text": _SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[
                        {"role": "user", "content": _build_user_prompt(context)}
                    ],
                )
                return response.content[0].text
            except anthropic.RateLimitError:
                wait = 2 ** attempt * 5
                log.warning("ai_builder.rate_limited", wait=wait)
                await asyncio.sleep(wait)
            except Exception as exc:
                log.error("ai_builder.claude_error", error=str(exc))
                return None
        return None

    # ------------------------------------------------------------------
    # Parse + validate
    # ------------------------------------------------------------------

    def _parse_and_validate(
        self, raw: str, context: MarketContext
    ) -> Optional[GeneratedStrategy]:
        # Strip any accidental markdown fences
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.error("ai_builder.json_parse_failed", error=str(exc), preview=raw[:200])
            return None

        required = {"name", "description", "rationale", "expected_edge_range", "params", "code"}
        missing = required - data.keys()
        if missing:
            log.error("ai_builder.missing_fields", missing=list(missing))
            return None

        name: str = data["name"]
        code: str = data["code"]

        # AST parse check
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            log.error("ai_builder.syntax_error", name=name, error=str(exc))
            return None

        # Must contain a class that extends BaseStrategy
        class_nodes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        valid_class = any(
            any(
                (isinstance(b, ast.Attribute) and b.attr == "BaseStrategy")
                or (isinstance(b, ast.Name) and b.id == "BaseStrategy")
                for b in cls.bases
            )
            for cls in class_nodes
        )
        if not valid_class:
            log.error("ai_builder.no_base_strategy_class", name=name)
            return None

        # Name collision check
        if name in context.existing_strategy_names:
            log.warning("ai_builder.name_collision", name=name)
            name = f"{name}_v{datetime.now().strftime('%Y%m%d%H%M')}"

        # Sanitize name
        name = re.sub(r"[^a-z0-9_]", "_", name.lower())

        file_path = str(self._GENERATED_DIR / f"{name}.py")
        yaml_entry = self._make_yaml_entry(name, data)

        return GeneratedStrategy(
            name=name,
            description=data["description"],
            code=code,
            params=data["params"],
            rationale=data["rationale"],
            expected_edge_range=data["expected_edge_range"],
            file_path=file_path,
            yaml_entry=yaml_entry,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_strategy_file(self, strategy: GeneratedStrategy) -> None:
        header = textwrap.dedent(f"""\
            # AUTO-GENERATED by AIStrategyBuilder — {datetime.now(timezone.utc).isoformat()}
            # Rationale: {strategy.rationale.replace(chr(10), ' ')}
            # Expected edge: {strategy.expected_edge_range}
            #
            # DO NOT edit manually — re-run scripts/generate_strategy.py to regenerate.

        """)
        Path(strategy.file_path).write_text(header + strategy.code)
        log.info("ai_builder.file_saved", path=strategy.file_path)

    def _register_in_yaml(self, strategy: GeneratedStrategy) -> None:
        """Append the strategy entry to config/strategies.yaml if not already present."""
        content = self._STRATEGIES_YAML.read_text() if self._STRATEGIES_YAML.exists() else ""
        if strategy.name in content:
            log.info("ai_builder.yaml_already_registered", name=strategy.name)
            return
        with self._STRATEGIES_YAML.open("a") as f:
            f.write(f"\n{strategy.yaml_entry}\n")
        log.info("ai_builder.yaml_updated", name=strategy.name)

    @staticmethod
    def _make_yaml_entry(name: str, data: Dict) -> str:
        module_path = f"src.strategies.generated.{name}"
        # Find class name from code
        match = re.search(r"class\s+(\w+)\s*\(", data["code"])
        cls_name = match.group(1) if match else "GeneratedStrategy"
        params_lines = "\n".join(
            f"      {k}: {json.dumps(v)}" for k, v in data.get("params", {}).items()
        )
        return textwrap.dedent(f"""\
            - name: "{name}"
              enabled: true
              class: "{module_path}.{cls_name}"
              params:
            {params_lines if params_lines else '      {}'}
        """)

    # ------------------------------------------------------------------
    # Context derivation from raw trade data
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_context(
        trades: List[Dict],
        active_markets: int,
        existing_strategy_names: List[str],
    ) -> MarketContext:
        import numpy as np

        if not trades:
            return MarketContext(
                timestamp=datetime.now(timezone.utc).isoformat(),
                total_active_markets=active_markets,
                category_stats=[],
                overall_win_rate=0.5,
                overall_sharpe=0.0,
                max_drawdown=0.0,
                avg_uncertainty=0.15,
                avg_confidence=0.55,
                avg_edge=0.03,
                volatility_regime="medium",
                dominant_category="Politics",
                underperforming_categories=[],
                outperforming_categories=[],
                existing_strategy_names=existing_strategy_names,
                recent_notes="Insufficient trade history — using defaults.",
            )

        pnls = np.array([float(t.get("pnl", 0)) for t in trades])
        wins = float(np.mean(pnls > 0))
        cum = np.cumsum(pnls)
        peak = np.maximum.accumulate(cum)
        dd = float(np.min((cum - peak) / np.maximum(peak, 1))) if len(pnls) > 0 else 0.0

        returns = np.diff(cum) / np.abs(cum[:-1] + 1e-9) if len(cum) > 1 else np.array([0.0])
        sharpe = float(np.mean(returns) / (np.std(returns) + 1e-9) * np.sqrt(252))

        # Per-category stats
        cat_map: Dict[str, List[Dict]] = {}
        for t in trades:
            cat = t.get("category", "Other")
            cat_map.setdefault(cat, []).append(t)

        cat_stats = []
        for cat, ctrades in cat_map.items():
            cpnls = np.array([float(t.get("pnl", 0)) for t in ctrades])
            cret = np.diff(np.cumsum(cpnls)) / (np.abs(np.cumsum(cpnls)[:-1]) + 1e-9)
            cs = float(np.mean(cret) / (np.std(cret) + 1e-9) * np.sqrt(252)) if len(cret) else 0.0
            cat_stats.append(CategoryStat(
                category=cat,
                num_trades=len(ctrades),
                win_rate=float(np.mean(cpnls > 0)),
                avg_edge=float(np.mean([t.get("edge", 0) for t in ctrades])),
                avg_pnl=float(np.mean(cpnls)),
                sharpe=cs,
            ))

        cat_stats.sort(key=lambda s: s.sharpe, reverse=True)
        out_perf = [s.category for s in cat_stats if s.sharpe > 0.5]
        under_perf = [s.category for s in cat_stats if s.sharpe < 0.0]
        dominant = max(cat_map, key=lambda c: len(cat_map[c])) if cat_map else "Politics"

        avg_unc = float(np.mean([float(t.get("uncertainty", 0.15)) for t in trades]))
        avg_conf = float(np.mean([float(t.get("confidence", 0.55)) for t in trades]))
        avg_edge = float(np.mean([float(t.get("edge", 0.03)) for t in trades]))

        vol_regime = "low" if avg_unc < 0.10 else ("high" if avg_unc > 0.20 else "medium")

        return MarketContext(
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_active_markets=active_markets,
            category_stats=cat_stats,
            overall_win_rate=wins,
            overall_sharpe=sharpe,
            max_drawdown=dd,
            avg_uncertainty=avg_unc,
            avg_confidence=avg_conf,
            avg_edge=avg_edge,
            volatility_regime=vol_regime,
            dominant_category=dominant,
            underperforming_categories=under_perf,
            outperforming_categories=out_perf,
            existing_strategy_names=existing_strategy_names,
        )
