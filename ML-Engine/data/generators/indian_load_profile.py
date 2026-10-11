from __future__ import annotations
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
import yaml

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from data.generators.weather_fetcher import WeatherFetcher


class IndianMicrogridSimulator:

    def __init__(self, config_path: Optional[Path] = None):
        if config_path is None:
            config_path = Path(__file__).resolve().parent.parent / "archetypes" / "nodes_config.yaml"
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)
        self.nodes = self.config["nodes"]
        self.weather_fetcher = WeatherFetcher()

    def generate_microgrid_dataset(
        self,
        city: str = "Bengaluru",
        start_date: str = "2024-01-01",
        end_date: str = "2024-03-31",
        random_seed: int = 42,
    ) -> pd.DataFrame:
        np.random.seed(random_seed)
        weather_df = self.weather_fetcher.fetch_weather(
            city=city, start_date=start_date, end_date=end_date
        )

        all_node_dfs: List[pd.DataFrame] = []

        for node in self.nodes:
            node_df = self._simulate_single_node(node, weather_df.copy())
            all_node_dfs.append(node_df)

        unified_df = pd.concat(all_node_dfs, ignore_index=True)
        return unified_df

    def _simulate_single_node(self, node: Dict, weather_df: pd.DataFrame) -> pd.DataFrame:
        df = weather_df.copy()
        n = len(df)
        hours = df["datetime"].dt.hour.values
        day_of_week = df["datetime"].dt.dayofweek.values
        temps = df["temperature_c"].values
        ghis = df["ghi_w_m2"].values

        node_id = node["id"]
        node_name = node["name"]
        node_type = node["type"]
        hh_size = node["household_size"]
        solar_kw = node.get("solar_capacity_kw", 0.0)
        appliances = node.get("appliances", {})
        behavior = node.get("behavior", {})

        base_kw = appliances.get("base_fridge_led_kw", 0.25)
        diurnal_weight = 1.0 + 0.35 * np.sin(np.pi * (hours - 6) / 12)
        base_load = base_kw * np.clip(diurnal_weight, 0.6, 1.5)
        if hh_size > 0:
            base_load += (hh_size - 1) * 0.05

        ac_load = np.zeros(n)
        ac_units = appliances.get("ac_units", 0)
        ac_power = appliances.get("ac_power_kw", 1.5)
        ac_threshold = behavior.get("ac_temp_threshold_c", 29.0)

        if ac_units > 0:
            afternoon_ac = (hours >= 13) & (hours <= 17) & (temps >= ac_threshold)
            night_ac = ((hours >= 22) | (hours <= 5)) & (temps >= (ac_threshold - 2.0))

            prob_afternoon = np.clip((temps - ac_threshold) / 5.0, 0.3, 0.95)
            prob_night = np.clip((temps - (ac_threshold - 2.0)) / 5.0, 0.4, 0.90)

            ac_active_afternoon = afternoon_ac & (np.random.uniform(0, 1, n) < prob_afternoon)
            ac_active_night = night_ac & (np.random.uniform(0, 1, n) < prob_night)

            temp_overdrive = np.clip((temps - 25.0) / 10.0, 0.7, 1.25)
            ac_load[ac_active_afternoon] = ac_power * 0.85 * temp_overdrive[ac_active_afternoon]
            ac_load[ac_active_night] = ac_power * 0.65 * temp_overdrive[ac_active_night]

        geyser_load = np.zeros(n)
        geyser_power = appliances.get("geyser_power_kw", 2.0)
        if geyser_power > 0 and hh_size > 0:
            geyser_hours_mask = (hours >= 6) & (hours <= 8)
            geyser_prob = np.clip(1.0 - (temps / 35.0), 0.4, 0.9)
            geyser_active = geyser_hours_mask & (np.random.uniform(0, 1, n) < geyser_prob)
            fraction_hour = np.random.uniform(0.4, 0.85, n)
            geyser_load[geyser_active] = geyser_power * fraction_hour[geyser_active]

        commercial_load = np.zeros(n)
        if node_type == "commercial_consumer":
            oven_power = appliances.get("commercial_ovens_kw", 2.5)
            baking_mask = ((hours >= 8) & (hours <= 11)) | ((hours >= 15) & (hours <= 18))
            commercial_load[baking_mask] = oven_power * np.random.uniform(0.75, 1.05, sum(baking_mask))

        ev_load = np.zeros(n)
        if appliances.get("has_ev", False):
            ev_charger_kw = appliances.get("ev_charger_kw", 3.3)
            is_weekend = (day_of_week >= 5)
            solar_charge_mask = is_weekend & (hours >= 11) & (hours <= 14) & (np.random.uniform(0, 1, n) < 0.6)
            evening_charge_mask = (~is_weekend) & (hours >= 20) & (hours <= 23) & (np.random.uniform(0, 1, n) < 0.4)
            ev_load[solar_charge_mask | evening_charge_mask] = ev_charger_kw * np.random.uniform(0.85, 1.0, sum(solar_charge_mask | evening_charge_mask))

        noise = np.random.normal(0.0, 0.08, n)
        spikes = (np.random.uniform(0, 1, n) < 0.05) * np.random.uniform(0.3, 1.2, n)

        total_load_kwh = np.clip(
            base_load + ac_load + geyser_load + commercial_load + ev_load + noise + spikes,
            0.05,
            12.0,
        )

        solar_generation_kwh = np.zeros(n)
        if solar_kw > 0:
            performance_ratio = 0.82
            cell_temp = temps + (25.0 / 800.0) * ghis
            thermal_loss_factor = np.clip(1.0 - 0.004 * (cell_temp - 25.0), 0.70, 1.05)
            raw_gen = solar_kw * (ghis / 1000.0) * performance_ratio * thermal_loss_factor
            solar_generation_kwh = np.clip(raw_gen + np.random.normal(0, 0.015 * solar_kw, n), 0, solar_kw * 1.05)
            solar_generation_kwh[(hours < 6) | (hours > 18)] = 0.0

        net_surplus_need = solar_generation_kwh - total_load_kwh

        df["node_id"] = node_id
        df["node_name"] = node_name
        df["node_type"] = node_type
        df["household_size"] = hh_size
        df["solar_capacity_kw"] = solar_kw
        df["ac_units"] = ac_units
        df["has_ev"] = int(appliances.get("has_ev", False))
        df["actual_load_kwh"] = np.round(total_load_kwh, 4)
        df["actual_solar_kwh"] = np.round(solar_generation_kwh, 4)
        df["actual_surplus_or_need"] = np.round(net_surplus_need, 4)

        return df


if __name__ == "__main__":
    simulator = IndianMicrogridSimulator()
    df = simulator.generate_microgrid_dataset(start_date="2024-03-01", end_date="2024-03-05")
    print(f"Total simulated rows: {len(df)}")
    print("Nodes summary:")
    print(df.groupby("node_id")[["actual_load_kwh", "actual_solar_kwh", "actual_surplus_or_need"]].mean())
