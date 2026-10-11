from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional
import boto3
from botocore.exceptions import BotoCoreError, ClientError
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import aws.env_loader

# Friendly descriptions for SHAP features in human readable explanations
FEATURE_LABEL_MAP: Dict[str, str] = {
    "temperature_c": "ambient temperature",
    "temp_over_30": "extreme heat above 30°C",
    "cooling_degree_hour": "cooling heat index",
    "ghi_w_m2": "global solar irradiance (GHI)",
    "dni_w_m2": "direct sunlight (DNI)",
    "dhi_w_m2": "diffuse solar radiation",
    "cloud_cover_pct": "cloud cover",
    "humidity_pct": "relative humidity",
    "solar_capacity_kw": "installed solar capacity",
    "household_size": "household occupancy",
    "ac_units": "air conditioning load",
    "has_ev": "EV charger presence",
    "load_lag_24h": "yesterday's consumption at this hour",
    "load_lag_168h": "last week's consumption at this hour",
    "load_rolling_mean_3h": "recent 3-hour load trend",
    "solar_lag_24h": "yesterday's solar output at this hour",
    "solar_potential_theoretical": "clear-sky theoretical solar potential",
}


class BedrockEnergyAgent:

    def __init__(
        self,
        model_id: Optional[str] = None,
        region_name: Optional[str] = None,
    ):
        # Default to Amazon Titan Text Lite (cheapest AWS Bedrock model, ~80% cheaper than Claude Haiku)
        self.model_id = model_id or os.environ.get("BEDROCK_MODEL_ID", "amazon.titan-text-lite-v1")
        self.region_name = (
            region_name
            or os.environ.get("AWS_DEFAULT_REGION")
            or os.environ.get("AWS_REGION")
            or "us-east-1"
        )
        self.bedrock_client = None

        try:
            client_kwargs = {"region_name": self.region_name}
            if os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"):
                client_kwargs["aws_access_key_id"] = os.environ["AWS_ACCESS_KEY_ID"]
                client_kwargs["aws_secret_access_key"] = os.environ["AWS_SECRET_ACCESS_KEY"]
                if os.environ.get("AWS_SESSION_TOKEN"):
                    client_kwargs["aws_session_token"] = os.environ["AWS_SESSION_TOKEN"]

            self.bedrock_client = boto3.client(
                "bedrock-runtime",
                **client_kwargs,
            )
        except Exception:
            self.bedrock_client = None

    def _invoke_llm(self, prompt: str, max_tokens: int = 220) -> Optional[str]:
        """Invokes AWS Bedrock with payload adaptation for Titan, Claude, or Llama."""
        if self.bedrock_client is None:
            return None

        try:
            if "amazon.titan" in self.model_id:
                body = json.dumps({
                    "inputText": prompt,
                    "textGenerationConfig": {
                        "maxTokenCount": max_tokens,
                        "temperature": 0.3,
                        "topP": 0.9,
                    },
                })
                response = self.bedrock_client.invoke_model(
                    modelId=self.model_id,
                    body=body,
                )
                res_json = json.loads(response["body"].read())
                results = res_json.get("results", [])
                if results and "outputText" in results[0]:
                    return results[0]["outputText"].strip()

            elif "anthropic.claude" in self.model_id:
                body = json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": max_tokens,
                    "temperature": 0.3,
                    "messages": [{"role": "user", "content": prompt}],
                })
                response = self.bedrock_client.invoke_model(
                    modelId=self.model_id,
                    body=body,
                )
                res_json = json.loads(response["body"].read())
                return res_json["content"][0]["text"].strip()

            elif "meta.llama" in self.model_id:
                body = json.dumps({
                    "prompt": prompt,
                    "max_gen_len": max_tokens,
                    "temperature": 0.3,
                    "top_p": 0.9,
                })
                response = self.bedrock_client.invoke_model(
                    modelId=self.model_id,
                    body=body,
                )
                res_json = json.loads(response["body"].read())
                return res_json.get("generation", "").strip()

        except (BotoCoreError, ClientError, Exception):
            pass

        return None

    def generate_advisory(
        self,
        node_name: str,
        node_type: str,
        peak_surplus_slot: str,
        peak_surplus_kwh: float,
        p10_surplus: float,
        p90_surplus: float,
        matched_peer: str,
        estimated_earnings_inr: float,
        grid_comparison_inr: float,
        weather_summary: str = "Clear sunny conditions expected",
        shap_explanation: Optional[Dict[str, Any]] = None,
    ) -> str:
        shap_context = ""
        if shap_explanation:
            shap_text = self._format_shap_summary(shap_explanation)
            if shap_text:
                shap_context = f"\n- Key Drivers: {shap_text}"

        prompt = (
            f"You are the autonomous AI Dispatcher for an Indian Smart Microgrid.\n"
            f"Generate a friendly, concise, 2-3 sentence notification for {node_name} ({node_type}):\n"
            f"- Forecasted Net Peak: {peak_surplus_kwh:.1f} kWh at {peak_surplus_slot} "
            f"(Confidence Band: {p10_surplus:.1f} to {p90_surplus:.1f} kWh).\n"
            f"- Weather: {weather_summary}.\n"
            f"- P2P Matching: Matched with {matched_peer}.\n"
            f"- Economics: Earning/saving ₹{estimated_earnings_inr:.2f} locally vs ₹{grid_comparison_inr:.2f} via standard DISCOM grid.{shap_context}\n"
            f"Keep it punchy, motivating, and actionable. Include relevant emojis."
        )

        llm_reply = self._invoke_llm(prompt, max_tokens=220)
        if llm_reply:
            return llm_reply

        # Deterministic offline rule-based fallback
        if peak_surplus_kwh > 0.5:
            base = (
                f"☀️ Solar Surplus Alert for {node_name}: "
                f"You will likely have a {peak_surplus_kwh:.1f} kWh surplus around {peak_surplus_slot} "
                f"(confidence: {p10_surplus:.1f}–{p90_surplus:.1f} kWh). "
                f"We have pre-matched your excess with {matched_peer} at ₹5.30/kWh, "
                f"earning you ₹{estimated_earnings_inr:.2f} (vs only ₹{grid_comparison_inr:.2f} from DISCOM net-metering)."
            )
        elif peak_surplus_kwh < -0.5:
            need = abs(peak_surplus_kwh)
            base = (
                f"⚡ Demand Peak Notice for {node_name}: "
                f"Your high AC / appliance load requires {need:.1f} kWh around {peak_surplus_slot}. "
                f"We have scheduled peer power delivery from {matched_peer} at ₹5.30/kWh, "
                f"saving you ₹{estimated_earnings_inr:.2f} compared to peak DISCOM grid rates (₹8.20/kWh)."
            )
        else:
            base = (
                f"⚖️ Balanced Microgrid Status for {node_name}: "
                f"Your production and consumption are nearly in equilibrium around {peak_surplus_slot}. "
                f"Minimal grid dependency anticipated."
            )

        if shap_explanation:
            shap_fallback = self.generate_shap_explanation(node_name, shap_explanation, peak_surplus_kwh)
            return f"{base}\n\n{shap_fallback}"

        return base

    def _format_shap_summary(self, shap_explanation: Dict[str, Any]) -> str:
        parts = []
        for d in shap_explanation.get("solar_drivers", [])[:2]:
            feat_name = FEATURE_LABEL_MAP.get(d.get("feature"), d.get("feature"))
            impact = d.get("shap_impact", 0.0)
            sign = "+" if impact >= 0 else ""
            parts.append(f"{feat_name} ({sign}{impact:.2f} kWh solar)")
        for d in shap_explanation.get("load_drivers", [])[:2]:
            feat_name = FEATURE_LABEL_MAP.get(d.get("feature"), d.get("feature"))
            impact = d.get("shap_impact", 0.0)
            sign = "+" if impact >= 0 else ""
            parts.append(f"{feat_name} ({sign}{impact:.2f} kWh demand)")
        return ", ".join(parts)

    def generate_shap_explanation(
        self,
        node_name: str,
        shap_explanation: Dict[str, Any],
        surplus_kwh: float,
        slot_time: str = "",
    ) -> str:
        """Explains SHAP feature attributions in plain English for prosumers."""
        solar_drivers = shap_explanation.get("solar_drivers", [])[:3]
        load_drivers = shap_explanation.get("load_drivers", [])[:3]

        solar_lines = [
            f"- {FEATURE_LABEL_MAP.get(d['feature'], d['feature'])}: {d.get('shap_impact', 0.0):+.2f} kWh"
            for d in solar_drivers
        ]
        load_lines = [
            f"- {FEATURE_LABEL_MAP.get(d['feature'], d['feature'])}: {d.get('shap_impact', 0.0):+.2f} kWh"
            for d in load_drivers
        ]

        time_str = f" at {slot_time}" if slot_time else ""
        prompt = (
            f"You are the Explainable AI (XAI) assistant for a smart microgrid.\n"
            f"Explain why {node_name} has a net {'surplus' if surplus_kwh >= 0 else 'deficit'} of {abs(surplus_kwh):.1f} kWh{time_str}.\n"
            f"Solar generation drivers (SHAP impact):\n" + "\n".join(solar_lines) + "\n"
            f"Household demand drivers (SHAP impact):\n" + "\n".join(load_lines) + "\n\n"
            f"Provide a friendly, 2-sentence plain-English explanation for the resident. "
            f"Explain clearly what physical or appliance factors caused this (e.g. high sunlight, air conditioning due to heat, etc.)."
        )

        llm_reply = self._invoke_llm(prompt, max_tokens=180)
        if llm_reply:
            return llm_reply

        # Deterministic offline rule-based explanation
        reasons = []
        if solar_drivers:
            top_s = solar_drivers[0]
            s_name = FEATURE_LABEL_MAP.get(top_s["feature"], top_s["feature"])
            s_val = top_s.get("shap_impact", 0.0)
            if s_val > 0.1:
                reasons.append(f"generation is boosted primarily by strong {s_name} (+{s_val:.2f} kWh)")
            elif s_val < -0.1:
                reasons.append(f"generation is held back by low {s_name} ({s_val:.2f} kWh)")

        if load_drivers:
            top_l = load_drivers[0]
            l_name = FEATURE_LABEL_MAP.get(top_l["feature"], top_l["feature"])
            l_val = top_l.get("shap_impact", 0.0)
            if l_val > 0.1:
                reasons.append(f"consumption is driven up mainly by {l_name} (+{l_val:.2f} kWh)")
            elif l_val < -0.1:
                reasons.append(f"consumption is softened by reduced {l_name} ({l_val:.2f} kWh)")

        if reasons:
            joined = " and ".join(reasons)
            return f"🔍 AI Attribution ({node_name}): Your balance is shaped because {joined}."
        else:
            return f"🔍 AI Attribution ({node_name}): Normal baseline conditions with balanced appliance and solar patterns."

    def generate_weather_shock_alert(
        self,
        cloud_surge_pct: float,
        drop_in_solar_kwh: float,
        affected_hours: str = "13:00–16:00",
    ) -> str:
        return (
            f"⚠️ Microgrid Cloudburst Advisory ({affected_hours}): "
            f"A sudden cloud surge (+{cloud_surge_pct:.0f}%) is slashing local solar generation by ~{drop_in_solar_kwh:.1f} kWh! "
            f"The P2P trading engine has activated dynamic buffer dispatch: EV charging deferred until 17:00, "
            f"and battery storage nodes switched to discharge support to avoid expensive DISCOM peak grid imports."
        )


if __name__ == "__main__":
    agent = BedrockEnergyAgent()
    print("Testing Bedrock Advisory Agent...")
    msg = agent.generate_advisory(
        node_name="Aarav Sharma",
        node_type="Solar Champion Prosumer",
        peak_surplus_slot="13:00–15:00",
        peak_surplus_kwh=3.8,
        p10_surplus=2.9,
        p90_surplus=4.4,
        matched_peer="Iyengar Bakery & Vikram Mehta",
        estimated_earnings_inr=19.95,
        grid_comparison_inr=9.31,
    )
    print("\nGenerated Prosumer Advisory:")
    print(msg)

    print("\nGenerated Weather Shock Advisory:")
    print(agent.generate_weather_shock_alert(cloud_surge_pct=65.0, drop_in_solar_kwh=4.2))
