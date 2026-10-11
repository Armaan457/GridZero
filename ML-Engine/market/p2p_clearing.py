from __future__ import annotations
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


@dataclass
class P2PTrade:
    slot: str
    seller_id: str
    seller_name: str
    buyer_id: str
    buyer_name: str
    energy_kwh: float
    clearing_price_inr: float
    seller_earnings_inr: float
    buyer_savings_inr: float


@dataclass
class SlotClearingResult:
    slot: str
    total_solar_gen_kwh: float
    total_load_kwh: float
    total_surplus_kwh: float
    total_deficit_kwh: float
    total_p2p_traded_kwh: float
    grid_import_kwh: float
    grid_export_kwh: float
    community_savings_inr: float
    trades: List[P2PTrade] = field(default_factory=list)


class MicrogridP2PClearingEngine:

    def __init__(
        self,
        grid_import_rate: float = 8.20,
        grid_export_rate: float = 2.45,
        p2p_clearing_rate: float = 5.30,
    ):
        self.grid_import_rate = grid_import_rate
        self.grid_export_rate = grid_export_rate
        self.p2p_clearing_rate = p2p_clearing_rate

    def clear_horizon(
        self,
        forecast_df: pd.DataFrame,
        risk_mode: str = "p50",
    ) -> List[SlotClearingResult]:
        results: List[SlotClearingResult] = []

        surplus_col = "pred_surplus_p10" if risk_mode == "p10" else "pred_surplus_or_need"
        load_col = "pred_load"
        solar_col = "pred_solar"

        grouped = forecast_df.groupby("datetime", sort=True)

        for dt, group in grouped:
            slot_str = str(dt)
            sellers: List[Dict[str, Any]] = []
            buyers: List[Dict[str, Any]] = []

            total_solar = float(group[solar_col].sum())
            total_load = float(group[load_col].sum())

            for _, row in group.iterrows():
                net = float(row[surplus_col])
                node_id = str(row["node_id"])
                node_name = str(row.get("node_name", node_id))

                if net > 0.01:
                    sellers.append({"id": node_id, "name": node_name, "available_kwh": net})
                elif net < -0.01:
                    buyers.append({"id": node_id, "name": node_name, "needed_kwh": abs(net)})

            total_surplus = sum(s["available_kwh"] for s in sellers)
            total_deficit = sum(b["needed_kwh"] for b in buyers)

            trades: List[P2PTrade] = []
            s_idx = 0
            b_idx = 0

            while s_idx < len(sellers) and b_idx < len(buyers):
                seller = sellers[s_idx]
                buyer = buyers[b_idx]

                trade_kwh = min(seller["available_kwh"], buyer["needed_kwh"])

                if trade_kwh > 0.001:
                    seller_earnings = trade_kwh * (self.p2p_clearing_rate - self.grid_export_rate)
                    buyer_savings = trade_kwh * (self.grid_import_rate - self.p2p_clearing_rate)

                    trade = P2PTrade(
                        slot=slot_str,
                        seller_id=seller["id"],
                        seller_name=seller["name"],
                        buyer_id=buyer["id"],
                        buyer_name=buyer["name"],
                        energy_kwh=round(trade_kwh, 3),
                        clearing_price_inr=self.p2p_clearing_rate,
                        seller_earnings_inr=round(seller_earnings, 2),
                        buyer_savings_inr=round(buyer_savings, 2),
                    )
                    trades.append(trade)

                    seller["available_kwh"] -= trade_kwh
                    buyer["needed_kwh"] -= trade_kwh

                if seller["available_kwh"] <= 0.001:
                    s_idx += 1
                if buyer["needed_kwh"] <= 0.001:
                    b_idx += 1

            total_p2p_traded = sum(t.energy_kwh for t in trades)
            unmatched_surplus = sum(s["available_kwh"] for s in sellers[s_idx:])
            unmatched_deficit = sum(b["needed_kwh"] for b in buyers[b_idx:])

            community_savings = sum(t.seller_earnings_inr + t.buyer_savings_inr for t in trades)

            res = SlotClearingResult(
                slot=slot_str,
                total_solar_gen_kwh=round(total_solar, 2),
                total_load_kwh=round(total_load, 2),
                total_surplus_kwh=round(total_surplus, 2),
                total_deficit_kwh=round(total_deficit, 2),
                total_p2p_traded_kwh=round(total_p2p_traded, 2),
                grid_import_kwh=round(unmatched_deficit, 2),
                grid_export_kwh=round(unmatched_surplus, 2),
                community_savings_inr=round(community_savings, 2),
                trades=trades,
            )
            results.append(res)

        return results

    def summarize_to_dataframe(self, results: List[SlotClearingResult]) -> pd.DataFrame:
        rows = []
        for r in results:
            rows.append({
                "slot": r.slot,
                "solar_kwh": r.total_solar_gen_kwh,
                "load_kwh": r.total_load_kwh,
                "surplus_kwh": r.total_surplus_kwh,
                "deficit_kwh": r.total_deficit_kwh,
                "p2p_traded_kwh": r.total_p2p_traded_kwh,
                "grid_import_kwh": r.grid_import_kwh,
                "grid_export_kwh": r.grid_export_kwh,
                "community_savings_inr": r.community_savings_inr,
                "num_trades": len(r.trades),
            })
        return pd.DataFrame(rows)
