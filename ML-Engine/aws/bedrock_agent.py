from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional
import boto3
from botocore.exceptions import BotoCoreError, ClientError

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import aws.env_loader

FEATURE_LABEL_MAP: Dict[str, str] = {
    "temperature_c": "ambient temperature",
    "temp_over_30": "extreme heat above 30C",
    "cooling_degree_hour": "cooling heat index",
    "ghi_w_m2": "global solar irradiance",
    "dni_w_m2": "direct sunlight",
    "dhi_w_m2": "diffuse solar radiation",
    "cloud_cover_pct": "cloud cover",
    "humidity_pct": "relative humidity",
    "solar_capacity_kw": "installed solar capacity",
    "household_size": "household occupancy",
    "ac_units": "air conditioning load",
    "has_ev": "EV charger presence",
    "load_lag_24h": "yesterdays consumption at this hour",
    "load_lag_168h": "last weeks consumption at this hour",
    "load_rolling_mean_3h": "recent 3-hour load trend",
    "solar_lag_24h": "yesterdays solar output at this hour",
    "solar_potential_theoretical": "clear-sky theoretical solar potential",
}

ACTIVE_CANDIDATE_MODELS = [
    "amazon.titan-text-express-v1",
    "us.amazon.nova-lite-v1:0",
    "amazon.nova-lite-v1:0",
    "us.anthropic.claude-3-haiku-20240307-v1:0",
    "anthropic.claude-3-haiku-20240307-v1:0",
    "amazon.titan-text-premier-v1:0",
    "us.meta.llama3-8b-instruct-v1:0",
    "meta.llama3-8b-instruct-v1:0",
]


