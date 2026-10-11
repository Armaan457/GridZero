from __future__ import annotations
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import numpy as np
import pandas as pd
import lightgbm as lgb
import joblib
from sklearn.metrics import mean_absolute_error, mean_squared_error

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from models.features import FeatureEngineer, FEATURE_COLUMNS

SAVED_MODELS_DIR = Path(__file__).resolve().parent / "saved"


def pinball_loss(y_true: np.ndarray, y_pred: np.ndarray, alpha: float) -> float:
    diff = y_true - y_pred
    return float(np.mean(np.maximum(alpha * diff, (alpha - 1.0) * diff)))


class QuantileEnergyForecaster:

    QUANTILES = [0.10, 0.50, 0.90]

    def __init__(
        self,
        feature_cols: Optional[List[str]] = None,
        models_dir: Optional[Path] = None,
    ):
        self.feature_cols = feature_cols or FEATURE_COLUMNS
        self.models_dir = models_dir or SAVED_MODELS_DIR
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.feature_engineer = FeatureEngineer(self.feature_cols)

        self.load_models: Dict[float, lgb.Booster] = {}
        self.solar_models: Dict[float, lgb.Booster] = {}

    def train(
        self,
        train_df: pd.DataFrame,
        val_df: Optional[pd.DataFrame] = None,
        num_boost_round: int = 250,
        learning_rate: float = 0.05,
    ) -> Dict[str, Dict[str, float]]:
        train_feat = self.feature_engineer.transform(train_df)
        X_train = train_feat[self.feature_cols]
        y_train_load = train_feat["actual_load_kwh"].values
        y_train_solar = train_feat["actual_solar_kwh"].values

        val_feat = None
        if val_df is not None:
            val_feat = self.feature_engineer.transform(val_df)
            X_val = val_feat[self.feature_cols]
            y_val_load = val_feat["actual_load_kwh"].values
            y_val_solar = val_feat["actual_solar_kwh"].values

        metrics: Dict[str, Dict[str, float]] = {"load": {}, "solar": {}}

        for alpha in self.QUANTILES:
            params = {
                "objective": "quantile",
                "alpha": alpha,
                "metric": "quantile",
                "learning_rate": learning_rate,
                "num_leaves": 31,
                "min_child_samples": 20,
                "feature_fraction": 0.85,
                "verbose": -1,
                "random_state": 42,
            }
            dtrain = lgb.Dataset(X_train, label=y_train_load)
            valid_sets = [dtrain]
            if val_df is not None:
                dval = lgb.Dataset(X_val, label=y_val_load, reference=dtrain)
                valid_sets.append(dval)

            booster = lgb.train(
                params,
                dtrain,
                num_boost_round=num_boost_round,
                valid_sets=valid_sets,
            )
            self.load_models[alpha] = booster

            if val_df is not None:
                preds = booster.predict(X_val)
                p_loss = pinball_loss(y_val_load, preds, alpha)
                metrics["load"][f"p{int(alpha*100)}_loss"] = round(p_loss, 4)
                if alpha == 0.50:
                    metrics["load"]["mae"] = round(mean_absolute_error(y_val_load, preds), 4)
                    metrics["load"]["rmse"] = round(float(np.sqrt(mean_squared_error(y_val_load, preds))), 4)

        for alpha in self.QUANTILES:
            params = {
                "objective": "quantile",
                "alpha": alpha,
                "metric": "quantile",
                "learning_rate": learning_rate,
                "num_leaves": 31,
                "min_child_samples": 15,
                "feature_fraction": 0.85,
                "verbose": -1,
                "random_state": 42,
            }
            dtrain = lgb.Dataset(X_train, label=y_train_solar)
            valid_sets = [dtrain]
            if val_df is not None:
                dval = lgb.Dataset(X_val, label=y_val_solar, reference=dtrain)
                valid_sets.append(dval)

            booster = lgb.train(
                params,
                dtrain,
                num_boost_round=num_boost_round,
                valid_sets=valid_sets,
            )
            self.solar_models[alpha] = booster

            if val_df is not None:
                preds = booster.predict(X_val)
                p_loss = pinball_loss(y_val_solar, preds, alpha)
                metrics["solar"][f"p{int(alpha*100)}_loss"] = round(p_loss, 4)
                if alpha == 0.50:
                    metrics["solar"]["mae"] = round(mean_absolute_error(y_val_solar, preds), 4)
                    metrics["solar"]["rmse"] = round(float(np.sqrt(mean_squared_error(y_val_solar, preds))), 4)

        self.save()
        return metrics

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.load_models or not self.solar_models:
            self.load()

        feat_df = self.feature_engineer.transform(df)
        X = feat_df[self.feature_cols]

        out_df = feat_df.copy()

        p10_load = np.maximum(0.0, self.load_models[0.10].predict(X))
        p50_load = np.maximum(0.0, self.load_models[0.50].predict(X))
        p90_load = np.maximum(0.0, self.load_models[0.90].predict(X))
        p90_load = np.maximum(p90_load, p50_load)
        p50_load = np.maximum(p50_load, p10_load)

        p10_solar = np.maximum(0.0, self.solar_models[0.10].predict(X))
        p50_solar = np.maximum(0.0, self.solar_models[0.50].predict(X))
        p90_solar = np.maximum(0.0, self.solar_models[0.90].predict(X))
        night_mask = (out_df["datetime"].dt.hour < 6) | (out_df["datetime"].dt.hour > 18)
        p10_solar[night_mask] = 0.0
        p50_solar[night_mask] = 0.0
        p90_solar[night_mask] = 0.0
        p90_solar = np.maximum(p90_solar, p50_solar)
        p50_solar = np.maximum(p50_solar, p10_solar)

        p50_surplus = p50_solar - p50_load
        p10_surplus = p10_solar - p90_load
        p90_surplus = p90_solar - p10_load

        out_df["pred_load_p10"] = np.round(p10_load, 4)
        out_df["pred_load"] = np.round(p50_load, 4)
        out_df["pred_load_p90"] = np.round(p90_load, 4)

        out_df["pred_solar_p10"] = np.round(p10_solar, 4)
        out_df["pred_solar"] = np.round(p50_solar, 4)
        out_df["pred_solar_p90"] = np.round(p90_solar, 4)

        out_df["pred_surplus_or_need"] = np.round(p50_surplus, 4)
        out_df["pred_surplus_p10"] = np.round(p10_surplus, 4)
        out_df["pred_surplus_p90"] = np.round(p90_surplus, 4)
        out_df["confidence_spread"] = np.round(p90_surplus - p10_surplus, 4)

        return out_df

    def save(self, filepath: Optional[Path] = None):
        target_path = filepath or (self.models_dir / "lgbm_forecaster.joblib")
        payload = {
            "load_models": self.load_models,
            "solar_models": self.solar_models,
            "feature_cols": self.feature_cols,
        }
        joblib.dump(payload, target_path)

    def load(self, filepath: Optional[Path] = None):
        target_path = filepath or (self.models_dir / "lgbm_forecaster.joblib")
        if not target_path.exists():
            raise FileNotFoundError(f"Model file not found at {target_path}")
        payload = joblib.load(target_path)
        self.load_models = payload["load_models"]
        self.solar_models = payload["solar_models"]
        self.feature_cols = payload["feature_cols"]


if __name__ == "__main__":
    from data.generators.indian_load_profile import IndianMicrogridSimulator
    sim = IndianMicrogridSimulator()
    print("Generating simulation data...")
    df_train = sim.generate_microgrid_dataset(start_date="2024-01-01", end_date="2024-02-20")
    df_val = sim.generate_microgrid_dataset(start_date="2024-02-21", end_date="2024-02-28")

    forecaster = QuantileEnergyForecaster()
    print("Training LightGBM Quantile Forecaster...")
    scores = forecaster.train(df_train, df_val)
    print("Training Validation Scores:", scores)

    print("Generating predictions on validation set...")
    preds = forecaster.predict(df_val)
    print(preds[["datetime", "node_id", "pred_load", "pred_solar", "pred_surplus_or_need", "pred_surplus_p10", "pred_surplus_p90"]].head(10))
