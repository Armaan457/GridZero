from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class QuantileForecastValues(BaseModel):
    p10: float
    p50: float
    p90: float


class SingleNodeForecastRequest(BaseModel):
    node_id: str = Field(..., example="node_01")
    datetime_str: str = Field(..., example="2024-03-05 14:00:00")
    temperature_c: float = Field(31.0, example=31.0)
    ghi_w_m2: float = Field(820.0, example=820.0)
    dni_w_m2: float = Field(780.0, example=780.0)
    dhi_w_m2: float = Field(150.0, example=150.0)
    cloud_cover_pct: float = Field(12.0, example=12.0)
    humidity_pct: float = Field(45.0, example=45.0)
    solar_capacity_kw: Optional[float] = Field(None, example=5.0)
    household_size: Optional[int] = Field(None, example=3)
    ac_units: Optional[int] = Field(None, example=1)
    has_ev: Optional[int] = Field(None, example=0)
    recent_actual_load_kwh: Optional[float] = Field(0.85, example=0.85)
    recent_actual_solar_kwh: Optional[float] = Field(3.90, example=3.90)


class SingleNodeForecastResponse(BaseModel):
    node_id: str
    datetime: str
    market_role: str
    load_kwh: QuantileForecastValues
    solar_kwh: QuantileForecastValues
    net_surplus_or_need_kwh: QuantileForecastValues
    confidence_spread_kwh: float


class HorizonForecastRequest(BaseModel):
    city: str = Field("Bengaluru", example="Bengaluru")
    date: str = Field("2024-03-05", example="2024-03-05")
    simulate_weather_shock: bool = Field(False)
    shock_cloud_pct_increase: float = Field(65.0)


class MarketClearRequest(BaseModel):
    city: str = Field("Bengaluru", example="Bengaluru")
    date: str = Field("2024-03-05", example="2024-03-05")
    grid_import_rate_inr: float = Field(8.20, example=8.20)
    grid_export_rate_inr: float = Field(2.45, example=2.45)
    p2p_clearing_rate_inr: float = Field(5.30, example=5.30)
    risk_mode: str = Field("p50", example="p50")
    simulate_weather_shock: bool = Field(False)
    shock_cloud_pct_increase: float = Field(65.0)


class AdvisoryRequest(BaseModel):
    node_id: str = Field(..., example="node_01")
    date: str = Field("2024-03-05", example="2024-03-05")
    peak_slot: Optional[str] = Field("13:00–15:00", example="13:00–15:00")
    peak_surplus_kwh: Optional[float] = Field(3.8, example=3.8)
    p10_surplus: Optional[float] = Field(2.9, example=2.9)
    p90_surplus: Optional[float] = Field(4.4, example=4.4)
    matched_peer: Optional[str] = Field("Iyengar Bakery & Vikram Mehta", example="Iyengar Bakery & Vikram Mehta")
    estimated_earnings_inr: Optional[float] = Field(19.95, example=19.95)
    grid_comparison_inr: Optional[float] = Field(9.31, example=9.31)
    weather_summary: Optional[str] = Field("Clear sunny skies", example="Clear sunny skies")
    include_shap: Optional[bool] = Field(False, example=False)


class ShapExplainRequest(BaseModel):
    node_id: str = Field("node_01", example="node_01")
    datetime_str: str = Field("2024-03-05 14:00:00", example="2024-03-05 14:00:00")
    temperature_c: float = Field(31.0, example=31.0)
    ghi_w_m2: float = Field(820.0, example=820.0)
    dni_w_m2: float = Field(780.0, example=780.0)
    dhi_w_m2: float = Field(150.0, example=150.0)
    cloud_cover_pct: float = Field(12.0, example=12.0)
    humidity_pct: float = Field(45.0, example=45.0)
    solar_capacity_kw: Optional[float] = Field(None, example=5.0)
    household_size: Optional[int] = Field(None, example=3)
    ac_units: Optional[int] = Field(None, example=1)
    has_ev: Optional[int] = Field(None, example=0)
    recent_actual_load_kwh: Optional[float] = Field(0.85, example=0.85)
    recent_actual_solar_kwh: Optional[float] = Field(3.90, example=3.90)
    top_k: int = Field(3, example=3)


class WeatherShockAdvisoryRequest(BaseModel):
    cloud_surge_pct: float = Field(65.0, example=65.0)
    drop_in_solar_kwh: float = Field(4.2, example=4.2)
    affected_hours: str = Field("13:00–16:00", example="13:00–16:00")


class TrainingRequest(BaseModel):
    start_date: str = Field("2024-01-01", example="2024-01-01")
    end_date: str = Field("2024-02-28", example="2024-02-28")
