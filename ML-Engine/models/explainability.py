from __future__ import annotations
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
import numpy as np
import pandas as pd
import shap
import joblib

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from models.lgbm_forecaster import QuantileEnergyForecaster


class EnergyExplainer:

    def __init__(self, forecaster: QuantileEnergyForecaster):
        self.forecaster = forecaster
        self.feature_cols = forecaster.feature_cols
        if not self.forecaster.load_models or not self.forecaster.solar_models:
            try:
                self.forecaster.load()
            except Exception:
                pass
        self.load_booster = forecaster.load_models.get(0.50)
        self.solar_booster = forecaster.solar_models.get(0.50)
        self._load_explainer: Optional[shap.TreeExplainer] = None
        self._solar_explainer: Optional[shap.TreeExplainer] = None

    @property
    def load_explainer(self) -> Optional[shap.TreeExplainer]:
        if self._load_explainer is None:
            if self.load_booster is None and self.forecaster.load_models:
                self.load_booster = self.forecaster.load_models.get(0.50)
            if self.load_booster is not None:
                self._load_explainer = shap.TreeExplainer(self.load_booster)
        return self._load_explainer

    @property
    def solar_explainer(self) -> Optional[shap.TreeExplainer]:
        if self._solar_explainer is None:
            if self.solar_booster is None and self.forecaster.solar_models:
                self.solar_booster = self.forecaster.solar_models.get(0.50)
            if self.solar_booster is not None:
                self._solar_explainer = shap.TreeExplainer(self.solar_booster)
        return self._solar_explainer

    def get_feature_importances(self) -> pd.DataFrame:
        load_imp = self.load_booster.feature_importance(importance_type="gain")
        solar_imp = self.solar_booster.feature_importance(importance_type="gain")

        df = pd.DataFrame({
            "feature": self.feature_cols,
            "load_importance": load_imp,
            "solar_importance": solar_imp,
        })
        df["total_importance"] = df["load_importance"] + df["solar_importance"]
        return df.sort_values(by="total_importance", ascending=False).reset_index(drop=True)

    def explain_slot(
        self,
        slot_features: pd.DataFrame,
        top_k: int = 4,
    ) -> Dict[str, Any]:
        if not all(c in slot_features.columns for c in self.feature_cols):
            slot_features = self.forecaster.feature_engineer.transform(slot_features)
        X = slot_features[self.feature_cols]

        explanation: Dict[str, Any] = {"load_drivers": [], "solar_drivers": []}

        if self.load_explainer is not None:
            shap_values_load = self.load_explainer.shap_values(X)
            if isinstance(shap_values_load, list):
                shap_values_load = shap_values_load[0]
            val = shap_values_load[0] if len(shap_values_load.shape) > 1 else shap_values_load
            top_load_idx = np.argsort(np.abs(val))[::-1][:top_k]
            for idx in top_load_idx:
                explanation["load_drivers"].append({
                    "feature": self.feature_cols[idx],
                    "value": float(X.iloc[0, idx]),
                    "shap_impact": round(float(val[idx]), 3),
                })

        if self.solar_explainer is not None:
            shap_values_solar = self.solar_explainer.shap_values(X)
            if isinstance(shap_values_solar, list):
                shap_values_solar = shap_values_solar[0]
            val = shap_values_solar[0] if len(shap_values_solar.shape) > 1 else shap_values_solar
            top_solar_idx = np.argsort(np.abs(val))[::-1][:top_k]
            for idx in top_solar_idx:
                explanation["solar_drivers"].append({
                    "feature": self.feature_cols[idx],
                    "value": float(X.iloc[0, idx]),
                    "shap_impact": round(float(val[idx]), 3),
                })

        return explanation
