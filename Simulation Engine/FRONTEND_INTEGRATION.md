# Frontend Integration Guide - P2P Energy Engine (for the Next.js developer)

This document tells you **what the engine gives you, which endpoint feeds which page, and the exact JSON shapes**.
You do **not** re-implement any energy logic in the frontend. The engine (Python, FastAPI) decides who sells to whom,
at what price, and writes the ledger. The frontend only **calls endpoints and displays the result**.

```
Next.js website  ──HTTP/JSON──►  ENGINE (FastAPI, port 8000)  ──HTTP──►  AI AGENT (forecast, other port)
                                    └─ SQLite (ledger, meter history)
```

---

## 1. Run the engine locally

```bash
cd p2p_engine
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8000
```
- Base URL: `http://localhost:8000` (same Wi-Fi teammates: `http://<engine-laptop-ip>:8000`)
- Interactive API docs (try every endpoint in the browser): `http://localhost:8000/docs`
- The engine's own control-room dashboard: `http://localhost:8000` (not for end users; see section 8)

CORS is enabled for all origins, so a Next.js app on `localhost:3000` can call it directly.

**Set the base URL once** in `.env.local`:
```
NEXT_PUBLIC_ENGINE_URL=http://localhost:8000
```

> **Deployment warning:** if the Next.js site is deployed (Vercel etc.) it cannot reach `localhost:8000` on someone's laptop,
> and an `https` page cannot call an `http` API (mixed content). For the hackathon demo either run Next.js locally
> (`npm run dev`) next to the engine, or expose the engine with a tunnel (`ngrok http 8000` or `cloudflared tunnel --url http://localhost:8000`)
> and put the `https://...` tunnel URL in `NEXT_PUBLIC_ENGINE_URL`.

---

## 2. Core concepts (read this first)

| Concept | Meaning |
|---|---|
| **Node / home** | One household = one node. IDs are `A` to `J`. A logged-in user maps to one node ID. |
| **Slot** | One simulated **hour**. `hour: 13` means the slot 13:00-14:00. `day` starts at 0. |
| **Simulation clock** | One global clock for the whole engine. `/state` `day`/`hour` is the **next slot to be simulated**; the **latest completed slot** is `last.slot`. |
| **Role** | `supplier` (has surplus solar / spare battery), `buyer` (needs power), `neutral`. |
| **Mode** | How the shared pool is split: `static` (equal, capped at need), `dynamic` (priority queue), `hybrid` (base share + priority). |
| **Pool** | Total spare energy offered in a slot. |
| **Planned vs actual** | `pred_*` / `planned_p2p` come from the AI agent's forecast. Everything else is the actual (simulated meter) outcome. The gap is a key demo feature. |
| **Units** | All energy is **kWh per slot**, money is **Rs (INR)**. |
| **`p2p_bought`** | Units the user **received** from neighbours = "credited" in their ledger (they owe money). |
| **`p2p_sold`** | Units the user **gave** to neighbours = "debited" in their ledger (they earn money). |
| **`grid_import` / `grid_export`** | Units drawn from / pushed to the **discom**. Shown in **units only, no price** (discom bills that itself). |

The simulation only has data for slots that have actually run. After **Reset**, every history/ledger endpoint is empty until you Start/Step.
Your UI must handle empty arrays.

The demo community has 10 homes. Solar homes: A (4.5 kW + 8 kWh battery), C (3 kW), E (4 kW + 8 kWh battery), G (2 kW). Homes without solar: B, D, F, H, I, J.

---

## 3. Which page uses which endpoint

| Frontend page / widget | Endpoint(s) | Poll? |
|---|---|---|
| **User dashboard: hourly consumption graph** | `GET /ledger/{node}?limit=24` (load, solar per hour) | every 2-3 s |
| **User dashboard: today's summary card** | `GET /statement/{node}` | every 3-5 s |
| **Ledger page** | `GET /ledger/{node}?limit=48` | every 2-3 s |
| **Monthly statement / bill page** | `GET /statement/{node}` | on open |
| **Live community view** (who feeds whom, supply vs demand chart) | `GET /state` | every 1 s while running |
| **Simulation controls** (admin / demo) | `POST /start`, `/pause`, `/step`, `/speed`, `/mode`, `/inject`, `/reset` | on click |
| **Sharing-mode comparison page** | `GET /compare?days=3` | on click (takes ~1 s) |
| **Audit / all transactions** | `GET /ledger_all?limit=100` | optional |
| **Notifications / activity feed** | `GET /events` or `state.events` | with `/state` |

There is no websocket; use polling (SWR or React Query with `refreshInterval`).

---

## 4. Control endpoints (all `POST`, no body, parameters in the query string)

