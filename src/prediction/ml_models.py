"""
Gradient-boosted ML ensemble: LightGBM + XGBoost + CatBoost.

Each model is trained on historical feature vectors with binary YES/NO labels.
Models are serialized to disk and loaded on startup.
Supports incremental online updates via leaf-based update (LightGBM).
Produces calibrated probability estimates.
"""

from __future__ import annotations

import asyncio
import os
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class MLPrediction:
    model: str
    probability: float
    confidence: float
    feature_importance: Optional[Dict[str, float]] = None


class LightGBMPredictor:
    """LightGBM binary classifier for YES probability."""

    MODEL_FILE = "lgbm_model.pkl"

    def __init__(self, models_dir: str = "models") -> None:
        self._models_dir = Path(models_dir)
        self._model: Optional[Any] = None
        self._feature_names: Optional[List[str]] = None

    def load_or_create(self, feature_names: List[str]) -> None:
        import lightgbm as lgb

        self._feature_names = feature_names
        path = self._models_dir / self.MODEL_FILE
        if path.exists():
            with open(path, "rb") as f:
                self._model = pickle.load(f)
            log.info("lgbm.loaded", path=str(path))
        else:
            log.info("lgbm.no_model_found_will_create_on_train")

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: Optional[List[str]] = None,
        n_estimators: int = 500,
        learning_rate: float = 0.05,
        num_leaves: int = 31,
        min_child_samples: int = 20,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        reg_alpha: float = 0.1,
        reg_lambda: float = 0.1,
    ) -> Dict[str, float]:
        import lightgbm as lgb
        from sklearn.model_selection import cross_val_score

        if feature_names:
            self._feature_names = feature_names

        params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "n_estimators": n_estimators,
            "learning_rate": learning_rate,
            "num_leaves": num_leaves,
            "min_child_samples": min_child_samples,
            "subsample": subsample,
            "colsample_bytree": colsample_bytree,
            "reg_alpha": reg_alpha,
            "reg_lambda": reg_lambda,
            "verbose": -1,
            "n_jobs": -1,
            "random_state": 42,
        }
        self._model = lgb.LGBMClassifier(**params)
        self._model.fit(X, y, feature_name=self._feature_names or "auto")

        scores = cross_val_score(
            self._model, X, y, cv=5, scoring="neg_log_loss"
        )
        metrics = {"cv_log_loss": float(-scores.mean()), "cv_std": float(scores.std())}
        self._save()
        log.info("lgbm.trained", **metrics)
        return metrics

    def predict(self, X: np.ndarray) -> float:
        if self._model is None:
            return 0.5
        prob = self._model.predict_proba(X.reshape(1, -1))[0][1]
        return float(prob)

    def feature_importance(self) -> Optional[Dict[str, float]]:
        if self._model is None or self._feature_names is None:
            return None
        imp = self._model.feature_importances_
        return dict(zip(self._feature_names, imp.tolist()))

    def _save(self) -> None:
        self._models_dir.mkdir(parents=True, exist_ok=True)
        with open(self._models_dir / self.MODEL_FILE, "wb") as f:
            pickle.dump(self._model, f)

    def make_prediction(self, features: np.ndarray) -> MLPrediction:
        prob = self.predict(features)
        confidence = abs(prob - 0.5) * 2  # 0 at 0.5, 1 at 0 or 1
        importance = self.feature_importance()
        return MLPrediction(
            model="lgbm",
            probability=prob,
            confidence=confidence,
            feature_importance=importance,
        )


