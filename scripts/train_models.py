#!/usr/bin/env python3
"""
Train ML models on historical market data.

Usage:
    python scripts/train_models.py \
        --data data/historical_markets.json \
        --models-dir models/

Trains LightGBM, XGBoost, CatBoost on labeled historical features.
Saves calibrated models for use by the live prediction engine.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import get_settings
from src.core.logging import get_logger, setup_logging
from src.features.engineer import FeatureEngineer
from src.prediction.calibration import ProbabilityCalibrator
from src.prediction.ml_models import (
    CatBoostPredictor,
    LightGBMPredictor,
    XGBoostPredictor,
)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="data/historical_markets.json")
    p.add_argument("--models-dir", default="models/")
    p.add_argument("--config", default="config/config.yaml")
    return p.parse_args()


def main():
    args = parse_args()
    settings = get_settings(args.config)
    setup_logging("INFO")
    log = get_logger("train_models")

    if not os.path.exists(args.data):
        log.error("train.data_not_found", path=args.data)
        sys.exit(1)

    with open(args.data) as f:
        markets = json.load(f)

    resolved = [m for m in markets if m.get("resolved") and "outcome" in m]
    if len(resolved) < 50:
        log.error("train.not_enough_resolved_markets", n=len(resolved))
        sys.exit(1)

    log.info("train.starting", n_markets=len(resolved))

    fe = FeatureEngineer()
    X_list, y_list = [], []

    for m in resolved:
        try:
            features = fe.extract(
                market=m,
                orderbook=m.get("orderbook"),
                price_history=m.get("price_history", []),
                analytics={
                    "volume": {"volume24hr": m.get("volume_24h", 0)},
                    "open_interest": {},
                    "recent_trades": [],
                },
                sentiment_score=float(m.get("sentiment_score", 0)),
                sentiment_confidence=float(m.get("sentiment_confidence", 0)),
            )
            _, values = fe.to_vector(features)
            X_list.append(values)
            y_list.append(float(m["outcome"]))
        except Exception as e:
            log.debug("train.feature_error", error=str(e))

    if not X_list:
        log.error("train.no_features_extracted")
        sys.exit(1)

    X = np.array(X_list, dtype=np.float32)
    y = np.array(y_list, dtype=np.float32)

    # Feature names from first sample
    sample_features = fe.extract(
        market=resolved[0], orderbook=None,
        price_history=[], analytics={"volume": {}, "open_interest": {}, "recent_trades": []},
    )
    feature_names, _ = fe.to_vector(sample_features)

    log.info("train.data_ready", n_samples=len(X), n_features=len(feature_names))
    os.makedirs(args.models_dir, exist_ok=True)

    # LightGBM
    lgbm = LightGBMPredictor(models_dir=args.models_dir)
    lgbm_metrics = lgbm.train(X, y, feature_names=feature_names)
    log.info("train.lgbm_done", **lgbm_metrics)

    # XGBoost
    xgb = XGBoostPredictor(models_dir=args.models_dir)
    xgb_metrics = xgb.train(X, y, feature_names=feature_names)
    log.info("train.xgboost_done", **xgb_metrics)

    # CatBoost
    cat = CatBoostPredictor(models_dir=args.models_dir)
    cat_metrics = cat.train(X, y)
    log.info("train.catboost_done", **cat_metrics)

    # Calibration
    calibrator = ProbabilityCalibrator(method="isotonic", models_dir=args.models_dir)
    lgbm_preds = np.array([lgbm.predict(x.reshape(1, -1)) for x in X])
    calibrator.fit("lgbm", lgbm_preds, y)
    xgb_preds = np.array([xgb.predict(x.reshape(1, -1)) for x in X])
    calibrator.fit("xgboost", xgb_preds, y)
    cat_preds = np.array([cat.predict(x.reshape(1, -1)) for x in X])
    calibrator.fit("catboost", cat_preds, y)

    log.info("train.complete", models_dir=args.models_dir)
    print(f"\n✅ Models trained and saved to {args.models_dir}")


if __name__ == "__main__":
    main()