| Call | Effect | Response |
|---|---|---|
| `POST /start` | Auto-advance the clock | `{"running": true}` |
| `POST /pause` | Stop the clock | `{"running": false}` |
| `POST /step` | Advance exactly one hour, returns that slot's full result (same shape as `state.last`) | step result |
| `POST /speed?value=3` | Simulated hours per real second (0.1 to 20) | `{"speed": 3.0}` |
| `POST /mode?name=hybrid` | `static` / `dynamic` / `hybrid` (takes effect from the next slot). 400 on bad name | `{"mode": "hybrid"}` |
| `POST /inject?node=B&kwh=3` | Sudden extra load at a node in the **next** slot (the "agent didn't predict this" demo). 404 on unknown node | `{"queued": {"B": 3.0}}` |
| `POST /reset?mode=hybrid` | Stop, wipe all history and ledger, start over | `{"ok": true}` |

---

## 5. Read endpoints with real response samples

### `GET /state`  (main live feed)
```json
{
  "running": false, "speed": 1.0, "mode": "hybrid",
  "day": 0, "hour": 13,                      // NEXT slot to run
  "pending": {},                             // injected loads waiting for the next slot, e.g. {"B": 3.0}
  "tariff": { "feed_in": 3.0, "retail": 8.0, "grid_fee": 0.5 },
  "nodes": [ { "id": "A", "panel_kw": 4.5, "base_kw": 0.5, "battery_kwh": 8, "soc": 1.13, "feeder": "Feeder-1" } /* ...A to J */ ],
  "last": { /* latest completed slot, see below; null before the first slot */ },
  "events": [ { "day": 0, "hour": 12, "text": "Sudden +3.0 kWh load at B: agent planned P2P 1.01 kWh, actual need 3.97 kWh -> P2P served 3.71 kWh, discom grid 0.26 kWh" } ],
  "history": [ { "day": 0, "hour": 12, "supply": 8.497, "demand": 8.759, "matched": 8.497, "grid_import": 0.262, "price": 5.28, "planned_matched": 6.054 } /* last 72 slots */ ],
  "summary": { "mode": "hybrid", "supply_used_pct": 92.0, "demand_met_by_p2p_pct": 37.7, "homes_fully_served_pct": 30.6,
               "fairness_jain": 0.366, "p2p_kwh": 34.69, "grid_import_kwh": 57.43, "user_gain_rs": 156.1,
               "discom_fee_rs": 17.3, "forecast_mae_load": 0.085 }
}
```

`state.last` (identical to the `POST /step` response):
```json
{
  "slot": { "day": 0, "hour": 12, "supply": 8.497, "demand": 8.759, "matched": 8.497,
            "grid_import": 0.262, "price": 5.28, "planned_matched": 6.054 },
  "mode": "hybrid",
  "forecast_source": "baseline",              // "agent" when the real AI agent answered
  "matches": [ { "seller": "A", "buyer": "B", "kwh": 1.481 }, { "seller": "C", "buyer": "B", "kwh": 0.752 } ],
  "events": [ "Sudden +3.0 kWh load at B: ..." ],
  "nodes": [
    { "day": 0, "hour": 12, "node": "B", "role": "buyer", "feeder": "Feeder-1",
      "load": 3.973, "solar": 0.0,
      "pred_load": 1.009, "pred_solar": 0.0, "planned_p2p": 1.009,      // agent's plan
      "p2p_bought": 3.711, "p2p_sold": 0.0,                              // actual P2P
      "grid_import": 0.262, "grid_export": 0.0,                          // discom, units only
      "batt_charge": 0.0, "soc": 0.0 }                                   // battery (kWh)
    /* ...one object per node */
  ]
}
```
Field notes: `supply` = pool offered, `demand` = total unmet-by-self need, `matched` = P2P energy actually shared,
`price` = Rs/kWh this slot (rises when supply is scarce, between feed-in and retail minus grid fee).

### `GET /ledger/{node}?limit=48`  (user ledger, oldest first)
```json
[
  { "day": 0, "hour": 11, "load": 0.952, "solar": 0.0, "grid_import": 0.0, "grid_export": 0.0,
    "p2p_bought": 0.952, "p2p_sold": 0.0, "soc": 0.0, "p2p_earned_rs": 0.0, "p2p_owed_rs": 4.59 },
  { "day": 0, "hour": 12, "load": 3.973, "solar": 0.0, "grid_import": 0.262, "grid_export": 0.0,
    "p2p_bought": 3.711, "p2p_sold": 0.0, "soc": 0.0, "p2p_earned_rs": 0.0, "p2p_owed_rs": 19.59 }
]
```
Suggested ledger row text:
- discom part: `Grid import 0.26 kWh`, `Grid export 0 kWh` (units only, **never show a price here**)
- `p2p_bought > 0` → `+3.71 kWh credited from neighbours, pay Rs 19.59`
- `p2p_sold > 0` → `-3.39 kWh sold to neighbours, earned Rs X`
- empty array (also returned for an unknown node ID) → "No activity yet"

