from __future__ import annotations
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import numpy as np
import pandas as pd
from fastapi import APIRouter, BackgroundTasks


def resolve_target_date(date_input: Optional[str] = None) -> str:
    """Resolves 'today', 'tomorrow', None, or an ISO YYYY-MM-DD date string.
    - 'today' or None or empty -> datetime.now().strftime("%Y-%m-%d")
    - 'tomorrow' or 'day_ahead' -> (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    - 'yesterday' -> (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    - standard YYYY-MM-DD string -> validates and returns as-is
    """
    if not date_input or not isinstance(date_input, str):
        return datetime.now().strftime("%Y-%m-%d")

    clean = date_input.strip().lower()
    if clean in ("today", "now", "current"):
        return datetime.now().strftime("%Y-%m-%d")
    elif clean in ("tomorrow", "next_day", "day_ahead", "d+1"):
        return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    elif clean in ("yesterday", "d-1"):
        return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    elif len(clean) == 10 and clean.count("-") == 2:
        return clean

    return datetime.now().strftime("%Y-%m-%d")


def resolve_slot_datetime(dt_input: Optional[str] = None, default_hour: int = 14) -> str:
    """Resolves slot timestamps like 'tomorrow 14:00:00', 'today 14:00:00', 'tomorrow', or None."""
    if not dt_input or not isinstance(dt_input, str):
        return f"{datetime.now().strftime('%Y-%m-%d')} {default_hour:02d}:00:00"

    clean = dt_input.strip()
    lower = clean.lower()
    if lower.startswith("tomorrow"):
        t_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        time_part = clean[8:].strip() or f"{default_hour:02d}:00:00"
        return f"{t_date} {time_part}"
    elif lower.startswith("today"):
        t_date = datetime.now().strftime("%Y-%m-%d")
        time_part = clean[5:].strip() or f"{default_hour:02d}:00:00"
        return f"{t_date} {time_part}"
    elif len(clean) <= 8 and ":" in clean:
        return f"{datetime.now().strftime('%Y-%m-%d')} {clean}"
    elif len(clean) == 10 and clean.count("-") == 2:
        return f"{clean} {default_hour:02d}:00:00"

    return clean

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from data.generators.weather_fetcher import CITY_COORDINATES
from data.generators.indian_load_profile import IndianMicrogridSimulator
from models.lgbm_forecaster import QuantileEnergyForecaster
from models.explainability import EnergyExplainer
from market.p2p_clearing import MicrogridP2PClearingEngine
from aws.bedrock_agent import BedrockEnergyAgent
from app.models import (
    SingleNodeForecastRequest,
    SingleNodeForecastResponse,
    QuantileForecastValues,
    HorizonForecastRequest,
    MarketClearRequest,
    AdvisoryRequest,
    ShapExplainRequest,
    WeatherShockSenseRequest,
    WeatherShockAdvisoryRequest,
    TrainingRequest,
)

router = APIRouter()

_SIMULATOR: Optional[IndianMicrogridSimulator] = None
_FORECASTER: Optional[QuantileEnergyForecaster] = None
_CLEARING_ENGINE: Optional[MicrogridP2PClearingEngine] = None
_BEDROCK_AGENT: Optional[BedrockEnergyAgent] = None
_EXPLAINER: Optional[EnergyExplainer] = None


def get_explainer() -> EnergyExplainer:
    global _EXPLAINER
    if _EXPLAINER is None:
        _, forecaster, _, _ = get_components()
        _EXPLAINER = EnergyExplainer(forecaster)
    return _EXPLAINER


def get_components():
    global _SIMULATOR, _FORECASTER, _CLEARING_ENGINE, _BEDROCK_AGENT

    if _SIMULATOR is None:
        _SIMULATOR = IndianMicrogridSimulator()

    if _CLEARING_ENGINE is None:
        _CLEARING_ENGINE = MicrogridP2PClearingEngine()

    if _BEDROCK_AGENT is None:
        _BEDROCK_AGENT = BedrockEnergyAgent()

    if _FORECASTER is None:
        _FORECASTER = QuantileEnergyForecaster()
        try:
            _FORECASTER.load()
        except Exception:
            df_boot = _SIMULATOR.generate_microgrid_dataset(
                start_date="2024-03-01", end_date="2024-03-07"
            )
            _FORECASTER.train(df_boot, num_boost_round=60)

    return _SIMULATOR, _FORECASTER, _CLEARING_ENGINE, _BEDROCK_AGENT


