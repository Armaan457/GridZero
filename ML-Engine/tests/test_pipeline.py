import sys
from pathlib import Path
import unittest
import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from data.generators.weather_fetcher import WeatherFetcher
from data.generators.indian_load_profile import IndianMicrogridSimulator
from models.features import FeatureEngineer
from models.lgbm_forecaster import QuantileEnergyForecaster
from market.p2p_clearing import MicrogridP2PClearingEngine
from aws.bedrock_agent import BedrockEnergyAgent
from aws.lambda_handler import lambda_handler


class TestP2PESPipeline(unittest.TestCase):

    def setUp(self):
        self.simulator = IndianMicrogridSimulator()
        self.weather_fetcher = WeatherFetcher()
        self.feature_engineer = FeatureEngineer()
        self.clearing_engine = MicrogridP2PClearingEngine()
        self.bedrock_agent = BedrockEnergyAgent()

    def test_01_weather_fetcher(self):
        df_weather = self.weather_fetcher.fetch_weather(
            city="Bengaluru", start_date="2024-03-01", end_date="2024-03-02"
        )
        self.assertGreater(len(df_weather), 0)
        self.assertIn("ghi_w_m2", df_weather.columns)
        self.assertIn("temperature_c", df_weather.columns)

    def test_02_simulation_generation(self):
        df = self.simulator.generate_microgrid_dataset(
            city="Bengaluru", start_date="2024-03-01", end_date="2024-03-03"
        )
        self.assertGreater(len(df), 0)
        node_ids = set(df["node_id"].unique())
        self.assertEqual(len(node_ids), 5)
        self.assertTrue((df["actual_load_kwh"] >= 0).all())
        self.assertTrue((df["actual_solar_kwh"] >= 0).all())

    def test_03_feature_engineering(self):
        df = self.simulator.generate_microgrid_dataset(
            city="Bengaluru", start_date="2024-03-01", end_date="2024-03-03"
        )
        feat_df = self.feature_engineer.transform(df)
        self.assertIn("hour_sin", feat_df.columns)
        self.assertIn("load_lag_24h", feat_df.columns)
        self.assertIn("solar_lag_24h", feat_df.columns)
        for col in self.feature_engineer.feature_cols:
            self.assertFalse(feat_df[col].isna().any(), f"NaN found in feature {col}")

    def test_04_forecaster_training_and_quantiles(self):
        df_train = self.simulator.generate_microgrid_dataset(
            start_date="2024-03-01", end_date="2024-03-05"
        )
        df_test = self.simulator.generate_microgrid_dataset(
            start_date="2024-03-06", end_date="2024-03-06"
        )

        forecaster = QuantileEnergyForecaster()
        metrics = forecaster.train(df_train, num_boost_round=40)
        self.assertIn("load", metrics)
        self.assertIn("solar", metrics)

        preds = forecaster.predict(df_test)
        self.assertIn("pred_load", preds.columns)
        self.assertIn("pred_solar", preds.columns)
        self.assertIn("pred_surplus_or_need", preds.columns)
        self.assertIn("pred_surplus_p10", preds.columns)
        self.assertIn("pred_surplus_p90", preds.columns)

        self.assertTrue((preds["pred_load_p90"] >= preds["pred_load"]).all())
        self.assertTrue((preds["pred_solar_p90"] >= preds["pred_solar"]).all())
        self.assertTrue((preds["pred_surplus_p90"] >= preds["pred_surplus_p10"]).all())

    def test_05_p2p_clearing_engine(self):
        df_test = self.simulator.generate_microgrid_dataset(
            start_date="2024-03-05", end_date="2024-03-05"
        )
        forecaster = QuantileEnergyForecaster()
        preds = forecaster.predict(df_test)

        results = self.clearing_engine.clear_horizon(preds)
        self.assertEqual(len(results), 24)
        summary = self.clearing_engine.summarize_to_dataframe(results)
        self.assertGreater(summary["community_savings_inr"].sum(), 0.0)

    def test_06_bedrock_advisory(self):
        msg = self.bedrock_agent.generate_advisory(
            node_name="Aarav Sharma",
            node_type="Solar Prosumer",
            peak_surplus_slot="13:00–15:00",
            peak_surplus_kwh=3.5,
            p10_surplus=2.8,
            p90_surplus=4.2,
            matched_peer="Iyengar Bakery",
            estimated_earnings_inr=18.55,
            grid_comparison_inr=8.58,
        )
        self.assertIsInstance(msg, str)
        self.assertIn("Aarav Sharma", msg)
        self.assertIn("3.5 kWh", msg)

    def test_07_lambda_handler(self):
        payload = {
            "node_id": "node_01",
            "datetime": "2024-03-05 14:00:00",
            "temperature_c": 31.0,
            "ghi_w_m2": 820.0,
            "solar_capacity_kw": 5.0,
        }
        res = lambda_handler(payload)
        self.assertEqual(res["statusCode"], 200)

    def test_08_fastapi_endpoints(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)

        res = client.get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "healthy")

        res_nodes = client.get("/nodes")
        self.assertEqual(res_nodes.status_code, 200)
        self.assertEqual(res_nodes.json()["total_nodes"], 5)

        res_fc = client.post("/forecast/node", json={
            "node_id": "node_01",
            "datetime_str": "2024-03-05 14:00:00",
            "temperature_c": 31.0,
            "ghi_w_m2": 820.0,
            "solar_capacity_kw": 5.0,
        })
        self.assertEqual(res_fc.status_code, 200)
        data = res_fc.json()
        self.assertIn("load_kwh", data)
        self.assertIn("solar_kwh", data)
        self.assertIn("net_surplus_or_need_kwh", data)


if __name__ == "__main__":
    unittest.main()
