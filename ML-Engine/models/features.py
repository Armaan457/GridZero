from __future__ import annotations
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Any
import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

FEATURE_COLUMNS = [
    "hour_sin", "hour_cos",
    "day_sin", "day_cos",
    "month_sin", "month_cos",
    "is_weekend",
    "temperature_c", "humidity_pct", "cloud_cover_pct",
    "ghi_w_m2", "dni_w_m2", "dhi_w_m2",
    "temp_over_30", "cooling_degree_hour",
    "solar_capacity_kw", "household_size", "ac_units", "has_ev",
    "load_lag_1h", "load_lag_2h", "load_lag_24h", "load_lag_168h",
    "load_rolling_mean_3h", "load_rolling_mean_24h", "load_rolling_std_24h",
    "solar_lag_1h", "solar_lag_24h", "solar_lag_168h",
    "solar_potential_theoretical",
]


class FeatureEngineer:

    def __init__(self, feature_cols: List[str] = None):
        self.feature_cols = feature_cols or FEATURE_COLUMNS

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df = df.sort_values(by=["node_id", "datetime"]).reset_index(drop=True)

        hours = df["datetime"].dt.hour
        days = df["datetime"].dt.dayofweek
        months = df["datetime"].dt.month

        df["hour_sin"] = np.sin(2 * np.pi * hours / 24.0)
        df["hour_cos"] = np.cos(2 * np.pi * hours / 24.0)
        df["day_sin"] = np.sin(2 * np.pi * days / 7.0)
        df["day_cos"] = np.cos(2 * np.pi * days / 7.0)
        df["month_sin"] = np.sin(2 * np.pi * months / 12.0)
        df["month_cos"] = np.cos(2 * np.pi * months / 12.0)
        df["is_weekend"] = (days >= 5).astype(int)

        df["temp_over_30"] = np.maximum(0.0, df["temperature_c"] - 30.0)
        df["cooling_degree_hour"] = np.maximum(0.0, df["temperature_c"] - 24.0)

        df["solar_potential_theoretical"] = np.maximum(
            0.0, df["solar_capacity_kw"] * (df["ghi_w_m2"] / 1000.0) * 0.82
        )

        processed_groups = []
        for _, group in df.groupby("node_id", sort=False):
            grp = group.copy()
            grp["load_lag_1h"] = grp["actual_load_kwh"].shift(1)
            grp["load_lag_2h"] = grp["actual_load_kwh"].shift(2)
            grp["load_lag_24h"] = grp["actual_load_kwh"].shift(24)
            grp["load_lag_168h"] = grp["actual_load_kwh"].shift(168)

            grp["load_rolling_mean_3h"] = grp["actual_load_kwh"].shift(1).rolling(3, min_periods=1).mean()
            grp["load_rolling_mean_24h"] = grp["actual_load_kwh"].shift(1).rolling(24, min_periods=1).mean()
            grp["load_rolling_std_24h"] = grp["actual_load_kwh"].shift(1).rolling(24, min_periods=1).std().fillna(0.0)

            grp["solar_lag_1h"] = grp["actual_solar_kwh"].shift(1)
            grp["solar_lag_24h"] = grp["actual_solar_kwh"].shift(24)
            grp["solar_lag_168h"] = grp["actual_solar_kwh"].shift(168)

            grp["load_lag_24h"] = grp["load_lag_24h"].fillna(grp["actual_load_kwh"])
            grp["load_lag_168h"] = grp["load_lag_168h"].fillna(grp["load_lag_24h"])
            grp["load_lag_1h"] = grp["load_lag_1h"].fillna(grp["actual_load_kwh"])
            grp["load_lag_2h"] = grp["load_lag_2h"].fillna(grp["load_lag_1h"])

            grp["solar_lag_24h"] = grp["solar_lag_24h"].fillna(grp["actual_solar_kwh"])
            grp["solar_lag_168h"] = grp["solar_lag_168h"].fillna(grp["solar_lag_24h"])
            grp["solar_lag_1h"] = grp["solar_lag_1h"].fillna(grp["actual_solar_kwh"])

            processed_groups.append(grp)

        result_df = pd.concat(processed_groups, ignore_index=True)
        for col in self.feature_cols:
            if col in result_df.columns:
                result_df[col] = result_df[col].fillna(0.0)

        return result_df


if __name__ == "__main__":
    from data.generators.indian_load_profile import IndianMicrogridSimulator
    sim = IndianMicrogridSimulator()
    df_raw = sim.generate_microgrid_dataset(start_date="2024-03-01", end_date="2024-03-05")
    fe = FeatureEngineer()
    df_features = fe.transform(df_raw)
    print("Engineered features:", df_features[FEATURE_COLUMNS].head(2))