@router.get("/", tags=["General"])
def root_info():
    return {
        "service": "P2P-ES Microgrid Intelligence Microservice",
        "version": "1.0.0",
        "status": "online",
        "documentation": "/docs",
        "available_cities": list(CITY_COORDINATES.keys()),
        "endpoints": [
            "GET  /health",
            "GET  /nodes",
            "POST /forecast/node",
            "POST /forecast/explain",
            "POST /forecast/explain-grid",
            "POST /forecast/microgrid",
            "POST /market/clear",
            "POST /agent/advisory",
            "POST /agent/sense-weather-shock",
            "POST /agent/weather-shock",
            "POST /models/train",
        ],
    }


@router.get("/health", tags=["General"])
def health_check():
    sim, forecaster, clearing, agent = get_components()
    return {
        "status": "healthy",
        "models_loaded": len(forecaster.load_models) > 0 and len(forecaster.solar_models) > 0,
        "nodes_count": len(sim.nodes),
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/nodes", tags=["Topology"])
def get_microgrid_nodes():
    sim, _, _, _ = get_components()
    return {
        "microgrid_id": sim.config.get("microgrid_id", "mg_bengaluru_east_01"),
        "grid_reference_rates": sim.config.get("grid_reference_rates", {}),
        "total_nodes": len(sim.nodes),
        "nodes": sim.nodes,
    }


@router.post("/forecast/node", response_model=SingleNodeForecastResponse, tags=["Forecasting"])
def forecast_single_node(payload: SingleNodeForecastRequest):
    sim, forecaster, _, _ = get_components()

    node_meta = next((n for n in sim.nodes if n["id"] == payload.node_id), None)
    solar_kw = payload.solar_capacity_kw if payload.solar_capacity_kw is not None else (node_meta.get("solar_capacity_kw", 0.0) if node_meta else 0.0)
    hh_size = payload.household_size if payload.household_size is not None else (node_meta.get("household_size", 3) if node_meta else 3)
    ac_units = payload.ac_units if payload.ac_units is not None else (node_meta.get("appliances", {}).get("ac_units", 0) if node_meta else 0)
    has_ev = payload.has_ev if payload.has_ev is not None else (int(node_meta.get("appliances", {}).get("has_ev", False)) if node_meta else 0)

    target_dt = resolve_slot_datetime(payload.datetime_str)
    df_row = pd.DataFrame([{
        "datetime": pd.to_datetime(target_dt),
        "node_id": payload.node_id,
        "temperature_c": payload.temperature_c,
        "ghi_w_m2": payload.ghi_w_m2,
        "dni_w_m2": payload.dni_w_m2,
        "dhi_w_m2": payload.dhi_w_m2,
        "cloud_cover_pct": payload.cloud_cover_pct,
        "humidity_pct": payload.humidity_pct,
        "solar_capacity_kw": solar_kw,
        "household_size": hh_size,
        "ac_units": ac_units,
        "has_ev": has_ev,
        "actual_load_kwh": payload.recent_actual_load_kwh,
        "actual_solar_kwh": payload.recent_actual_solar_kwh,
    }])

    preds = forecaster.predict(df_row).iloc[0]
    surplus = float(preds["pred_surplus_or_need"])
    role = "SURPLUS_SELLER" if surplus > 0.05 else ("DEFICIT_BUYER" if surplus < -0.05 else "BALANCED")

    return SingleNodeForecastResponse(
        node_id=payload.node_id,
        datetime=str(preds["datetime"]),
        market_role=role,
        load_kwh=QuantileForecastValues(
            p10=float(preds["pred_load_p10"]),
            p50=float(preds["pred_load"]),
            p90=float(preds["pred_load_p90"]),
        ),
        solar_kwh=QuantileForecastValues(
            p10=float(preds["pred_solar_p10"]),
            p50=float(preds["pred_solar"]),
            p90=float(preds["pred_solar_p90"]),
        ),
        net_surplus_or_need_kwh=QuantileForecastValues(
            p10=float(preds["pred_surplus_p10"]),
            p50=surplus,
            p90=float(preds["pred_surplus_p90"]),
        ),
        confidence_spread_kwh=float(preds["confidence_spread"]),
    )


@router.post("/forecast/explain", tags=["Explainability"])
def explain_forecast_slot(payload: ShapExplainRequest):
    sim, forecaster, _, agent = get_components()
    explainer = get_explainer()

    target_dt = resolve_slot_datetime(payload.datetime_str)
    parsed_dt = pd.to_datetime(target_dt)
    target_date = parsed_dt.strftime("%Y-%m-%d")

    is_grid = payload.node_id in ("microgrid", "grid", "all", "community", None)

    if is_grid:
        city = payload.city or "Bengaluru"
        df_all = sim.generate_microgrid_dataset(
            city=city, start_date=target_date, end_date=target_date
        )
        df_slot = df_all[df_all["datetime"].dt.hour == parsed_dt.hour].copy()
        if df_slot.empty:
            df_slot = df_all.iloc[:len(sim.nodes)].copy()

        preds = forecaster.predict(df_slot)
        total_load = float(preds["pred_load"].sum())
        total_solar = float(preds["pred_solar"].sum())
        total_surplus = float(preds["pred_surplus_or_need"].sum())

        shap_result = explainer.explain_microgrid_slot(df_slot, top_k=payload.top_k)
        node_name = "Community Microgrid Feeder"
        ai_explanation = agent.generate_shap_explanation(
            node_name=node_name,
            shap_explanation=shap_result,
            surplus_kwh=total_surplus,
            slot_time=str(target_dt),
        )

        return {
            "node_id": "microgrid",
            "node_name": node_name,
            "datetime": str(target_dt),
            "predicted_load_kwh": round(total_load, 2),
            "predicted_solar_kwh": round(total_solar, 2),
            "predicted_surplus_kwh": round(total_surplus, 2),
            "shap_drivers": shap_result,
            "ai_explanation": ai_explanation,
            "engine": agent.last_invocation_source,
            "model_id": agent.active_model_id if agent.last_invocation_source == "aws_bedrock" else "offline_fallback",
            "fallback_reason": agent.last_error if agent.last_invocation_source == "offline_fallback" else None,
        }

    node_meta = next((n for n in sim.nodes if n["id"] == payload.node_id), None)
    solar_kw = payload.solar_capacity_kw if payload.solar_capacity_kw is not None else (node_meta.get("solar_capacity_kw", 0.0) if node_meta else 0.0)
    hh_size = payload.household_size if payload.household_size is not None else (node_meta.get("household_size", 3) if node_meta else 3)
    ac_units = payload.ac_units if payload.ac_units is not None else (node_meta.get("appliances", {}).get("ac_units", 0) if node_meta else 0)
    has_ev = payload.has_ev if payload.has_ev is not None else (int(node_meta.get("appliances", {}).get("has_ev", False)) if node_meta else 0)

    df_row = pd.DataFrame([{
        "datetime": pd.to_datetime(target_dt),
        "node_id": payload.node_id,
        "temperature_c": payload.temperature_c,
        "ghi_w_m2": payload.ghi_w_m2,
        "dni_w_m2": payload.dni_w_m2,
        "dhi_w_m2": payload.dhi_w_m2,
        "cloud_cover_pct": payload.cloud_cover_pct,
        "humidity_pct": payload.humidity_pct,
        "solar_capacity_kw": solar_kw,
        "household_size": hh_size,
        "ac_units": ac_units,
        "has_ev": has_ev,
        "actual_load_kwh": payload.recent_actual_load_kwh,
        "actual_solar_kwh": payload.recent_actual_solar_kwh,
    }])

    preds = forecaster.predict(df_row).iloc[0]
    surplus = float(preds["pred_surplus_or_need"])
    node_name = node_meta["name"] if node_meta else payload.node_id

    shap_result = explainer.explain_slot(df_row, top_k=payload.top_k)
    ai_explanation = agent.generate_shap_explanation(
        node_name=node_name,
        shap_explanation=shap_result,
        surplus_kwh=surplus,
        slot_time=str(target_dt),
    )

    return {
        "node_id": payload.node_id,
        "node_name": node_name,
        "datetime": str(preds["datetime"]),
        "predicted_load_kwh": float(preds["pred_load"]),
        "predicted_solar_kwh": float(preds["pred_solar"]),
        "predicted_surplus_kwh": surplus,
        "shap_drivers": shap_result,
        "ai_explanation": ai_explanation,
        "engine": agent.last_invocation_source,
        "model_id": agent.active_model_id if agent.last_invocation_source == "aws_bedrock" else "offline_fallback",
        "fallback_reason": agent.last_error if agent.last_invocation_source == "offline_fallback" else None,
    }


@router.post("/forecast/explain-grid", tags=["Explainability"])
def explain_microgrid_slot_endpoint(payload: ShapExplainRequest = ShapExplainRequest()):
    payload.node_id = "microgrid"
    return explain_forecast_slot(payload)


@router.post("/forecast/microgrid", tags=["Forecasting"])
def forecast_microgrid_horizon(req: HorizonForecastRequest):
    sim, forecaster, _, _ = get_components()
    target_date = resolve_target_date(req.date)

    df = sim.generate_microgrid_dataset(
        city=req.city, start_date=target_date, end_date=target_date
    )

    if req.simulate_weather_shock:
        afternoon = (df["datetime"].dt.hour >= 13) & (df["datetime"].dt.hour <= 16)
        df.loc[afternoon, "cloud_cover_pct"] = np.clip(
            df.loc[afternoon, "cloud_cover_pct"] + req.shock_cloud_pct_increase, 0, 100
        )
        df.loc[afternoon, "ghi_w_m2"] = np.clip(
            df.loc[afternoon, "ghi_w_m2"] * (1.0 - req.shock_cloud_pct_increase / 120.0), 50, 1000
        )

    preds = forecaster.predict(df)

    summary_by_node = {}
    for node_id, grp in preds.groupby("node_id"):
        summary_by_node[node_id] = {
            "node_name": str(grp["node_name"].iloc[0]),
            "node_type": str(grp["node_type"].iloc[0]),
            "total_solar_24h_kwh": round(float(grp["pred_solar"].sum()), 2),
            "total_load_24h_kwh": round(float(grp["pred_load"].sum()), 2),
            "net_balance_24h_kwh": round(float(grp["pred_surplus_or_need"].sum()), 2),
            "hourly_slots": [
                {
                    "hour": int(row["datetime"].hour),
                    "pred_load": float(row["pred_load"]),
                    "pred_solar": float(row["pred_solar"]),
                    "pred_surplus": float(row["pred_surplus_or_need"]),
                    "confidence_p10": float(row["pred_surplus_p10"]),
                    "confidence_p90": float(row["pred_surplus_p90"]),
                }
                for _, row in grp.iterrows()
            ],
        }

    return {
        "city": req.city,
        "date": target_date,
        "weather_shock_applied": req.simulate_weather_shock,
        "nodes": summary_by_node,
    }


@router.post("/market/clear", tags=["Market"])
def clear_p2p_market(req: MarketClearRequest):
    sim, forecaster, clearing, _ = get_components()
    target_date = resolve_target_date(req.date)

    clearing.grid_import_rate = req.grid_import_rate_inr
    clearing.grid_export_rate = req.grid_export_rate_inr
    clearing.p2p_clearing_rate = req.p2p_clearing_rate_inr

    df = sim.generate_microgrid_dataset(
        city=req.city, start_date=target_date, end_date=target_date
    )

    if req.simulate_weather_shock:
        afternoon = (df["datetime"].dt.hour >= 13) & (df["datetime"].dt.hour <= 16)
        df.loc[afternoon, "cloud_cover_pct"] = np.clip(
            df.loc[afternoon, "cloud_cover_pct"] + req.shock_cloud_pct_increase, 0, 100
        )
        df.loc[afternoon, "ghi_w_m2"] = np.clip(
            df.loc[afternoon, "ghi_w_m2"] * (1.0 - req.shock_cloud_pct_increase / 120.0), 50, 1000
        )

    preds = forecaster.predict(df)
    results = clearing.clear_horizon(preds, risk_mode=req.risk_mode)
    summary_df = clearing.summarize_to_dataframe(results)

    total_traded_kwh = round(float(summary_df["p2p_traded_kwh"].sum()), 2)
    total_savings_inr = round(float(summary_df["community_savings_inr"].sum()), 2)
    total_solar_kwh = round(float(summary_df["solar_kwh"].sum()), 2)
    total_load_kwh = round(float(summary_df["load_kwh"].sum()), 2)

    slots_data = []
    for r in results:
        slots_data.append({
            "slot": r.slot,
            "solar_kwh": r.total_solar_gen_kwh,
            "load_kwh": r.total_load_kwh,
            "surplus_kwh": r.total_surplus_kwh,
            "deficit_kwh": r.total_deficit_kwh,
            "p2p_traded_kwh": r.total_p2p_traded_kwh,
            "community_savings_inr": r.community_savings_inr,
            "trades_count": len(r.trades),
            "trades": [
                {
                    "seller": t.seller_name,
                    "buyer": t.buyer_name,
                    "kwh": t.energy_kwh,
                    "price_inr": t.clearing_price_inr,
                    "seller_profit_inr": t.seller_earnings_inr,
                    "buyer_savings_inr": t.buyer_savings_inr,
                }
                for t in r.trades
            ],
        })

    return {
        "date": target_date,
        "city": req.city,
        "risk_mode": req.risk_mode,
        "totals": {
            "solar_kwh": total_solar_kwh,
            "load_kwh": total_load_kwh,
            "p2p_traded_kwh": total_traded_kwh,
            "community_savings_inr": total_savings_inr,
            "p2p_coverage_pct": round((total_traded_kwh / total_load_kwh * 100) if total_load_kwh else 0, 1),
        },
        "slots": slots_data,
    }


@router.post("/agent/advisory", tags=["GenAI Agent"])
def get_agent_advisory(req: AdvisoryRequest):
    sim, _, _, agent = get_components()
    target_date = resolve_target_date(req.date or "tomorrow")
    node_meta = next((n for n in sim.nodes if n["id"] == req.node_id), None)
    node_name = node_meta["name"] if node_meta else req.node_id
    node_type = node_meta["type"] if node_meta else "microgrid_node"

    shap_data = None
    if req.include_shap:
        explainer = get_explainer()
        node_df = pd.DataFrame([{
            "datetime": pd.to_datetime(f"{target_date} 14:00:00"),
            "node_id": req.node_id,
            "temperature_c": 31.0,
            "ghi_w_m2": 820.0,
            "dni_w_m2": 780.0,
            "dhi_w_m2": 150.0,
            "cloud_cover_pct": 15.0,
            "humidity_pct": 45.0,
            "solar_capacity_kw": node_meta.get("solar_capacity_kw", 0.0) if node_meta else 0.0,
            "household_size": node_meta.get("household_size", 3) if node_meta else 3,
            "ac_units": node_meta.get("appliances", {}).get("ac_units", 0) if node_meta else 0,
            "has_ev": int(node_meta.get("appliances", {}).get("has_ev", False)) if node_meta else 0,
            "actual_load_kwh": 0.85,
            "actual_solar_kwh": 3.90,
        }])
        shap_data = explainer.explain_slot(node_df, top_k=3)

    msg = agent.generate_advisory(
        node_name=node_name,
        node_type=node_type,
        peak_surplus_slot=req.peak_slot,
        peak_surplus_kwh=req.peak_surplus_kwh,
        p10_surplus=req.p10_surplus,
        p90_surplus=req.p90_surplus,
        matched_peer=req.matched_peer,
        estimated_earnings_inr=req.estimated_earnings_inr,
        grid_comparison_inr=req.grid_comparison_inr,
        weather_summary=req.weather_summary,
        shap_explanation=shap_data,
    )
    res = {
        "node_id": req.node_id,
        "node_name": node_name,
        "advisory": msg,
        "engine": agent.last_invocation_source,
        "model_id": agent.active_model_id if agent.last_invocation_source == "aws_bedrock" else "offline_fallback",
        "fallback_reason": agent.last_error if agent.last_invocation_source == "offline_fallback" else None,
    }
    if req.include_shap and shap_data:
        res["shap_drivers"] = shap_data
    return res


@router.post("/agent/sense-weather-shock", tags=["GenAI Agent"])
@router.post("/weather/sense-shock", tags=["GenAI Agent"])
def sense_weather_shock(req: WeatherShockSenseRequest):
    sim, _, _, agent = get_components()
    target_date = resolve_target_date(req.date or "today")
    weather_df = sim.weather_fetcher.fetch_weather(
        city=req.city, start_date=target_date, end_date=target_date
    )
    total_solar_kw = sum(n.get("solar_capacity_kw", 0.0) for n in sim.nodes)

    day_mask = (weather_df["datetime"].dt.hour >= 8) & (weather_df["datetime"].dt.hour <= 17)
    day_df = weather_df[day_mask].copy()

    day_df["cloud_diff"] = day_df["cloud_cover_pct"].diff().fillna(0)
    max_cloud_jump = float(day_df["cloud_diff"].max()) if not day_df.empty else 0.0
    afternoon_mask = (weather_df["datetime"].dt.hour >= 12) & (weather_df["datetime"].dt.hour <= 16)
    mean_afternoon_cloud = float(weather_df[afternoon_mask]["cloud_cover_pct"].mean()) if any(afternoon_mask) else 15.0
    min_midday_ghi = float(weather_df[(weather_df["datetime"].dt.hour >= 11) & (weather_df["datetime"].dt.hour <= 15)]["ghi_w_m2"].min()) if any(afternoon_mask) else 600.0

    shock_detected = False
    shock_type = "NONE"
    affected_hours = "13:00–16:00"
    cloud_surge_pct = 0.0
    solar_loss_kwh = 0.0

    if req.simulate_test_shock:
        shock_detected = True
        shock_type = "Monsoonal Cloudburst (Simulated)"
        affected_hours = "13:00–16:00"
        cloud_surge_pct = 65.0
        ghi_drop = 540.0
        solar_loss_kwh = round(total_solar_kw * (ghi_drop / 1000.0) * 3.0 * 0.28, 2)
    elif max_cloud_jump >= 35.0 or mean_afternoon_cloud >= 60.0 or min_midday_ghi <= 250.0:
        shock_detected = True
        peak_idx = day_df["cloud_diff"].idxmax()
        peak_hour = int(day_df.loc[peak_idx, "datetime"].hour)
        start_h = max(8, peak_hour - 1)
        end_h = min(17, peak_hour + 2)
        affected_hours = f"{start_h:02d}:00–{end_h:02d}:00"
        cloud_surge_pct = round(max(max_cloud_jump, mean_afternoon_cloud), 1)
        ghi_drop = max(300.0, 800.0 - min_midday_ghi)
        dur = max(1, end_h - start_h)
        solar_loss_kwh = round(total_solar_kw * (ghi_drop / 1000.0) * dur * 0.18, 2)
        shock_type = "Intraday Cloud Surge" if max_cloud_jump >= 35.0 else "Storm Front Overcast"

    if shock_detected:
        alert_text = agent.generate_weather_shock_alert(
            city=req.city,
            cloud_surge_pct=cloud_surge_pct,
            drop_in_solar_kwh=solar_loss_kwh,
            affected_hours=affected_hours,
            shock_type=shock_type,
        )
        return {
            "city": req.city,
            "date": target_date,
            "shock_detected": True,
            "shock_type": shock_type,
            "affected_hours": affected_hours,
            "cloud_surge_pct": cloud_surge_pct,
            "estimated_solar_loss_kwh": solar_loss_kwh,
            "alert_severity": "HIGH",
            "simulated": req.simulate_test_shock,
            "alert": alert_text,
            "recommended_action": "Pause non-essential EV charging; shift battery storage to discharge mode; activate P2P dynamic reserves.",
            "engine": agent.last_invocation_source,
            "model_id": agent.active_model_id if agent.last_invocation_source == "aws_bedrock" else "offline_fallback",
        }
    else:
        return {
            "city": req.city,
            "date": target_date,
            "shock_detected": False,
            "shock_type": "NONE",
            "affected_hours": None,
            "cloud_surge_pct": 0.0,
            "estimated_solar_loss_kwh": 0.0,
            "alert_severity": "NORMAL",
            "simulated": False,
            "status": "STABLE_CONDITIONS",
            "alert": f"Clear weather in {req.city} today. No solar generation shock detected across the feeder.",
            "recommended_action": "Standard P2P clearing active. Microgrid generation tracking within nominal forecast bands.",
            "engine": agent.last_invocation_source,
            "model_id": agent.active_model_id if agent.last_invocation_source == "aws_bedrock" else "offline_fallback",
        }


@router.post("/agent/weather-shock", tags=["GenAI Agent"])
def get_weather_shock_alert(req: WeatherShockAdvisoryRequest):
    _, _, _, agent = get_components()
    alert_text = agent.generate_weather_shock_alert(
        city=req.city or "Bengaluru",
        cloud_surge_pct=req.cloud_surge_pct,
        drop_in_solar_kwh=req.drop_in_solar_kwh,
        affected_hours=req.affected_hours,
        shock_type=req.shock_type or "Monsoonal Cloudburst",
    )
    return {
        "alert": alert_text,
        "city": req.city or "Bengaluru",
        "cloud_surge_pct": req.cloud_surge_pct,
        "drop_in_solar_kwh": req.drop_in_solar_kwh,
        "affected_hours": req.affected_hours,
    }


@router.post("/models/train", tags=["Training"])
def trigger_training(req: TrainingRequest, background_tasks: BackgroundTasks):
    from aws.train_pipeline import run_training_pipeline

    target_bucket = os.environ.get("S3_BUCKET_NAME")

    def train_worker():
        run_training_pipeline(
            start_date=req.start_date,
            end_date=req.end_date,
            s3_bucket=target_bucket,
        )

    background_tasks.add_task(train_worker)
    return {
        "message": f"Training job scheduled from {req.start_date} to {req.end_date}",
        "s3_bucket": target_bucket,
        "status": "in_progress",
    }
