import NeighborhoodFlow from "./components/NeighborhoodFlow";

const modes = [
  {
    name: "Static",
    title: "Equal share, capped",
    copy: "Every buyer gets a fair slice of the surplus pool, never more than they need. Leftover energy is redistributed — water-filling, not waste.",
  },
  {
    name: "Dynamic",
    title: "Priority when it matters",
    copy: "Serve the most homes first, or the largest need first. A configurable queue so the locality can choose what fairness means today.",
  },
  {
    name: "Hybrid",
    title: "Base share, then priority",
    copy: "A guaranteed slice for everyone, then the remaining pool follows a dynamic policy. Fair by default, efficient where it counts.",
  },
];

const steps = [
  {
    n: "01",
    title: "Forecast generation and load",
    copy: "The agent predicts solar and household demand — surplus is generation minus consumption, not a guess about usage alone.",
  },
  {
    n: "02",
    title: "Match on the same feeder",
    copy: "Sharing stays local. Virtual smart meters report each slot; the engine allocates surplus to neighbors on paper, on the shared grid.",
  },
  {
    n: "03",
    title: "Settle units and money apart",
    copy: "The discom reassigns kilowatt-hours. Neighbors settle P2P value through a wallet. Wires still earn a wheeling charge.",
  },
];

const pages = [
  { title: "Dashboard", copy: "Hourly solar and load — actual versus predicted — and today’s surplus or need." },
  { title: "Ledger", copy: "Grid import, solar export, P2P sold and bought. Units and rupees, clearly named." },
  { title: "Live simulation", copy: "Play, pause, switch modes, watch arrows between homes, inject sudden demand." },
  { title: "Compare modes", copy: "Surplus used, demand met by P2P, grid import cut, fairness — same day, three policies." },
];

