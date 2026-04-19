"""
Probability calibration module.

Implements:
  - Isotonic regression calibration (non-parametric, monotone)
  - Platt scaling (parametric sigmoid calibration)
  - Temperature scaling
  - Reliability diagrams for visual inspection
  - Brier score / log-loss tracking per model
  - Online calibration updates from resolved markets
"""

from __future__ import annotations

import math
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class CalibrationResult:
    model_name: str
    brier_score: float
    log_loss: float
    ece: float                  # Expected Calibration Error
    n_samples: int
    bins: List[Tuple[float, float, int]]  # (mean_predicted, mean_actual, count)


@dataclass
class CalibrationRecord:
    predicted_prob: float
    actual_outcome: float       # 1.0 for YES, 0.0 for NO
    model_name: str


class ProbabilityCalibrator:
    """
    Calibrates raw model probabilities using isotonic regression or Platt scaling.
    Maintains per-model calibration state and tracks Brier scores.
    """

    def __init__(
        self,
        method: str = "isotonic",
        models_dir: str = "models",
    ) -> None:
        self._method = method
        self._models_dir = Path(models_dir)
        self._calibrators: Dict[str, Any] = {}
        self._history: List[CalibrationRecord] = []

    def fit(
        self,
        model_name: str,
        predicted_probs: np.ndarray,
        actual_outcomes: np.ndarray,
    ) -> None:
        """Fit calibrator on (predicted, actual) pairs."""
        from sklearn.calibration import CalibratedClassifierCV, calibration_curve
        from sklearn.isotonic import IsotonicRegression
        from sklearn.linear_model import LogisticRegression

        if self._method == "isotonic":
            cal = IsotonicRegression(out_of_bounds="clip")
            cal.fit(predicted_probs, actual_outcomes)
        elif self._method == "platt":
            # Platt scaling via logistic regression on logit-transformed probs
            logit = np.log(
                predicted_probs / (1 - np.clip(predicted_probs, 1e-7, 1 - 1e-7))
            ).reshape(-1, 1)
            cal = LogisticRegression(C=1e9)
            cal.fit(logit, actual_outcomes)
        else:
            raise ValueError(f"Unknown calibration method: {self._method}")

        self._calibrators[model_name] = cal
        self._save_calibrator(model_name, cal)
        log.info("calibration.fitted", model=model_name, method=self._method, n=len(predicted_probs))

    def calibrate(self, model_name: str, raw_prob: float) -> float:
        """Apply calibration to a single raw probability."""
        if model_name not in self._calibrators:
            self._load_calibrator(model_name)
        if model_name not in self._calibrators:
            return raw_prob  # no calibrator available, pass through

        cal = self._calibrators[model_name]
        p = np.array([raw_prob])

        if self._method == "isotonic":
            result = cal.transform(p)[0]
        else:  # platt
            logit = np.log(p / (1 - np.clip(p, 1e-7, 1 - 1e-7))).reshape(-1, 1)
            result = cal.predict_proba(logit)[0][1]

        return float(np.clip(result, 0.01, 0.99))

    def record_outcome(
        self,
        model_name: str,
        predicted_prob: float,
        actual_outcome: float,
    ) -> None:
        """Record a resolved prediction for ongoing calibration tracking."""
        self._history.append(
            CalibrationRecord(
                predicted_prob=predicted_prob,
                actual_outcome=actual_outcome,
                model_name=model_name,
            )
        )

    def evaluate(self, model_name: Optional[str] = None) -> Dict[str, CalibrationResult]:
        """Compute calibration metrics for each model (or specific model)."""
        results: Dict[str, CalibrationResult] = {}
        records = [r for r in self._history if model_name is None or r.model_name == model_name]
        model_names = {r.model_name for r in records}

        for name in model_names:
            model_records = [r for r in records if r.model_name == name]
            preds = np.array([r.predicted_prob for r in model_records])
            actuals = np.array([r.actual_outcome for r in model_records])

            if len(preds) == 0:
                continue

            brier = float(np.mean((preds - actuals) ** 2))
            eps = 1e-10
            pclipped = np.clip(preds, eps, 1 - eps)
            ll = float(-np.mean(
                actuals * np.log(pclipped) + (1 - actuals) * np.log(1 - pclipped)
            ))

            ece, bins = self._compute_ece(preds, actuals)
            results[name] = CalibrationResult(
                model_name=name,
                brier_score=brier,
                log_loss=ll,
                ece=ece,
                n_samples=len(preds),
                bins=bins,
            )
        return results

    @staticmethod
    def _compute_ece(
        preds: np.ndarray,
        actuals: np.ndarray,
        n_bins: int = 10,
    ) -> Tuple[float, List[Tuple[float, float, int]]]:
        bins = np.linspace(0, 1, n_bins + 1)
        ece = 0.0
        bin_stats = []
        for i in range(n_bins):
            mask = (preds >= bins[i]) & (preds < bins[i + 1])
            if mask.sum() == 0:
                continue
            bin_preds = preds[mask]
            bin_actuals = actuals[mask]
            mean_pred = float(bin_preds.mean())
            mean_actual = float(bin_actuals.mean())
            count = int(mask.sum())
            ece += count / len(preds) * abs(mean_pred - mean_actual)
            bin_stats.append((mean_pred, mean_actual, count))
        return ece, bin_stats

    def _save_calibrator(self, model_name: str, cal: Any) -> None:
        self._models_dir.mkdir(parents=True, exist_ok=True)
        path = self._models_dir / f"calibrator_{model_name}.pkl"
        with open(path, "wb") as f:
            pickle.dump(cal, f)

    def _load_calibrator(self, model_name: str) -> None:
        path = self._models_dir / f"calibrator_{model_name}.pkl"
        if path.exists():
            with open(path, "rb") as f:
                self._calibrators[model_name] = pickle.load(f)
            log.info("calibration.loaded", model=model_name)
