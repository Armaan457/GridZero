"use client";

import useSWR from "swr";
import SiteNav from "../components/SiteNav";
import { engine, kwh, rs, slotLabel, type LedgerRow } from "@/lib/engine";
import { useNode } from "@/lib/useNode";

export default function DashboardPage() {
  const { node } = useNode();
  const state = useSWR("state", engine.state, { refreshInterval: 1000 });
  const ledger = useSWR(["ledger", node], () => engine.ledger(node, 24), { refreshInterval: 2500 });
  const statement = useSWR(["statement", node], () => engine.statement(node), { refreshInterval: 3000 });

  const rows = ledger.data ?? [];
  const me = state.data?.last?.nodes.find((n) => n.node === node);
  const stmt = statement.data;
  const chart = rows.slice(-12);
  const maxBar = Math.max(0.01, ...chart.map((r) => Math.max(r.load, r.solar)));

  const predSurplus = me ? me.pred_solar - me.pred_load : null;
  const actualSurplus = me ? me.solar - me.load : null;

  const stats = [
    {
      label: "Predicted surplus",
      value: predSurplus == null ? "—" : kwh(predSurplus),
      hint: me ? `Slot ${slotLabel(me.day, me.hour)}` : "Waiting for the first slot",
    },
    {
      label: "Actual surplus",
      value: actualSurplus == null ? "—" : kwh(actualSurplus),
      hint: me ? `Load ${me.load.toFixed(2)} · solar ${me.solar.toFixed(2)}` : "No meter reading yet",
    },
    {
      label: "Grid import",
      value: stmt ? kwh(stmt.discom_import_kwh) : "—",
      hint: "Units only · discom bills this itself",
    },
    {
      label: "P2P sold",
      value: stmt ? kwh(stmt.p2p_sold_kwh) : "—",
      hint: stmt ? `${rs(stmt.p2p_earned_rs)} earned` : "Since reset",
    },
  ];

  return (
    <div className="flex min-h-full flex-1 flex-col text-forest">
      <SiteNav active="/dashboard" />
      <main className="mx-auto w-full max-w-6xl flex-1 px-6 pt-28 pb-16">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-sm font-medium text-teal">Home {node} · same feeder</p>
            <h1 className="font-display text-3xl text-forest sm:text-4xl">Today&apos;s energy</h1>
          </div>
          <div className="inline-flex items-center gap-2 rounded-full border border-light-sage bg-warm-white px-4 py-2 text-sm text-sage-text">
            <span className={`h-2 w-2 rounded-full ${state.data?.running ? "bg-teal" : "bg-sage-muted"}`} />
            {state.data?.running ? "Simulation running" : "Simulation paused"}
            {state.data?.last ? ` · ${state.data.last.forecast_source}` : ""}
          </div>
        </div>

        {(state.error || ledger.error) && (
          <p className="mt-6 rounded-2xl bg-butter px-4 py-3 text-sm text-dark-teal">
            Cannot reach the simulation engine. Start it on port 8000, then refresh.
          </p>
        )}

        <section className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {stats.map((stat) => (
            <article key={stat.label} className="rounded-3xl border border-light-sage bg-warm-white/90 px-5 py-5">
              <p className="text-sm text-sage-muted">{stat.label}</p>
              <p className="mt-2 font-display text-2xl text-dark-teal">{stat.value}</p>
              <p className="mt-1 text-xs text-sage-text">{stat.hint}</p>
            </article>
          ))}
        </section>

        <section className="mt-6 grid gap-6 lg:grid-cols-[1.4fr_0.8fr]">
          <article className="rounded-3xl border border-light-sage bg-warm-white/90 p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="font-display text-xl text-dark-teal">Hourly load and solar</h2>
                <p className="text-sm text-sage-muted">Last slots from the ledger</p>
              </div>
              <div className="flex gap-2 text-xs">
                <span className="rounded-full bg-pale-mint px-3 py-1 text-deep-teal">Load</span>
                <span className="rounded-full bg-butter px-3 py-1 text-dark-teal">Solar</span>
              </div>
            </div>
            {chart.length === 0 ? (
              <p className="mt-10 text-sm text-sage-muted">No activity yet. Start or step the simulation on the live page.</p>
            ) : (
              <div className="mt-8 flex h-48 items-end gap-2">
                {chart.map((row) => (
                  <div key={`${row.day}-${row.hour}`} className="flex flex-1 flex-col items-center gap-2">
                    <div className="flex h-36 w-full items-end justify-center gap-0.5">
                      <div className="w-1/2 rounded-t-md bg-teal/80" style={{ height: `${(row.load / maxBar) * 100}%` }} />
                      <div className="w-1/2 rounded-t-md bg-gold/80" style={{ height: `${(row.solar / maxBar) * 100}%` }} />
                    </div>
                    <span className="text-[11px] text-sage-muted">{String(row.hour).padStart(2, "0")}</span>
                  </div>
                ))}
              </div>
            )}
          </article>

          <article className="rounded-3xl border border-light-sage bg-gradient-to-b from-warm-white to-misty-sage/70 p-6">
            <h2 className="font-display text-xl text-dark-teal">This slot</h2>
            <p className="mt-2 text-sm leading-6 text-sage-text">
              Net = solar − load. Positive means you can sell on the feeder.
            </p>
            {!me ? (
              <p className="mt-6 text-sm text-sage-muted">No activity yet.</p>
            ) : (
              <>
                <div className="mt-6 rounded-2xl bg-warm-white px-4 py-4">
                  <p className="text-xs uppercase tracking-wide text-sage-muted">{slotLabel(me.day, me.hour)} · {me.role}</p>
                  <p className="mt-1 font-display text-3xl text-teal">{kwh(me.solar - me.load)}</p>
                  <p className="mt-1 text-sm text-sage-text">
                    Predicted load {me.pred_load.toFixed(2)} · actual {me.load.toFixed(2)}
                  </p>
                </div>
                <div className="mt-4 space-y-2 text-sm text-sage-text">
                  <div className="flex justify-between rounded-full bg-pale-mint px-4 py-2">
                    <span>P2P bought</span>
                    <span>{kwh(me.p2p_bought)}</span>
                  </div>
                  <div className="flex justify-between rounded-full bg-butter/80 px-4 py-2">
                    <span>P2P sold</span>
                    <span>{kwh(me.p2p_sold)}</span>
                  </div>
                  <div className="flex justify-between rounded-full bg-warm-white px-4 py-2">
                    <span>Grid import</span>
                    <span>{kwh(me.grid_import)}</span>
                  </div>
                </div>
              </>
            )}
          </article>
        </section>

        <LedgerTable rows={rows} />
      </main>
    </div>
  );
}

