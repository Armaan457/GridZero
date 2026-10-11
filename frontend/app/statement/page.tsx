"use client";

import useSWR from "swr";
import SiteNav from "../components/SiteNav";
import { engine, kwh, rs } from "@/lib/engine";
import { useNode } from "@/lib/useNode";

export default function StatementPage() {
  const { node } = useNode();
  const { data, error } = useSWR(["statement", node], () => engine.statement(node));

  const lines = data
    ? [
        { label: "Discom import", value: kwh(data.discom_import_kwh) },
        { label: "Discom export", value: kwh(data.discom_export_kwh) },
        { label: "P2P bought", value: `${kwh(data.p2p_bought_kwh)} · owe ${rs(-data.p2p_owed_rs)}` },
        { label: "P2P sold", value: `${kwh(data.p2p_sold_kwh)} · earned ${rs(data.p2p_earned_rs)}` },
        { label: "Grid fee on P2P", value: rs(data.grid_fee_on_discom_bill_rs) },
        { label: "Net wallet", value: rs(data.net_wallet_rs) },
      ]
    : [];

  return (
    <div className="flex min-h-full flex-1 flex-col text-forest">
      <SiteNav active="/statement" />
      <main className="mx-auto w-full max-w-3xl flex-1 px-6 pt-28 pb-16">
        <p className="text-sm font-medium text-teal">Home {node}</p>
        <h1 className="font-display text-3xl text-forest sm:text-4xl">Statement since reset</h1>
        {error && (
          <p className="mt-6 rounded-2xl bg-butter px-4 py-3 text-sm text-dark-teal">
            Cannot reach the simulation engine.
          </p>
        )}
        {!data && !error && <p className="mt-8 text-sm text-sage-muted">Loading…</p>}
        {data && (
          <>
            <div className="mt-8 space-y-3">
              {lines.map((line) => (
                <div key={line.label} className="flex items-center justify-between rounded-2xl border border-light-sage bg-warm-white px-5 py-4">
                  <span className="text-sage-text">{line.label}</span>
                  <span className="font-display text-lg text-dark-teal">{line.value}</span>
                </div>
              ))}
            </div>
            <p className="mt-6 text-sm leading-6 text-sage-muted">{data.note}</p>
          </>
        )}
      </main>
    </div>
  );
}
