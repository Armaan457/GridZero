const hours = ["6a", "8a", "10a", "12p", "2p", "4p", "6p", "8p"];

const ledgerRows = [
  { slot: "12:00–12:15", import: "—", export: "1.2", sold: "0.9", bought: "—", money: "+ ₹6.30" },
  { slot: "12:15–12:30", import: "—", export: "1.1", sold: "0.8", bought: "—", money: "+ ₹5.60" },
  { slot: "12:30–12:45", import: "0.2", export: "0.4", sold: "0.3", bought: "—", money: "+ ₹2.10" },
  { slot: "12:45–13:00", import: "0.6", export: "—", sold: "—", bought: "0.4", money: "− ₹2.80" },
];

const stats = [
  { label: "Predicted surplus", value: "4.1 kWh", hint: "Today · 12–3pm band" },
  { label: "Actual surplus", value: "3.6 kWh", hint: "Metered so far" },
  { label: "Grid import", value: "0.8 kWh", hint: "Unmet after P2P" },
  { label: "P2P sold", value: "2.0 kWh", hint: "₹14.00 earned" },
];

export default function DashboardPage() {
  return (
    <div className="flex min-h-full flex-1 flex-col text-forest">
      <nav className="pointer-events-none fixed top-5 left-1/2 z-30 w-full max-w-[min(94vw,56rem)] -translate-x-1/2 px-3">
        <div
          className="pointer-events-auto flex items-center justify-between gap-3 rounded-full px-5 py-2 shadow-[0_8px_28px_rgba(40,124,115,0.12)] ring-1 ring-white/50"
          style={{ background: "linear-gradient(135deg, #dcebdd 0%, #c8dec9 55%, #b8d8d0 100%)" }}
        >
          <a
            href="/"
            className="rounded-full px-4 py-2 font-display text-sm text-dark-teal transition duration-300 hover:bg-white/50"
          >
            Grove Grid
          </a>
          <div className="hidden items-center gap-0.5 sm:flex">
            <a
              href="/dashboard"
              className="rounded-full bg-white/70 px-3.5 py-2 text-sm text-dark-teal"
            >
              Dashboard
            </a>
            <a
              href="#ledger"
              className="rounded-full px-3.5 py-2 text-sm text-sage-text transition duration-300 hover:bg-white/55 hover:text-dark-teal"
            >
              Ledger
            </a>
            <a
              href="#live"
              className="rounded-full px-3.5 py-2 text-sm text-sage-text transition duration-300 hover:bg-white/55 hover:text-dark-teal"
            >
              Live
            </a>
          </div>
          <a href="/" className="btn-teal inline-flex h-9 items-center rounded-full px-4 text-sm font-medium">
            Home
          </a>
        </div>
      </nav>

      <main className="mx-auto w-full max-w-6xl flex-1 px-6 pt-28 pb-16">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-sm font-medium text-teal">Home A · same feeder</p>
            <h1 className="font-display text-3xl text-forest sm:text-4xl">Today&apos;s energy</h1>
          </div>
          <div className="inline-flex items-center gap-2 rounded-full border border-light-sage bg-warm-white px-4 py-2 text-sm text-sage-text">
            <span className="h-2 w-2 rounded-full bg-teal" />
            Surplus day · 3.6 kWh left to share
          </div>
        </div>

        <section className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {stats.map((stat) => (
            <article
              key={stat.label}
              className="rounded-3xl border border-light-sage bg-warm-white/90 px-5 py-5"
            >
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
                <p className="text-sm text-sage-muted">Actual vs predicted · skeleton</p>
              </div>
              <div className="flex gap-2 text-xs">
                <span className="rounded-full bg-pale-mint px-3 py-1 text-deep-teal">Actual</span>
                <span className="rounded-full bg-butter px-3 py-1 text-dark-teal">Predicted</span>
              </div>
            </div>
            <div className="mt-8 flex h-48 items-end gap-3">
              {hours.map((hour, i) => {
                const actual = [28, 36, 52, 78, 86, 64, 40, 32][i];
                const pred = [30, 40, 48, 82, 80, 60, 44, 30][i];
                return (
                  <div key={hour} className="flex flex-1 flex-col items-center gap-2">
                    <div className="flex h-36 w-full items-end justify-center gap-1">
                      <div
                        className="w-1/2 rounded-t-md bg-teal/80"
                        style={{ height: `${actual}%` }}
                      />
                      <div
                        className="w-1/2 rounded-t-md bg-gold/80"
                        style={{ height: `${pred}%` }}
                      />
                    </div>
                    <span className="text-[11px] text-sage-muted">{hour}</span>
                  </div>
                );
              })}
            </div>
          </article>

          <article className="rounded-3xl border border-light-sage bg-gradient-to-b from-warm-white to-misty-sage/70 p-6">
            <h2 className="font-display text-xl text-dark-teal">Surplus or need</h2>
            <p className="mt-2 text-sm leading-6 text-sage-text">
              Net = solar − load. Positive means you can sell on the feeder. Negative
              means you buy or import from the discom.
            </p>
            <div className="mt-6 rounded-2xl bg-warm-white px-4 py-4">
              <p className="text-xs uppercase tracking-wide text-sage-muted">This slot</p>
              <p className="mt-1 font-display text-3xl text-teal">+1.1 kWh</p>
              <p className="mt-1 text-sm text-sage-text">Predicted 1.3 · error 0.2</p>
            </div>
            <div className="mt-4 space-y-2 text-sm text-sage-text">
              <div className="flex justify-between rounded-full bg-pale-mint px-4 py-2">
                <span>P2P sold</span>
                <span>0.8 kWh</span>
              </div>
              <div className="flex justify-between rounded-full bg-butter/80 px-4 py-2">
                <span>Solar export leftover</span>
                <span>0.3 kWh</span>
              </div>
            </div>
          </article>
        </section>

        <section id="ledger" className="mt-6 rounded-3xl border border-light-sage bg-warm-white/90 p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-display text-xl text-dark-teal">Ledger</h2>
              <p className="text-sm text-sage-muted">
                Grid import · solar export · P2P sold / bought · money for P2P only
              </p>
            </div>
            <button type="button" className="btn-outline-teal rounded-full px-4 py-2 text-sm font-medium">
              Monthly statement
            </button>
          </div>
          <div className="mt-5 overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="text-sage-muted">
                <tr className="border-b border-light-sage">
                  <th className="py-3 font-medium">Slot</th>
                  <th className="py-3 font-medium">Grid import</th>
                  <th className="py-3 font-medium">Solar export</th>
                  <th className="py-3 font-medium">P2P sold</th>
                  <th className="py-3 font-medium">P2P bought</th>
                  <th className="py-3 font-medium">Money</th>
                </tr>
              </thead>
              <tbody className="text-sage-text">
                {ledgerRows.map((row) => (
                  <tr key={row.slot} className="border-b border-misty-sage">
                    <td className="py-3">{row.slot}</td>
                    <td className="py-3">{row.import}</td>
                    <td className="py-3">{row.export}</td>
                    <td className="py-3">{row.sold}</td>
                    <td className="py-3">{row.bought}</td>
                    <td className="py-3 text-dark-teal">{row.money}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section id="live" className="mt-6 grid gap-4 md:grid-cols-3">
          <article className="rounded-3xl border border-dashed border-eucalyptus bg-misty-sage/50 p-6">
            <h3 className="font-display text-lg text-dark-teal">Live simulation</h3>
            <p className="mt-2 text-sm text-sage-text">Play / pause · speed · Static / Dynamic / Hybrid</p>
            <div className="mt-4 flex gap-2">
              <span className="h-9 w-20 rounded-full bg-light-sage" />
              <span className="h-9 flex-1 rounded-full bg-light-sage" />
            </div>
          </article>
          <article className="rounded-3xl border border-dashed border-eucalyptus bg-misty-sage/50 p-6">
            <h3 className="font-display text-lg text-dark-teal">Node map</h3>
            <p className="mt-2 text-sm text-sage-text">Arrows A → B on the feeder. Placeholder.</p>
            <div className="mt-4 h-16 rounded-2xl bg-light-sage" />
          </article>
          <article className="rounded-3xl border border-dashed border-eucalyptus bg-misty-sage/50 p-6">
            <h3 className="font-display text-lg text-dark-teal">Sudden demand</h3>
            <p className="mt-2 text-sm text-sage-text">Inject extra load at Home B for the live demo.</p>
            <button type="button" className="btn-teal mt-4 rounded-full px-5 py-2 text-sm font-medium">
              Inject at B
            </button>
          </article>
        </section>
      </main>
    </div>
  );
}
