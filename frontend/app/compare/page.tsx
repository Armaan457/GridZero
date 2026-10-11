"use client";

import { useState } from "react";
import SiteNav from "../components/SiteNav";
import { engine, type CompareRow } from "@/lib/engine";

const metrics: { key: string; label: string }[] = [
  { key: "supply_used_pct", label: "Supply used %" },
  { key: "demand_met_by_p2p_pct", label: "Demand met by P2P %" },
  { key: "homes_fully_served_pct", label: "Homes fully served %" },
  { key: "fairness_jain", label: "Jain fairness" },
  { key: "p2p_kwh", label: "P2P kWh" },
  { key: "grid_import_kwh", label: "Grid import kWh" },
  { key: "user_gain_rs", label: "User gain Rs" },
];

export default function ComparePage() {
  const [rows, setRows] = useState<CompareRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function run() {
    setBusy(true);
    setError("");
    try {
      setRows(await engine.compare(3));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Compare failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-full flex-1 flex-col text-forest">
      <SiteNav active="/compare" />
      <main className="mx-auto w-full max-w-6xl flex-1 px-6 pt-28 pb-16">
        <h1 className="font-display text-3xl text-forest sm:text-4xl">Compare sharing modes</h1>
        <p className="mt-2 max-w-2xl text-sage-text">
          Runs static, dynamic, and hybrid on the same three days. This does not change the live clock.
        </p>
        <button type="button" disabled={busy} className="btn-teal mt-6 rounded-full px-6 py-2 text-sm" onClick={run}>
          {busy ? "Running…" : "Compare 3 days"}
        </button>
        {error && <p className="mt-4 text-sm text-dark-teal">{error}</p>}
        {rows && (
          <div className="mt-8 overflow-x-auto rounded-3xl border border-light-sage bg-warm-white p-6">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="text-sage-muted">
                <tr>
                  <th className="py-2 font-medium">Metric</th>
                  {rows.map((row) => (
                    <th key={String(row.mode)} className="py-2 font-medium capitalize">{String(row.mode)}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="text-sage-text">
                {metrics.map((metric) => (
                  <tr key={metric.key} className="border-t border-misty-sage">
                    <td className="py-2">{metric.label}</td>
                    {rows.map((row) => (
                      <td key={String(row.mode)} className="py-2">
                        {typeof row[metric.key] === "number" ? Number(row[metric.key]).toFixed(2) : String(row[metric.key] ?? "—")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}