class BedrockEnergyAgent:

    def __init__(
        self,
        model_id: Optional[str] = None,
        region_name: Optional[str] = None,
    ):
        self.model_id = model_id or os.environ.get("BEDROCK_MODEL_ID")
        self.active_model_id: str = self.model_id or ACTIVE_CANDIDATE_MODELS[0]
        self.region_name = (
            region_name
            or os.environ.get("AWS_DEFAULT_REGION")
            or os.environ.get("AWS_REGION")
            or "us-east-1"
        )
        self.bedrock_client = None
        self.last_invocation_source: str = "offline_fallback"
        self.last_error: Optional[str] = None

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
        except Exception as e:
            self.bedrock_client = None
            self.last_error = f"ClientInitError: {e}"

    def _invoke_via_converse(self, model_id: str, prompt: str, max_tokens: int) -> Optional[str]:
        messages = [{"role": "user", "content": [{"text": prompt}]}]
        inference_config = {"maxTokens": max_tokens, "temperature": 0.3}
        response = self.bedrock_client.converse(
            modelId=model_id,
            messages=messages,
            inferenceConfig=inference_config,
        )
        output_content = response.get("output", {}).get("message", {}).get("content", [])
        if output_content and "text" in output_content[0]:
            return output_content[0]["text"].strip()
        return None

    def _invoke_via_invoke_model(self, model_id: str, prompt: str, max_tokens: int) -> Optional[str]:
        if "claude" in model_id:
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "temperature": 0.3,
                "messages": [{"role": "user", "content": prompt}],
            })
            resp = self.bedrock_client.invoke_model(modelId=model_id, body=body)
            res_json = json.loads(resp["body"].read())
            return res_json["content"][0]["text"].strip()
        elif "titan" in model_id:
            body = json.dumps({
                "inputText": prompt,
                "textGenerationConfig": {"maxTokenCount": max_tokens, "temperature": 0.3},
            })
            resp = self.bedrock_client.invoke_model(modelId=model_id, body=body)
            res_json = json.loads(resp["body"].read())
            return res_json.get("results", [{}])[0].get("outputText", "").strip()
        elif "nova" in model_id:
            body = json.dumps({
                "messages": [{"role": "user", "content": [{"text": prompt}]}],
                "inferenceConfig": {"max_new_tokens": max_tokens, "temperature": 0.3},
            })
            resp = self.bedrock_client.invoke_model(modelId=model_id, body=body)
            res_json = json.loads(resp["body"].read())
            output = res_json.get("output", {}).get("message", {}).get("content", [])
            if output and "text" in output[0]:
                return output[0]["text"].strip()
        elif "llama" in model_id:
            body = json.dumps({
                "prompt": prompt,
                "max_gen_len": max_tokens,
                "temperature": 0.3,
            })
            resp = self.bedrock_client.invoke_model(modelId=model_id, body=body)
            res_json = json.loads(resp["body"].read())
            return res_json.get("generation", "").strip()
        return None

    def _invoke_llm(self, prompt: str, max_tokens: int = 220) -> Optional[str]:
        if self.bedrock_client is None:
            self.last_invocation_source = "offline_fallback"
            if not self.last_error:
                self.last_error = "AWS Bedrock client not initialized (verify credentials in .env)"
            return None

        models_to_try = []
        if self.model_id:
            models_to_try.append(self.model_id)
        for m in ACTIVE_CANDIDATE_MODELS:
            if m not in models_to_try:
                models_to_try.append(m)

        last_error_msg = None
        for candidate in models_to_try:
            try:
                res = self._invoke_via_converse(candidate, prompt, max_tokens)
                if res:
                    self.active_model_id = candidate
                    self.last_invocation_source = "aws_bedrock"
                    self.last_error = None
                    return res
            except Exception as e1:
                last_error_msg = f"{type(e1).__name__}: {str(e1)}"

            try:
                res_alt = self._invoke_via_invoke_model(candidate, prompt, max_tokens)
                if res_alt:
                    self.active_model_id = candidate
                    self.last_invocation_source = "aws_bedrock"
                    self.last_error = None
                    return res_alt
            except Exception as e2:
                last_error_msg = f"{type(e2).__name__}: {str(e2)}"
                continue

        if last_error_msg and "Operation not allowed" in last_error_msg:
            self.last_error = f"{last_error_msg} -> First-time serverless model invocation pending or AWS account verification hold active"
        else:
            self.last_error = last_error_msg or "All candidate models failed or un-granted"
        self.last_invocation_source = "offline_fallback"
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
            f"- Economics: Earning/saving INR {estimated_earnings_inr:.2f} locally vs INR {grid_comparison_inr:.2f} via standard DISCOM grid.{shap_context}\n"
            f"Keep it punchy, professional, and actionable. Do not use any emojis."
        )

        llm_reply = self._invoke_llm(prompt, max_tokens=220)
        if llm_reply:
            return llm_reply

        if peak_surplus_kwh > 0.5:
            base = (
                f"[Solar Surplus Notice] {node_name}: "
                f"You will likely have a {peak_surplus_kwh:.1f} kWh surplus around {peak_surplus_slot} "
                f"(confidence: {p10_surplus:.1f}-{p90_surplus:.1f} kWh). "
                f"We have pre-matched your excess with {matched_peer} at INR 5.30/kWh, "
                f"earning you INR {estimated_earnings_inr:.2f} (vs only INR {grid_comparison_inr:.2f} from DISCOM net-metering)."
            )
        elif peak_surplus_kwh < -0.5:
            need = abs(peak_surplus_kwh)
            base = (
                f"[Demand Peak Notice] {node_name}: "
                f"Your high AC / appliance load requires {need:.1f} kWh around {peak_surplus_slot}. "
                f"We have scheduled peer power delivery from {matched_peer} at INR 5.30/kWh, "
                f"saving you INR {estimated_earnings_inr:.2f} compared to peak DISCOM grid rates (INR 8.20/kWh)."
            )
        else:
            base = (
                f"[Balanced Status] {node_name}: "
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
            f"Provide a friendly, 2-sentence plain-English explanation for the resident without using any emojis. "
            f"Explain clearly what physical or appliance factors caused this."
        )

        llm_reply = self._invoke_llm(prompt, max_tokens=180)
        if llm_reply:
            return llm_reply

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
            return f"[AI Attribution] ({node_name}): Your balance is shaped because {joined}."
        else:
            return f"[AI Attribution] ({node_name}): Normal baseline conditions with balanced appliance and solar patterns."

    def generate_weather_shock_alert(
        self,
        cloud_surge_pct: float,
        drop_in_solar_kwh: float,
        affected_hours: str = "13:00–16:00",
    ) -> str:
        return (
            f"[Microgrid Cloudburst Advisory] ({affected_hours}): "
            f"A sudden cloud surge (+{cloud_surge_pct:.0f}%) is slashing local solar generation by ~{drop_in_solar_kwh:.1f} kWh. "
            f"The P2P trading engine has activated dynamic buffer dispatch: EV charging deferred until 17:00, "
            f"and battery storage nodes switched to discharge support to avoid expensive DISCOM peak grid imports."
        )


if __name__ == "__main__":
    agent = BedrockEnergyAgent()
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
    print("Advisory:", msg)
    print("Engine:", agent.last_invocation_source)
    print("Model:", agent.active_model_id)
    if agent.last_error:
        print("Error:", agent.last_error)