function LedgerTable({ rows }: { rows: LedgerRow[] }) {
  return (
    <section id="ledger" className="mt-6 rounded-3xl border border-light-sage bg-warm-white/90 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-xl text-dark-teal">Ledger</h2>
          <p className="text-sm text-sage-muted">Grid import and export in units. Money is P2P only.</p>
        </div>
        <a href="/statement" className="btn-outline-teal rounded-full px-4 py-2 text-sm font-medium">
          Monthly statement
        </a>
      </div>
      {rows.length === 0 ? (
        <p className="mt-6 text-sm text-sage-muted">No activity yet.</p>
      ) : (
        <div className="mt-5 overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="text-sage-muted">
              <tr className="border-b border-light-sage">
                <th className="py-3 font-medium">Slot</th>
                <th className="py-3 font-medium">Grid import</th>
                <th className="py-3 font-medium">Grid export</th>
                <th className="py-3 font-medium">P2P sold</th>
                <th className="py-3 font-medium">P2P bought</th>
                <th className="py-3 font-medium">Money</th>
              </tr>
            </thead>
            <tbody className="text-sage-text">
              {[...rows].reverse().slice(0, 12).map((row) => {
                const money = row.p2p_earned_rs - row.p2p_owed_rs;
                return (
                  <tr key={`${row.day}-${row.hour}`} className="border-b border-misty-sage">
                    <td className="py-3">{slotLabel(row.day, row.hour)}</td>
                    <td className="py-3">{row.grid_import.toFixed(2)}</td>
                    <td className="py-3">{row.grid_export.toFixed(2)}</td>
                    <td className="py-3">{row.p2p_sold.toFixed(2)}</td>
                    <td className="py-3">{row.p2p_bought.toFixed(2)}</td>
                    <td className="py-3 text-dark-teal">{rs(money)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
