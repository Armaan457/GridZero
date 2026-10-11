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


class BedrockEnergyAgent:

    def __init__(
        self,
        model_id: str = "anthropic.claude-3-haiku-20240307-v1:0",
        region_name: str = "us-east-1",
    ):
        self.model_id = model_id
        self.region_name = region_name
        self.bedrock_client = None

        try:
            self.bedrock_client = boto3.client(
                "bedrock-runtime",
                region_name=self.region_name,
            )
        except Exception:
            self.bedrock_client = None

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
    ) -> str:
        prompt = (
            f"You are the autonomous AI Dispatcher for an Indian Smart Microgrid.\n"
            f"Generate a friendly, concise, 2-3 sentence notification for {node_name} ({node_type}):\n"
            f"- Forecasted Net Peak: {peak_surplus_kwh:.1f} kWh at {peak_surplus_slot} "
            f"(Confidence Band: {p10_surplus:.1f} to {p90_surplus:.1f} kWh).\n"
            f"- Weather: {weather_summary}.\n"
            f"- P2P Matching: Matched with {matched_peer}.\n"
            f"- Economics: Earning/saving ₹{estimated_earnings_inr:.2f} locally vs ₹{grid_comparison_inr:.2f} via standard DISCOM grid.\n"
            f"Keep it punchy, motivating, and actionable. Include relevant emojis."
        )

        if self.bedrock_client is not None:
            try:
                body = json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 200,
                    "temperature": 0.3,
                    "messages": [{"role": "user", "content": prompt}],
                })
                response = self.bedrock_client.invoke_model(
                    modelId=self.model_id,
                    body=body,
                )
                response_json = json.loads(response["body"].read())
                return response_json["content"][0]["text"].strip()
            except (BotoCoreError, ClientError, Exception):
                pass

        if peak_surplus_kwh > 0.5:
            return (
                f"☀️ Solar Surplus Alert for {node_name}: "
                f"You will likely have a {peak_surplus_kwh:.1f} kWh surplus around {peak_surplus_slot} "
                f"(confidence: {p10_surplus:.1f}–{p90_surplus:.1f} kWh). "
                f"We have pre-matched your excess with {matched_peer} at ₹5.30/kWh, "
                f"earning you ₹{estimated_earnings_inr:.2f} (vs only ₹{grid_comparison_inr:.2f} from DISCOM net-metering)."
            )
        elif peak_surplus_kwh < -0.5:
            need = abs(peak_surplus_kwh)
            return (
                f"⚡ Demand Peak Notice for {node_name}: "
                f"Your high AC / appliance load requires {need:.1f} kWh around {peak_surplus_slot}. "
                f"We have scheduled peer power delivery from {matched_peer} at ₹5.30/kWh, "
                f"saving you ₹{estimated_earnings_inr:.2f} compared to peak DISCOM grid rates (₹8.20/kWh)."
            )
        else:
            return (
                f"⚖️ Balanced Microgrid Status for {node_name}: "
                f"Your production and consumption are nearly in equilibrium around {peak_surplus_slot}. "
                f"Minimal grid dependency anticipated."
            )

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
