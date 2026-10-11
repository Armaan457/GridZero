from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Dict, Any
import pandas as pd
import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import aws.env_loader
from models.lgbm_forecaster import QuantileEnergyForecaster

_FORECASTER: QuantileEnergyForecaster = None


def get_forecaster() -> QuantileEnergyForecaster:
    global _FORECASTER
    if _FORECASTER is None:
        models_dir = Path(__file__).resolve().parent.parent / "models" / "saved"
        _FORECASTER = QuantileEnergyForecaster(models_dir=models_dir)
        _FORECASTER.load()
    return _FORECASTER


def lambda_handler(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    try:
        if "body" in event and isinstance(event["body"], str):
            payload = json.loads(event["body"])
        else:
            payload = event

        forecaster = get_forecaster()

        df_row = pd.DataFrame([{
            "datetime": pd.to_datetime(payload.get("datetime", "2024-03-05 13:00:00")),
            "node_id": payload.get("node_id", "node_01"),
            "temperature_c": float(payload.get("temperature_c", 30.0)),
            "ghi_w_m2": float(payload.get("ghi_w_m2", 750.0)),
            "dni_w_m2": float(payload.get("dni_w_m2", 700.0)),
            "dhi_w_m2": float(payload.get("dhi_w_m2", 150.0)),
            "cloud_cover_pct": float(payload.get("cloud_cover_pct", 15.0)),
            "humidity_pct": float(payload.get("humidity_pct", 50.0)),
            "solar_capacity_kw": float(payload.get("solar_capacity_kw", 0.0)),
            "household_size": int(payload.get("household_size", 3)),
            "ac_units": int(payload.get("ac_units", 1)),
            "has_ev": int(payload.get("has_ev", 0)),
            "actual_load_kwh": float(payload.get("actual_load_kwh", 0.8)),
            "actual_solar_kwh": float(payload.get("actual_solar_kwh", 0.0)),
        }])

        preds = forecaster.predict(df_row)
        res = preds.iloc[0]

        pred_surplus = float(res["pred_surplus_or_need"])
        role = "SURPLUS_SELLER" if pred_surplus > 0.1 else ("DEFICIT_BUYER" if pred_surplus < -0.1 else "BALANCED")

        response_body = {
            "status": "success",
            "node_id": str(res["node_id"]),
            "datetime": str(res["datetime"]),
            "predictions": {
                "load": {
                    "p10": float(res["pred_load_p10"]),
                    "p50": float(res["pred_load"]),
                    "p90": float(res["pred_load_p90"]),
                },
                "solar": {
                    "p10": float(res["pred_solar_p10"]),
                    "p50": float(res["pred_solar"]),
                    "p90": float(res["pred_solar_p90"]),
                },
                "net_surplus_or_need": {
                    "p10_conservative": float(res["pred_surplus_p10"]),
                    "p50_expected": pred_surplus,
                    "p90_optimistic": float(res["pred_surplus_p90"]),
                    "confidence_spread": float(res["confidence_spread"]),
                },
            },
            "market_role": role,
        }

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(response_body),
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"status": "error", "message": str(e)}),
        }


if __name__ == "__main__":
    sample_event = {
        "node_id": "node_01",
        "datetime": "2024-03-05 14:00:00",
        "temperature_c": 31.0,
        "ghi_w_m2": 820.0,
        "dni_w_m2": 780.0,
        "dhi_w_m2": 150.0,
        "cloud_cover_pct": 12.0,
        "humidity_pct": 45.0,
        "solar_capacity_kw": 5.0,
        "household_size": 3,
        "ac_units": 1,
        "has_ev": 0,
        "actual_load_kwh": 0.85,
        "actual_solar_kwh": 3.90,
    }
    print("Testing Lambda Handler with sample microgrid payload...")
    res = lambda_handler(sample_event)
    print("Status Code:", res["statusCode"])
    print("Response JSON:")
    print(json.dumps(json.loads(res["body"]), indent=2))