### `GET /statement/{node}`  (totals since reset)
```json
{ "node": "B", "discom_import_kwh": 8.63, "discom_export_kwh": 0.0,
  "p2p_sold_kwh": 0, "p2p_earned_rs": 0, "p2p_bought_kwh": 8.22, "p2p_owed_rs": 44.23,
  "grid_fee_on_discom_bill_rs": 4.11, "net_wallet_rs": -44.23,
  "note": "P2P units are reassigned on the discom bill (virtual net metering); money settles between users via the platform wallet; the discom receives the per-unit grid fee." }
```
`net_wallet_rs` = earned − owed (negative = user owes). `grid_fee_on_discom_bill_rs` is the per-unit grid/wheeling fee the discom charges on P2P units, shown as a bill line item.

### `GET /compare?days=3`  (runs all 3 modes on identical data; fresh simulation, does not touch the live one)
```json
[ { "mode": "static", "supply_used_pct": 88.4, "demand_met_by_p2p_pct": 27.5, "homes_fully_served_pct": 17.8,
    "fairness_jain": 0.337, "p2p_kwh": 56.99, "grid_import_kwh": 149.91, "user_gain_rs": 256.5,
    "discom_fee_rs": 28.5, "forecast_mae_load": 0.074 }, { "mode": "dynamic", ... }, { "mode": "hybrid", ... } ]
```
`days` is clamped to 1-7. Interpretation for UI text: dynamic serves the most homes completely, static is the fairest (higher `fairness_jain`, max 1.0), hybrid balances both.

### `GET /ledger_all?limit=100`  (every P2P transaction, oldest first)
```json
[ { "day": 0, "hour": 12, "seller": "A", "buyer": "B", "kwh": 1.4806, "price": 5.28, "amount": 7.817,
    "grid_fee": 0.74, "mode": "hybrid", "source": "solar" } ]
```
`source` is `solar` or `battery`.

### `GET /events`
`[ { "day": 0, "hour": 12, "text": "..." } ]` newest first, up to 50.

---

## 6. Copy-paste code (Next.js, TypeScript)

`lib/engine.ts`
```ts
const BASE = process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://localhost:8000";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json();
}
async function post<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { method: "POST" });
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json();
}

export type NodeSlot = {
  day: number; hour: number; node: string; role: "supplier" | "buyer" | "neutral"; feeder: string;
  load: number; solar: number; pred_load: number; pred_solar: number; planned_p2p: number;
  p2p_bought: number; p2p_sold: number; grid_import: number; grid_export: number; batt_charge: number; soc: number;
};
export type Slot = { day: number; hour: number; supply: number; demand: number; matched: number;
                     grid_import: number; price: number; planned_matched: number };
export type StepResult = { slot: Slot; mode: string; forecast_source: "agent" | "baseline";
                           nodes: NodeSlot[]; matches: { seller: string; buyer: string; kwh: number }[]; events: string[] };
export type EngineState = {
  running: boolean; speed: number; mode: "static" | "dynamic" | "hybrid"; day: number; hour: number;
  pending: Record<string, number>; tariff: { feed_in: number; retail: number; grid_fee: number };
  nodes: { id: string; panel_kw: number; base_kw: number; battery_kwh: number; soc: number; feeder: string }[];
  last: StepResult | null; events: { day: number; hour: number; text: string }[]; history: Slot[];
  summary: Record<string, number | string>;
};
export type LedgerRow = { day: number; hour: number; load: number; solar: number; grid_import: number; grid_export: number;
                          p2p_bought: number; p2p_sold: number; soc: number; p2p_earned_rs: number; p2p_owed_rs: number };
export type Statement = { node: string; discom_import_kwh: number; discom_export_kwh: number; p2p_sold_kwh: number;
                          p2p_earned_rs: number; p2p_bought_kwh: number; p2p_owed_rs: number;
                          grid_fee_on_discom_bill_rs: number; net_wallet_rs: number; note: string };

export const engine = {
  state: () => get<EngineState>("/state"),
  ledger: (node: string, limit = 48) => get<LedgerRow[]>(`/ledger/${node}?limit=${limit}`),
  statement: (node: string) => get<Statement>(`/statement/${node}`),
  compare: (days = 3) => get<Record<string, number | string>[]>(`/compare?days=${days}`),
  ledgerAll: (limit = 100) => get<unknown[]>(`/ledger_all?limit=${limit}`),
  start: () => post("/start"), pause: () => post("/pause"), step: () => post<StepResult>("/step"),
  speed: (v: number) => post(`/speed?value=${v}`), mode: (m: string) => post(`/mode?name=${m}`),
  inject: (node: string, kwh = 3) => post(`/inject?node=${node}&kwh=${kwh}`),
  reset: (mode = "hybrid") => post(`/reset?mode=${mode}`),
};
```