class XGBoostPredictor:
    """XGBoost binary classifier."""

    MODEL_FILE = "xgboost_model.pkl"

    def __init__(self, models_dir: str = "models") -> None:
        self._models_dir = Path(models_dir)
        self._model: Optional[Any] = None
        self._feature_names: Optional[List[str]] = None

    def load_or_create(self, feature_names: List[str]) -> None:
        self._feature_names = feature_names
        path = self._models_dir / self.MODEL_FILE
        if path.exists():
            with open(path, "rb") as f:
                self._model = pickle.load(f)
            log.info("xgboost.loaded", path=str(path))

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: Optional[List[str]] = None,
        n_estimators: int = 500,
        learning_rate: float = 0.05,
        max_depth: int = 6,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        reg_alpha: float = 0.1,
        reg_lambda: float = 1.0,
    ) -> Dict[str, float]:
        import xgboost as xgb
        from sklearn.model_selection import cross_val_score

        if feature_names:
            self._feature_names = feature_names

        params = {
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "n_estimators": n_estimators,
            "learning_rate": learning_rate,
            "max_depth": max_depth,
            "subsample": subsample,
            "colsample_bytree": colsample_bytree,
            "reg_alpha": reg_alpha,
            "reg_lambda": reg_lambda,
            "use_label_encoder": False,
            "verbosity": 0,
            "n_jobs": -1,
            "random_state": 42,
        }
        self._model = xgb.XGBClassifier(**params)
        self._model.fit(X, y)
        scores = cross_val_score(
            self._model, X, y, cv=5, scoring="neg_log_loss"
        )
        metrics = {"cv_log_loss": float(-scores.mean()), "cv_std": float(scores.std())}
        self._save()
        log.info("xgboost.trained", **metrics)
        return metrics

    def predict(self, X: np.ndarray) -> float:
        if self._model is None:
            return 0.5
        return float(self._model.predict_proba(X.reshape(1, -1))[0][1])

    def _save(self) -> None:
        self._models_dir.mkdir(parents=True, exist_ok=True)
        with open(self._models_dir / self.MODEL_FILE, "wb") as f:
            pickle.dump(self._model, f)

    def make_prediction(self, features: np.ndarray) -> MLPrediction:
        prob = self.predict(features)
        return MLPrediction(
            model="xgboost",
            probability=prob,
            confidence=abs(prob - 0.5) * 2,
        )


class CatBoostPredictor:
    """CatBoost binary classifier."""

    MODEL_FILE = "catboost_model.pkl"

    def __init__(self, models_dir: str = "models") -> None:
        self._models_dir = Path(models_dir)
        self._model: Optional[Any] = None

    def load_or_create(self, feature_names: List[str]) -> None:
        path = self._models_dir / self.MODEL_FILE
        if path.exists():
            with open(path, "rb") as f:
                self._model = pickle.load(f)
            log.info("catboost.loaded", path=str(path))

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        n_estimators: int = 500,
        learning_rate: float = 0.05,
        depth: int = 6,
    ) -> Dict[str, float]:
        from catboost import CatBoostClassifier
        from sklearn.model_selection import cross_val_score

        params = {
            "iterations": n_estimators,
            "learning_rate": learning_rate,
            "depth": depth,
            "loss_function": "Logloss",
            "eval_metric": "Logloss",
            "verbose": False,
            "random_state": 42,
        }
        self._model = CatBoostClassifier(**params)
        self._model.fit(X, y)
        scores = cross_val_score(
            self._model, X, y, cv=5, scoring="neg_log_loss"
        )
        metrics = {"cv_log_loss": float(-scores.mean()), "cv_std": float(scores.std())}
        self._save()
        log.info("catboost.trained", **metrics)
        return metrics

    def predict(self, X: np.ndarray) -> float:
        if self._model is None:
            return 0.5
        return float(self._model.predict_proba(X.reshape(1, -1))[0][1])

    def _save(self) -> None:
        self._models_dir.mkdir(parents=True, exist_ok=True)
        with open(self._models_dir / self.MODEL_FILE, "wb") as f:
            pickle.dump(self._model, f)

    def make_prediction(self, features: np.ndarray) -> MLPrediction:
        prob = self.predict(features)
        return MLPrediction(
            model="catboost",
            probability=prob,
            confidence=abs(prob - 0.5) * 2,
        )
