"use client";

import { useState } from "react";
import useSWR from "swr";
import SiteNav from "../components/SiteNav";
import { engine, kwh, type EngineState } from "@/lib/engine";

const modes = ["static", "dynamic", "hybrid"] as const;

export default function LivePage() {
  const { data, error, mutate } = useSWR("state", engine.state, { refreshInterval: 1000 });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setMessage("");
    try {
      await action();
      await mutate();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-full flex-1 flex-col text-forest">
      <SiteNav active="/live" />
      <main className="mx-auto w-full max-w-6xl flex-1 px-6 pt-28 pb-16">
        <h1 className="font-display text-3xl text-forest sm:text-4xl">Live community</h1>
        <p className="mt-2 text-sage-text">One shared clock. Start, pause, or step a single hour.</p>
        {error && (
          <p className="mt-6 rounded-2xl bg-butter px-4 py-3 text-sm text-dark-teal">
            Cannot reach the simulation engine on port 8000.
          </p>
        )}
        {message && <p className="mt-4 text-sm text-dark-teal">{message}</p>}

        <section className="mt-8 flex flex-wrap gap-2">
          <button type="button" disabled={busy} className="btn-teal rounded-full px-5 py-2 text-sm" onClick={() => run(engine.start)}>Start</button>
          <button type="button" disabled={busy} className="btn-outline-teal rounded-full px-5 py-2 text-sm" onClick={() => run(engine.pause)}>Pause</button>
          <button type="button" disabled={busy} className="btn-outline-teal rounded-full px-5 py-2 text-sm" onClick={() => run(engine.step)}>Step</button>
          {modes.map((mode) => (
            <button
              key={mode}
              type="button"
              disabled={busy}
              className={`rounded-full px-4 py-2 text-sm capitalize ${data?.mode === mode ? "bg-teal text-white" : "btn-outline-teal"}`}
              onClick={() => run(() => engine.mode(mode))}
            >
              {mode}
            </button>
          ))}
          <button type="button" disabled={busy} className="btn-outline-teal rounded-full px-4 py-2 text-sm" onClick={() => run(() => engine.speed(1))}>1×</button>
          <button type="button" disabled={busy} className="btn-outline-teal rounded-full px-4 py-2 text-sm" onClick={() => run(() => engine.speed(5))}>5×</button>
          <button type="button" disabled={busy} className="btn-teal rounded-full px-4 py-2 text-sm" onClick={() => run(() => engine.inject("B", 3))}>Inject +3 kWh at B</button>
          <button type="button" disabled={busy} className="rounded-full border border-light-sage px-4 py-2 text-sm text-sage-text" onClick={() => run(() => engine.reset("hybrid"))}>Reset</button>
        </section>

        {data && <LiveBody data={data} />}
      </main>
    </div>
  );
}

function LiveBody({ data }: { data: EngineState }) {
  const history = data.history.slice(-18);
  const max = Math.max(0.01, ...history.map((s) => Math.max(s.supply, s.demand, s.matched)));
  const matches = data.last?.matches ?? [];

  return (
    <>
      <p className="mt-6 text-sm text-sage-text">
        Next slot day {data.day} hour {data.hour} · {data.running ? "running" : "paused"} · {data.speed}× · {data.mode}
        {data.last ? ` · forecast ${data.last.forecast_source}` : ""}
      </p>

      <section className="mt-6 grid gap-6 lg:grid-cols-2">
        <article className="rounded-3xl border border-light-sage bg-warm-white p-6">
          <h2 className="font-display text-xl text-dark-teal">Supply and demand</h2>
          {history.length === 0 ? (
            <p className="mt-6 text-sm text-sage-muted">No activity yet.</p>
          ) : (
            <div className="mt-6 flex h-40 items-end gap-1">
              {history.map((slot) => (
                <div key={`${slot.day}-${slot.hour}`} className="flex flex-1 items-end gap-px" title={`${slot.hour}:00`}>
                  <div className="w-1/3 rounded-t bg-gold/80" style={{ height: `${(slot.supply / max) * 100}%` }} />
                  <div className="w-1/3 rounded-t bg-teal/70" style={{ height: `${(slot.demand / max) * 100}%` }} />
                  <div className="w-1/3 rounded-t bg-dark-teal/80" style={{ height: `${(slot.matched / max) * 100}%` }} />
                </div>
              ))}
            </div>
          )}
          <p className="mt-3 text-xs text-sage-muted">Gold supply · teal demand · dark matched</p>
        </article>

        <article className="rounded-3xl border border-light-sage bg-warm-white p-6">
          <h2 className="font-display text-xl text-dark-teal">Who feeds whom</h2>
          {matches.length === 0 ? (
            <p className="mt-6 text-sm text-sage-muted">No matches in the latest slot.</p>
          ) : (
            <ul className="mt-4 space-y-2 text-sm text-sage-text">
              {matches.map((m, i) => (
                <li key={`${m.seller}-${m.buyer}-${i}`} className="flex justify-between rounded-full bg-pale-mint px-4 py-2">
                  <span>{m.seller} → {m.buyer}</span>
                  <span>{kwh(m.kwh)}</span>
                </li>
              ))}
            </ul>
          )}
        </article>
      </section>

      <section className="mt-6 rounded-3xl border border-light-sage bg-warm-white p-6">
        <h2 className="font-display text-xl text-dark-teal">Activity</h2>
        {data.events.length === 0 ? (
          <p className="mt-4 text-sm text-sage-muted">No events yet.</p>
        ) : (
          <ul className="mt-4 space-y-2 text-sm text-sage-text">
            {data.events.slice(0, 8).map((event, i) => (
              <li key={i}>{event.text}</li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