Polling with SWR (`npm i swr`):
```tsx
"use client";
import useSWR from "swr";
import { engine } from "@/lib/engine";

export function useEngineState() {
  return useSWR("state", engine.state, { refreshInterval: 1000 });
}
export function useLedger(node: string) {
  return useSWR(["ledger", node], () => engine.ledger(node, 24), { refreshInterval: 2500 });
}
```

Per-user hourly consumption chart (Recharts), from the ledger endpoint:
```tsx
const { data = [] } = useLedger("B");
const chart = data.map(r => ({ t: `${String(r.hour).padStart(2, "0")}:00`, load: r.load, solar: r.solar,
                               p2p_in: r.p2p_bought, grid: r.grid_import }));
// <LineChart data={chart}> lines: load, solar, p2p_in, grid
```

"Predicted vs actual" chart for the logged-in user (live) from `state.last.nodes`:
```ts
const me = state.last?.nodes.find(n => n.node === myNode);
// me.pred_load vs me.load, me.planned_p2p vs me.p2p_bought
```
(For a time series, push `me` into a client-side array each time `state.last.slot` changes.)

Community supply vs demand chart: use `state.history` directly: lines for `supply`, `demand`, `matched`, `planned_matched`.

Energy-flow arrows: `state.last.matches` (`seller -> buyer, kwh`).

---

## 7. Mapping a logged-in user to a node

The engine has no login. Keep a mapping in the frontend (for the demo a dropdown or a fixed table):
```ts
const USER_TO_NODE = { "aaditya@x.com": "B", "demo-seller@x.com": "A" };
```
Use that node ID in `/ledger/{node}` and `/statement/{node}`. `GET /state` returns `nodes[]` if you need to list all homes.

---

## 8. What the built-in dashboard (`http://localhost:8000`) is for

It is a **control room for the demo and for testing**, not the user-facing product. It uses the same endpoints described here.
Use it to (1) verify the engine works before wiring the frontend, (2) run the live "sudden demand" demo, (3) as a fallback if the
Next.js site is not ready. Admin-only controls (`/inject`, `/speed`, `/mode`, `/reset`) should not appear on the normal user pages.
Optionally embed it: `<iframe src={BASE} style={{width: "100%", height: 900, border: 0}} />`.

---

## 9. Gotchas

1. **One shared simulation.** Everyone who presses Start or changes the mode affects the same clock. Treat it as one simulated community.
2. **Empty at first.** Before the first slot, `state.last` is `null` and ledger endpoints return `[]`. After `/reset` the same.
3. **Values are numbers in kWh/Rs, rounded to 3-4 decimals.** Round for display (`toFixed(2)`).
4. **Unknown node on `/inject`** returns 404; bad mode returns 400.
5. **Do not compute allocation, price or ledger in the frontend.** The engine is the single source of truth.
6. **Poll sensibly:** `/state` at 1 s is fine; ledger endpoints every 2-3 s; `/compare` only on demand.
7. **Dev proxy alternative** (avoid CORS and hard-coded URLs): in `next.config.js` add
   `async rewrites() { return [{ source: "/engine/:path*", destination: "http://localhost:8000/:path*" }]; }` and call `/engine/state`.
8. **The clock only moves when the engine runs it.** Show a clear Start/Pause/Step UI, or the page will look frozen.

---

## 10. For the agent developer (the other integration)

The engine calls the agent, not the other way around. Each slot, for every home, it POSTs:
```json
POST <FORECAST_URL>
{ "node_id": "B", "hour": 14, "day": 0, "panel_kw": 0, "base_kw": 1.4, "household_size": 5, "appliances": ["ac","geyser","fridge"] }
```
and expects within ~1.5 s:
```json
{ "pred_load": 0.92, "pred_solar": 0.0 }
```
(kWh for that single hour). Start the engine with `FORECAST_URL=http://<agent-host>:<port>/predict uvicorn server:app --port 8000`.
When it works, `state.last.forecast_source` changes from `"baseline"` to `"agent"`. If the agent errors or times out, the engine falls back to
its baseline forecaster automatically, so the demo never breaks.

---

## 11. Quick test checklist (5 minutes)

1. `uvicorn server:app --port 8000`, open `http://localhost:8000/docs`.
2. `POST /step` a few times (or `/start`), then `GET /state` and confirm `last` is filled.
3. `GET /ledger/B` returns rows and `GET /statement/B` returns totals.
4. From the Next.js app: `fetch("http://localhost:8000/state")` works with no CORS error.
5. `POST /inject?node=B&kwh=3` then `POST /step` around hour 11-12: an event appears in `state.events`.