export default function Home() {
  return (
    <div className="flex flex-col flex-1 text-forest">
      <nav className="pointer-events-none fixed top-5 left-1/2 z-30 w-full max-w-[min(94vw,56rem)] -translate-x-1/2 px-3">
        <div
          className="pointer-events-auto flex items-center justify-between gap-3 rounded-full px-5 py-2 shadow-[0_8px_28px_rgba(40,124,115,0.12)] ring-1 ring-white/50"
          style={{ background: "linear-gradient(135deg, #dcebdd 0%, #c8dec9 55%, #b8d8d0 100%)" }}
        >
          <a
            href="#top"
            className="rounded-full px-4 py-2 font-display text-sm text-dark-teal transition duration-300 hover:bg-white/50"
          >
            Grove Grid
          </a>
          <div className="hidden items-center gap-0.5 sm:flex">
            <a
              href="#how"
              className="rounded-full px-3.5 py-2 text-sm text-sage-text transition duration-300 hover:bg-white/55 hover:text-dark-teal"
            >
              How it works
            </a>
            <a
              href="#modes"
              className="rounded-full px-3.5 py-2 text-sm text-sage-text transition duration-300 hover:bg-white/55 hover:text-dark-teal"
            >
              Matching
            </a>
            <a
              href="#platform"
              className="rounded-full px-3.5 py-2 text-sm text-sage-text transition duration-300 hover:bg-white/55 hover:text-dark-teal"
            >
              Platform
            </a>
          </div>
          <a
            href="#cta"
            className="btn-teal inline-flex h-9 items-center rounded-full px-4 text-sm font-medium"
          >
            Dashboard
          </a>
        </div>
      </nav>

      <main id="top">
        <section id="hero-pin" className="relative h-[220vh]">
          <div className="sticky top-0 flex min-h-screen items-center overflow-hidden">
            <div
              aria-hidden
              className="pointer-events-none absolute inset-0"
              style={{
                background:
                  "radial-gradient(ellipse 70% 50% at 80% 10%, #fff2b8 0%, transparent 55%), radial-gradient(ellipse 50% 40% at 10% 80%, #c8dec9 0%, transparent 50%)",
              }}
            />
            <div className="relative mx-auto grid w-full max-w-6xl items-center gap-8 px-6 pt-24 pb-10 md:grid-cols-2 md:pt-28">
              <div>
                <h1 className="font-display text-4xl leading-tight text-forest sm:text-5xl lg:text-6xl">
                  Share rooftop sun with the house next door
                </h1>
                <p className="mt-6 max-w-xl text-lg leading-8 text-sage-text">
                  Grove Grid is a virtual allocation for neighborhood solar. Your surplus
                  goes onto the shared grid; a neighbor draws from it. We decide whose
                  export covers whose import — fairly, locally, and in every time slot.
                </p>
                <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                  <a
                    href="#cta"
                    className="btn-teal inline-flex h-12 items-center justify-center rounded-full px-8 text-base font-medium"
                  >
                    Start a local share
                  </a>
                  <a
                    href="#how"
                    className="btn-outline-teal inline-flex h-12 items-center justify-center rounded-full px-8 text-base font-medium"
                  >
                    See the matching engine
                  </a>
                </div>
                <p className="mt-6 text-sm text-sage-muted">
                  Sellers earn more than a feed-in tariff. Buyers pay less than retail.
                  The discom is paid for the wires.
                </p>
              </div>

              <NeighborhoodFlow />
            </div>
          </div>
        </section>

        <section id="how" className="border-t border-light-sage/80 bg-soft-off-white/40">
          <div className="mx-auto max-w-6xl px-6 py-20">
            <h2 className="font-display text-3xl text-forest sm:text-4xl">
              From forecast to a fair dispatch
            </h2>
            <p className="mt-3 max-w-2xl text-sage-text">
              An agent looks ahead. A matching engine classifies every home each
              slot. Settlement splits units from money so the story stays clear.
            </p>
            <div className="mt-12 grid gap-6 md:grid-cols-3">
              {steps.map((step) => (
                <article
                  key={step.n}
                  className="card-lift rounded-3xl border border-light-sage bg-warm-white p-7"
                >
                  <span className="font-display text-sm text-teal">{step.n}</span>
                  <h3 className="mt-3 font-display text-2xl text-dark-teal">{step.title}</h3>
                  <p className="mt-3 leading-7 text-sage-text">{step.copy}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="modes" className="mx-auto max-w-6xl px-6 py-20">
          <h2 className="font-display text-3xl text-forest sm:text-4xl">
            Three ways to share the pool
          </h2>
          <p className="mt-3 max-w-2xl text-sage-text">
            Compare Static, Dynamic, and Hybrid on the same day — surplus used,
            demand met by neighbors, grid import reduced, and Jain&apos;s fairness.
          </p>
          <div className="mt-12 grid gap-6 md:grid-cols-3">
            {modes.map((mode) => (
              <article
                key={mode.name}
                className="card-lift rounded-3xl border border-light-sage bg-gradient-to-b from-warm-white to-misty-sage/60 p-7"
              >
                <span className="rounded-full bg-teal px-3 py-1 text-xs font-medium text-white">
                  {mode.name}
                </span>
                <h3 className="mt-5 font-display text-2xl text-dark-teal">{mode.title}</h3>
                <p className="mt-3 leading-7 text-sage-text">{mode.copy}</p>
              </article>
            ))}
          </div>
        </section>

        <section id="platform" className="border-t border-light-sage/80">
          <div className="mx-auto max-w-6xl px-6 py-20">
            <h2 className="font-display text-3xl text-forest sm:text-4xl">
              A website that shows the living grid
            </h2>
            <p className="mt-3 max-w-2xl text-sage-text">
              Planned schedule from forecasts. Actual settlement from meters. When
              a home suddenly needs more, leftover surplus still finds them — or
              the grid steps in.
            </p>
            <div className="mt-12 grid gap-5 sm:grid-cols-2">
              {pages.map((page) => (
                <article
                  key={page.title}
                  className="card-lift rounded-2xl border border-light-sage bg-warm-white/80 px-6 py-6"
                >
                  <h3 className="font-display text-xl text-dark-teal">{page.title}</h3>
                  <p className="mt-2 text-sage-text">{page.copy}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section
          id="cta"
          className="mx-auto mb-20 max-w-6xl overflow-hidden rounded-3xl px-6"
        >
          <div
            className="rounded-3xl px-8 py-14 text-center text-white md:px-16"
            style={{
              background: "linear-gradient(135deg, #287c73 0%, #1a554f 100%)",
            }}
          >
            <h2 className="font-display text-3xl sm:text-4xl">
              Keep more sun in the neighborhood
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-white/85">
              Restrict sharing to the same feeder. Forecast both generation and
              load. Let the ledger speak in exported and imported kilowatt-hours —
              then settle gently between neighbors.
            </p>
            <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <a
                href="#"
                className="inline-flex h-12 items-center rounded-full bg-warm-white px-8 text-base font-medium text-dark-teal transition duration-300 hover:-translate-y-0.5 hover:scale-105 hover:shadow-lg"
              >
                View live simulation
              </a>
              <a
                href="#"
                className="inline-flex h-12 items-center rounded-full border border-white/40 px-8 text-base font-medium text-white transition duration-300 hover:-translate-y-0.5 hover:bg-white/10"
              >
                Read the monthly statement
              </a>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-light-sage/80 px-6 py-8 text-center text-sm text-sage-muted">
        Grove Grid · P2P energy sharing · virtual net metering, proposed with care
      </footer>
    </div>
  );
}
