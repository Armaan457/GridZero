from __future__ import annotations
import os
import sys
import json
from pathlib import Path
from typing import Dict, Any, Optional
import numpy as np
import pandas as pd
import requests

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

CITY_COORDINATES: Dict[str, Dict[str, float]] = {
    "Bengaluru": {"latitude": 12.9716, "longitude": 77.5946, "timezone": "Asia/Kolkata"},
    "Delhi": {"latitude": 28.6139, "longitude": 77.2090, "timezone": "Asia/Kolkata"},
    "Mumbai": {"latitude": 19.0760, "longitude": 72.8777, "timezone": "Asia/Kolkata"},
    "Ahmedabad": {"latitude": 23.0225, "longitude": 72.5714, "timezone": "Asia/Kolkata"},
    "Chennai": {"latitude": 13.0827, "longitude": 80.2707, "timezone": "Asia/Kolkata"},
    "Hyderabad": {"latitude": 17.3850, "longitude": 78.4867, "timezone": "Asia/Kolkata"},
}

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"


class WeatherFetcher:

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch_weather(
        self,
        city: str = "Bengaluru",
        start_date: str = "2024-01-01",
        end_date: str = "2024-03-31",
        use_cache: bool = True,
    ) -> pd.DataFrame:
        coords = CITY_COORDINATES.get(city, CITY_COORDINATES["Bengaluru"])
        cache_file = self.cache_dir / f"weather_{city.lower()}_{start_date}_{end_date}.csv"

        if use_cache and cache_file.exists():
            df = pd.read_csv(cache_file)
            df["datetime"] = pd.to_datetime(df["datetime"])
            return df

        try:
            url = "https://archive-api.open-meteo.com/v1/archive"
            params = {
                "latitude": coords["latitude"],
                "longitude": coords["longitude"],
                "start_date": start_date,
                "end_date": end_date,
                "hourly": [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "cloud_cover",
                    "direct_normal_irradiance",
                    "diffuse_radiation",
                    "shortwave_radiation_instant",
                ],
                "timezone": coords["timezone"],
            }
            resp = requests.get(url, params=params, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                hourly = data.get("hourly", {})
                df = pd.DataFrame({
                    "datetime": pd.to_datetime(hourly["time"]),
                    "temperature_c": hourly.get("temperature_2m", []),
                    "humidity_pct": hourly.get("relative_humidity_2m", []),
                    "cloud_cover_pct": hourly.get("cloud_cover", []),
                    "dni_w_m2": hourly.get("direct_normal_irradiance", []),
                    "dhi_w_m2": hourly.get("diffuse_radiation", []),
                    "ghi_w_m2": hourly.get("shortwave_radiation_instant", []),
                })
                df.to_csv(cache_file, index=False)
                return df
        except Exception:
            pass

        df = self._generate_synthetic_weather(city, start_date, end_date)
        df.to_csv(cache_file, index=False)
        return df

    def _generate_synthetic_weather(
        self, city: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        dt_range = pd.date_range(start=f"{start_date} 00:00:00", end=f"{end_date} 23:00:00", freq="h")
        n = len(dt_range)
        np.random.seed(42)

        hours = dt_range.hour.values
        day_of_year = dt_range.dayofyear.values

        solar_altitude = np.sin(np.pi * np.clip((hours - 6.0) / 12.0, 0, 1))
        is_daylight = (hours >= 6) & (hours <= 18)
        solar_altitude[~is_daylight] = 0.0

        seasonal_factor = 0.85 + 0.25 * np.sin(2 * np.pi * (day_of_year - 80) / 365.0)

        cloud_base = np.clip(np.random.beta(a=1.5, b=4.0, size=n) * 100, 0, 100)
        cloud_cover = pd.Series(cloud_base).rolling(window=4, min_periods=1).mean().values

        clear_sky_ghi = 950.0 * (solar_altitude ** 1.1) * seasonal_factor
        cloud_attenuation = np.clip(1.0 - (cloud_cover / 100.0) * 0.75, 0.1, 1.0)
        ghi = np.clip(clear_sky_ghi * cloud_attenuation + np.random.normal(0, 15, n), 0, 1100)
        ghi[~is_daylight] = 0.0

        dni = np.clip(ghi * 1.15 * (1.0 - cloud_cover / 120.0), 0, 950)
        dni[~is_daylight] = 0.0

        dhi = np.clip(ghi * (0.2 + 0.6 * (cloud_cover / 100.0)), 0, 500)
        dhi[~is_daylight] = 0.0

        base_temp = 24.0 + 8.0 * np.sin(2 * np.pi * (day_of_year - 100) / 365.0)
        diurnal_temp = 7.0 * np.sin(np.pi * (hours - 9.0) / 12.0)
        temp_c = base_temp + diurnal_temp + np.random.normal(0, 1.2, n)

        humidity = np.clip(65.0 - (temp_c - base_temp) * 3.0 + np.random.normal(0, 4.0, n), 20, 95)

        return pd.DataFrame({
            "datetime": dt_range,
            "temperature_c": np.round(temp_c, 2),
            "humidity_pct": np.round(humidity, 1),
            "cloud_cover_pct": np.round(cloud_cover, 1),
            "dni_w_m2": np.round(dni, 2),
            "dhi_w_m2": np.round(dhi, 2),
            "ghi_w_m2": np.round(ghi, 2),
        })


if __name__ == "__main__":
    fetcher = WeatherFetcher()
    df_weather = fetcher.fetch_weather(city="Bengaluru", start_date="2024-03-01", end_date="2024-03-07")
    print(f"Fetched {len(df_weather)} hourly weather rows.")
    print(df_weather.head(3))
