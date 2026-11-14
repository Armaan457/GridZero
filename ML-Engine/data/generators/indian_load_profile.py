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

import appliances as ap
from data.generators.weather_fetcher import WeatherFetcher


def solar_shape(hour: int) -> float:
    return max(0.0, math.sin(math.pi * (hour - 6) / 12.0)) if 6 <= hour <= 18 else 0.0


def solar_factor(cloud: float) -> float:
    """Fraction of clear-sky output at a given cloud cover fraction (0..1)."""
    return max(0.0, 1.0 - 0.8 * min(max(cloud, 0.0), 1.0))


class IndianMicrogridSimulator:

    def __init__(self, config_path: Optional[Path] = None):
        if config_path is None:
            config_path = (
                Path(__file__).resolve().parent.parent / "archetypes" / "nodes_config.yaml"
            )
        with open(config_path, "r", encoding="utf-8") as f:
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
        temps = df["temperature_c"].values
        cloud_pcts = df["cloud_cover_pct"].values

        node_id = str(node["id"])
        node_name = str(node.get("name", node_id))
        node_type = str(node.get("type", "residential_consumer"))
        hh_size = int(node.get("household_size", 4))
        solar_kw = float(node.get("solar_capacity_kw", 0.0))

        raw_apps = node.get("appliances", {})
        if isinstance(raw_apps, dict):
            catalog_items = raw_apps.get("catalog", [])
            ac_units_cfg = raw_apps.get("ac_units")
            has_ev_cfg = raw_apps.get("has_ev", False)
        elif isinstance(raw_apps, list):
            catalog_items = raw_apps
            ac_units_cfg = None
            has_ev_cfg = False
        else:
            catalog_items = []
            ac_units_cfg = None
            has_ev_cfg = False

        app_list = []
        if catalog_items:
            for item in catalog_items:
                if isinstance(item, str):
                    app_list.append(ap.make_appliance(item))
                elif isinstance(item, dict):
                    t = item.get("type", "custom")
                    overrides = {k: v for k, v in item.items() if k != "type"}
                    app_list.append(ap.make_appliance(t, **overrides))
        else:
            app_list = ap.default_appliances(hh_size)

        ac_units = ac_units_cfg if ac_units_cfg is not None else sum(
            1 for a in app_list if str(a.get("type", "")).lower().startswith("ac")
        )
        has_ev = int(bool(has_ev_cfg or any(str(a.get("type", "")).lower() == "ev" for a in app_list)))

        # Pre-schedule flexible appliances into daytime solar peak hours
        unique_dates = df["datetime"].dt.date.unique()
        flex_sched = {}
        for d in unique_dates:
            for a in app_list:
                if a.get("flexible"):
                    w_start, w_end = a["start"], a["end"]
                    dur = min(a["duration_h"], max(1, w_end - w_start))
                    cand = list(range(w_start, w_end))
                    cand.sort(key=lambda h: -solar_shape(h))
                    flex_sched[(d, a["id"])] = sorted(cand[:dur])

        loads = np.zeros(n)
        solars = np.zeros(n)
        start_dt = df["datetime"].min()

        for i in range(n):
            dt = df["datetime"].iloc[i]
            h = int(hours[i])
            day_idx = int((dt - start_dt).total_seconds() // 86400)
            d_date = dt.date()
            temp = float(temps[i])
            cloud_frac = float(np.clip(cloud_pcts[i] / 100.0, 0.0, 1.0))

            # Set scheduled hours for flexible loads
            for a in app_list:
                if a.get("flexible"):
                    a["sched"] = flex_sched.get((d_date, a["id"]), list(range(a["start"], a["start"] + a["duration_h"])))

            # Sum appliance expectations matching appliances.py
            base_kw = ap.STANDBY_KW * np.random.uniform(0.85, 1.15)
            slot_load = base_kw
            for a in app_list:
                ekw = ap.expected_kw(a, day_idx, h, temp)
                if ekw > 0:
                    slot_load += ekw * np.random.uniform(0.92, 1.08)

            # Solar generation matching Simulation Engine
            s_sh = solar_shape(h)
            s_fac = solar_factor(cloud_frac)
            if solar_kw > 0 and s_sh > 0:
                slot_solar = solar_kw * s_sh * s_fac * 0.95 * np.random.uniform(0.92, 1.0)
            else:
                slot_solar = 0.0

            loads[i] = np.clip(slot_load, 0.03, 20.0)
            solars[i] = np.clip(slot_solar, 0.0, solar_kw * 1.05)

        net_surplus_need = solars - loads

        df["node_id"] = node_id
        df["node_name"] = node_name
        df["node_type"] = node_type
        df["household_size"] = hh_size
        df["solar_capacity_kw"] = solar_kw
        df["ac_units"] = ac_units
        df["has_ev"] = has_ev
        df["actual_load_kwh"] = np.round(loads, 4)
        df["actual_solar_kwh"] = np.round(solars, 4)
        df["actual_surplus_or_need"] = np.round(net_surplus_need, 4)

        return df


if __name__ == "__main__":
    simulator = IndianMicrogridSimulator()
    df = simulator.generate_microgrid_dataset(start_date="2024-03-01", end_date="2024-03-05")
    print(f"Total simulated rows: {len(df)}")
    print("Nodes summary:")
    print(df.groupby("node_id")[["actual_load_kwh", "actual_solar_kwh", "actual_surplus_or_need"]].mean())
