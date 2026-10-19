# Frontend Integration Guide - P2P Energy Engine v2 (for the Next.js developer)

The engine (Python/FastAPI) decides who sells to whom, at what price, and writes the ledger. The frontend only **calls
endpoints and displays results**; never re-implement allocation, pricing or ledger logic in the frontend.

```
Next.js website --HTTP/JSON--> ENGINE (FastAPI :8000) --HTTP--> AI AGENT (forecast)
                                   |-- SQLite or DynamoDB (ledger, meter history, saved state)
```
Interactive docs for every endpoint: `http://<engine>/docs`. The engine also serves its own control-room dashboard at `/`.

---
## 1. Connect
- Base URL: `http://localhost:8000` (teammates on the same Wi-Fi: `http://<engine-laptop-ip>:8000`). In `.env.local`: `NEXT_PUBLIC_ENGINE_URL=http://localhost:8000`.
- CORS is open (`*`), so `localhost:3000` can call it directly.
- **Admin token:** if the engine runs with `ADMIN_TOKEN`, every **POST / PATCH / DELETE** needs the header `X-Admin-Token: <token>` (else HTTP 401). **GET endpoints are always open.** `GET /state` has `auth_required: true|false`.
- **Deployed frontend (Vercel):** it cannot reach `localhost`, and an `https` page cannot call an `http` API from the browser (mixed content). Options: run Next.js locally next to the engine; or proxy through Next.js (`next.config.js`: `async rewrites() { return [{ source: "/engine/:path*", destination: "http://<ENGINE_IP>:8000/:path*" }]; }` and call `/engine/state`); or put HTTPS in front of the engine (tunnel / CloudFront / domain).

## 2. Concepts
| Term | Meaning |
|---|---|
| **Node / home** | One household. Demo IDs `A`-`J`; users can add more at runtime. A logged-in user maps to one node ID. |
| **Slot** | One simulated hour. `hour: 13` = 13:00-14:00; `day` starts at 0 (day 0 is a Monday). |
| **Clock** | One global clock. `state.day/hour` is the NEXT slot to run; the latest completed slot is `state.last.slot`. |
| **Role** | `supplier` (surplus solar / spare battery), `buyer` (needs power), `neutral`. |
| **Mode** | `static` / `dynamic` / `hybrid` pool-sharing policy. |
| **Appliance** | Every home's load is a list of appliances (type, kW, hour window, duty...). Flexible ones get their run-hours placed in sunny hours by the engine. |
| **Event** | Temporary extra load (`type:"event"`); `surprise:true` means the forecast agent is not told. |
| **Scenario** | Weather (`temp_c`, `cloud_cover` 0-1) and grid `outage`. |
| **Planned vs actual** | `pred_*` / `planned_p2p` come from the agent; everything else is the actual outcome. |
| **Units** | Energy in kWh per slot, money in Rs (INR), CO2 in kg. |
| `p2p_bought` / `p2p_sold` | Units received from / given to neighbours (ledger "credited" / "debited"). |
| `grid_import` / `grid_export` | Units from / to the discom. **Units only, never a price.** |
| `unserved` | Load nobody could supply (only during an outage). `curtailed` = surplus wasted because the grid is down. |
| `benefit_rs` | Rs saved vs buying everything from the discom (buyer saving + seller extra earning). |

History/ledger endpoints are empty until slots have run (and after `/reset`); handle empty arrays.

## 3. Page -> endpoint map
| Page / widget | Endpoint | Poll |
|---|---|---|
| Live community view, supply/demand chart, flows | `GET /state` | 1 s while running |
| User dashboard: hourly consumption graph | `GET /ledger/{node}?limit=24` | 2-3 s |
| User ledger | `GET /ledger/{node}?limit=48` | 2-3 s |
| Statement / bill page | `GET /statement/{node}` | on open |
| Simulation controls (admin) | `POST /start /pause /step /speed /mode /reset` | click |
| House & appliance manager | `GET /nodes`, `/nodes/{id}`, `/catalog` + editing endpoints (section 5) | on open / after edit |
| Scenario panel (weather, outage) | `GET/POST /scenario` | click |
| Tariff / policy settings | `GET/POST /settings` | click |
| Mode comparison | `GET /compare?days=3` | click (~1-2 s) |
| Export / import | `GET /export/ledger.csv`, `/export/meter.csv`, `GET/POST /config` | click |
| Audit | `GET /ledger_all`, `GET /events` | optional |
No websocket: use polling (SWR / React Query `refreshInterval`).

## 4. Control endpoints (all POST, parameters in the query string unless noted)
| Call | Effect / response |
|---|---|
| `/start` `/pause` | Auto-advance / stop. `{"running": bool}` |
| `/step` | Advance exactly one hour; returns the slot result (same shape as `state.last`) |
| `/speed?value=3` | Simulated hours per real second, 0.1-20 |
| `/mode?name=hybrid` | `static` / `dynamic` / `hybrid` (400 if invalid) |
| `/inject?node=B&kwh=3` | One-hour surprise load at B starting next slot. `{"queued": {"B": 3.0}}` |
| `/reset` | Clears history + clock, **keeps houses/appliances/settings**. Optional `?mode=` |
| `/reset?defaults=true` | Also restores the original 10-home demo community and default settings |
Errors: 400 = invalid value (message in `detail`), 404 = unknown node/appliance, 401 = admin token missing/wrong.

## 5. Editing the community (POST/PATCH/DELETE, JSON bodies)
| Call | Body | Notes |
|---|---|---|
| `POST /nodes` | `{id?, panel_kw, battery_kwh, household_size, feeder, ac:"none\|night\|day\|both", appliances?: ["fridge", {"type":"ev","kw":7.2}]}` | Omit `appliances` for a starter set based on household size. Returns the node. `id` 1-12 chars `[A-Za-z0-9_-]`, auto-letter if omitted |
| `PATCH /nodes/{id}` | any of `panel_kw, battery_kwh, household_size, feeder` | |
| `DELETE /nodes/{id}` | - | History stays in the ledger. Minimum 2 homes |
| `POST /nodes/{id}/appliances` | `{type, name?, kw?, start?, end?, duty?, days?, sensitivity?, flexible?, duration_h?}` | Catalog defaults fill missing fields |
| `PATCH /nodes/{id}/appliances/{aid}` | any of `name, kw, start, end, duty, days, sensitivity, enabled, flexible, duration_h` | |
| `POST /nodes/{id}/appliances/{aid}/toggle` | - | enable / disable |
| `DELETE /nodes/{id}/appliances/{aid}` | - | |
| `POST /nodes/{id}/events` | `{kw, hours:1, surprise:true, name?}` | Temporary load from the next hour for `hours` hours |
| `POST /scenario` | `{preset?: "clear\|heatwave\|monsoon\|winter\|outage\|restore", temp_c?, cloud_cover?, outage?}` | Returns the scenario. temp -10..55, cloud 0..1 |
| `POST /settings` | `{feed_in, retail, grid_fee, dynamic_price, beta, policy:"smallest_first\|largest_first", co2_factor}` (all optional) | Needs `feed_in < retail - grid_fee` |
| `POST /config` | a JSON exported by `GET /config` | Replaces the whole community, clears history |
Appliance rules: `kw` 0-50; `start/end` hours 0-24, a window may wrap midnight (`22 -> 7`); `duty` 0-1 = fraction of the window actually drawing power;
`days` = `all|weekday|weekend`; `sensitivity` = `none|cooling|heating` (scales with temperature); **flexible** needs a same-day window (`start < end`) and `duration_h` <= window length.
`GET /catalog` returns all appliance types with their defaults (use it to fill your "add load" form).

## 6. Read endpoints with real samples

### `GET /state`
```json
{ "running": false, "error": null, "speed": 1.0, "mode": "hybrid", "day": 0, "hour": 14,
  "pending": {"D": 2.0},                                   // queued event loads by node (kW)
  "scenario": {"temp_c": 30.0, "cloud_cover": 0.15, "outage": false},
  "settings": {"feed_in": 3.0, "retail": 8.0, "grid_fee": 0.5, "dynamic_price": true, "beta": 0.5, "policy": "smallest_first", "co2_factor": 0.82},
  "tariff": {"feed_in": 3.0, "retail": 8.0, "grid_fee": 0.5},
  "auth_required": false, "db_backend": "sqlite", "restored": false,
  "nodes": [ {"id":"B","panel_kw":0.0,"battery_kwh":0.0,"soc":0.0,"feeder":"Feeder-1","household_size":5,"n_appliances":9} ],
  "last": { /* latest completed slot (below) or null */ },
  "events": [ {"day":0,"hour":13,"text":"Sudden +3.0 kW load 'Guests arrive' at B: agent planned P2P 1.02 kWh, actual need 4.03 kWh -> P2P served 4.03 kWh, discom grid 0.00 kWh"} ],
  "history": [ {"day":0,"hour":13,"supply":9.927,"demand":8.863,"matched":8.863,"grid_import":0.0,"price":5.12,"planned_matched":5.888,"load":9.836,"solar":10.9,"unserved":0.0} ],   // last 72 slots
  "summary": {"mode":"hybrid","supply_used_pct":54.0,"demand_met_by_p2p_pct":49.4,"homes_fully_served_pct":45.4,"fairness_jain":0.472,
              "p2p_kwh":26.79,"grid_import_kwh":27.43,"user_gain_rs":120.5,"discom_fee_rs":13.4,"local_energy_share_pct":63.0,
              "co2_avoided_kg":21.97,"unserved_kwh":0.0,"curtailed_kwh":0.0,"grid_import_reduction_pct":49.4,"peak_grid_kw":7.81,"forecast_mae_load":0.041} }
```
`state.last` (identical to the `POST /step` response):
```json
{ "slot": {"day":0,"hour":13,"supply":9.927,"demand":8.863,"matched":8.863,"grid_import":0.0,"price":5.12,"planned_matched":5.888,"load":9.836,"solar":10.9,"unserved":0.0},
  "mode": "hybrid", "forecast_source": "baseline",           // "agent" when your ML agent answered
  "scenario": {"temp_c":30.0,"cloud_cover":0.15,"outage":false},
  "matches": [ {"seller":"A","buyer":"B","kwh":1.481} ],
  "events": [ "..." ],
  "nodes": [ { "day":0,"hour":13,"node":"B","role":"buyer","feeder":"Feeder-1",
               "load":4.028,"solar":0.0,"pred_load":1.018,"pred_solar":0.0,"planned_p2p":1.018,
               "p2p_bought":4.028,"p2p_sold":0.0,"grid_import":0.0,"grid_export":0.0,"batt_charge":0.0,"soc":0.0,
               "p2p_earned_rs":0.0,"p2p_owed_rs":20.623,"grid_fee_rs":2.014,"unserved":0.0,"curtailed":0.0,"benefit_rs":9.587 } ] }
```
### `GET /ledger/{node}?limit=48` (oldest first; empty array if none)
`[ {"day":0,"hour":13,"load":4.028,"solar":0.0,"grid_import":0.0,"grid_export":0.0,"p2p_bought":4.028,"p2p_sold":0.0,"soc":0.0,"p2p_earned_rs":0.0,"p2p_owed_rs":20.623,"unserved":0.0,"benefit_rs":9.587} ]`
Row text: discom part in units only; `p2p_bought>0` -> "+4.03 kWh credited, pay Rs 20.62"; `p2p_sold>0` -> "-3.39 kWh sold, earned Rs X"; `benefit_rs` = "saved vs no P2P".
### `GET /statement/{node}` (totals since the last reset)
```json
{ "node":"B","discom_import_kwh":5.47,"discom_export_kwh":0,"p2p_sold_kwh":0,"p2p_earned_rs":0,"p2p_bought_kwh":7.69,"p2p_owed_rs":38.37,
  "grid_fee_on_discom_bill_rs":3.84,"p2p_benefit_rs":19.3,"unserved_kwh":0,"total_load_kwh":13.16,"total_solar_kwh":0,"net_wallet_rs":-38.37,"note":"..." }
```
### `GET /nodes/{id}`
```json
{ "id":"E","panel_kw":4.0,"battery_kwh":8.0,"household_size":4,"feeder":"Feeder-1","soc":4.0,
  "expected_daily_load_kwh":14.2,"expected_daily_solar_kwh":19.1,
  "appliances":[ {"id":"ebc197","type":"ev","name":"EV charger (flexible)","kw":3.3,"start":9,"end":23,"duty":1.0,"days":"all","sensitivity":"none",
                  "enabled":true,"flexible":true,"duration_h":3,"surprise":false,"sched":[9,10,11],"sched_day":0,"daily_kwh":9.9} ] }
```
(`sched` = the hours today when a flexible load runs. Event loads also have `once: {day, hour, hours}`.) `GET /nodes` returns the list.
### Others
`GET /compare?days=3` -> list of 3 summary objects (same fields as `state.summary`) for static/dynamic/hybrid on the CURRENT community, fresh clock (days 1-7).
`GET /ledger_all?limit=100` -> `[{day,hour,seller,buyer,kwh,price,amount,grid_fee,mode,source}]` (`source` = solar|battery).
`GET /events` -> `[{day,hour,text}]` newest first. `GET /scenario`, `GET /settings`, `GET /health` -> `{ok, db_backend, running, version}`.
`GET /config` -> `{mode, settings, scenario, nodes:[...], version}` to save a community; `POST /config` loads one (nodes may list just `{id, panel_kw, appliances:[{type:"ac"}]}`).

## 7. Copy-paste code (Next.js, TypeScript)
`lib/engine.ts`
```ts
const BASE = process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://localhost:8000";
const ADMIN = process.env.NEXT_PUBLIC_ENGINE_ADMIN_TOKEN;      // only for an admin page; never ship a real secret to normal users

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method, cache: "no-store",
    headers: { "Content-Type": "application/json", ...(ADMIN && method !== "GET" ? { "X-Admin-Token": ADMIN } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail ?? `${path} -> ${r.status}`); }
  return r.json();
}

export type NodeSlot = { day:number; hour:number; node:string; role:"supplier"|"buyer"|"neutral"; feeder:string; load:number; solar:number;
  pred_load:number; pred_solar:number; planned_p2p:number; p2p_bought:number; p2p_sold:number; grid_import:number; grid_export:number;
  batt_charge:number; soc:number; p2p_earned_rs:number; p2p_owed_rs:number; grid_fee_rs:number; unserved:number; curtailed:number; benefit_rs:number };
export type Slot = { day:number; hour:number; supply:number; demand:number; matched:number; grid_import:number; price:number;
  planned_matched:number; load:number; solar:number; unserved:number };
export type StepResult = { slot:Slot; mode:string; forecast_source:"agent"|"baseline"; scenario:Scenario; nodes:NodeSlot[];
  matches:{seller:string;buyer:string;kwh:number}[]; events:string[] };
export type Scenario = { temp_c:number; cloud_cover:number; outage:boolean };
export type Settings = { feed_in:number; retail:number; grid_fee:number; dynamic_price:boolean; beta:number; policy:"smallest_first"|"largest_first"; co2_factor:number };
export type Summary = Record<string, number|string>;
export type EngineState = { running:boolean; error:string|null; speed:number; mode:"static"|"dynamic"|"hybrid"; day:number; hour:number;
  pending:Record<string,number>; scenario:Scenario; settings:Settings; auth_required:boolean; db_backend:string; restored:boolean;
  nodes:{id:string;panel_kw:number;battery_kwh:number;soc:number;feeder:string;household_size:number;n_appliances:number}[];
  last:StepResult|null; events:{day:number;hour:number;text:string}[]; history:Slot[]; summary:Summary };
export type Appliance = { id:string; type:string; name:string; kw:number; start:number; end:number; duty:number; days:string; sensitivity:string;
  enabled:boolean; flexible:boolean; duration_h:number; surprise:boolean; sched?:number[]; once?:{day:number;hour:number;hours:number}; daily_kwh:number };
export type NodeDetail = { id:string; panel_kw:number; battery_kwh:number; household_size:number; feeder:string; soc:number;
  expected_daily_load_kwh:number; expected_daily_solar_kwh:number; appliances:Appliance[] };
export type LedgerRow = { day:number; hour:number; load:number; solar:number; grid_import:number; grid_export:number; p2p_bought:number;
  p2p_sold:number; soc:number; p2p_earned_rs:number; p2p_owed_rs:number; unserved:number; benefit_rs:number };

export const engine = {
  state: () => call<EngineState>("GET", "/state"),
  ledger: (node:string, limit=48) => call<LedgerRow[]>("GET", `/ledger/${node}?limit=${limit}`),
  statement: (node:string) => call<Record<string, number|string>>("GET", `/statement/${node}`),
  compare: (days=3) => call<Summary[]>("GET", `/compare?days=${days}`),
  catalog: () => call<{appliances:Record<string,any>}>("GET", "/catalog"),
  nodes: () => call<NodeDetail[]>("GET", "/nodes"),
  node: (id:string) => call<NodeDetail>("GET", `/nodes/${id}`),
  start: () => call("POST", "/start"), pause: () => call("POST", "/pause"), step: () => call<StepResult>("POST", "/step"),
  speed: (v:number) => call("POST", `/speed?value=${v}`), mode: (m:string) => call("POST", `/mode?name=${m}`),
  reset: (defaults=false) => call("POST", `/reset?defaults=${defaults}`),
  inject: (node:string, kwh=3) => call("POST", `/inject?node=${node}&kwh=${kwh}`),
  addNode: (b:object) => call<NodeDetail>("POST", "/nodes", b),
  patchNode: (id:string, b:object) => call<NodeDetail>("PATCH", `/nodes/${id}`, b),
  deleteNode: (id:string) => call("DELETE", `/nodes/${id}`),
  addAppliance: (id:string, b:object) => call<Appliance>("POST", `/nodes/${id}/appliances`, b),
  patchAppliance: (id:string, aid:string, b:object) => call<Appliance>("PATCH", `/nodes/${id}/appliances/${aid}`, b),
  toggleAppliance: (id:string, aid:string) => call<Appliance>("POST", `/nodes/${id}/appliances/${aid}/toggle`),
  deleteAppliance: (id:string, aid:string) => call("DELETE", `/nodes/${id}/appliances/${aid}`),
  addEvent: (id:string, b:{kw:number;hours?:number;surprise?:boolean;name?:string}) => call("POST", `/nodes/${id}/events`, b),
  scenario: (b:Partial<Scenario> & {preset?:string}) => call<Scenario>("POST", "/scenario", b),
  settings: (b:Partial<Settings>) => call<Settings>("POST", "/settings", b),
  exportConfig: () => call<object>("GET", "/config"), importConfig: (c:object) => call("POST", "/config", c),
};
```
Polling hook (`npm i swr`): `useSWR("state", engine.state, { refreshInterval: 1000 })`, ledger: `useSWR(["ledger", node], () => engine.ledger(node, 24), { refreshInterval: 2500 })`.
Charts: community chart from `state.history` (`supply, demand, matched, planned_matched`); user consumption chart from `/ledger/{node}` (`load, solar, p2p_bought, grid_import`); predicted vs actual from `state.last.nodes` (`pred_load` vs `load`, `planned_p2p` vs `p2p_bought`); flow arrows from `state.last.matches`; show a red banner when `state.error` is set and an "OUTAGE" badge when `state.scenario.outage`.
Each user maps to a node: `const USER_TO_NODE = { "user@x.com": "B" }`; admin-only controls (`/inject`, `/speed`, `/mode`, `/reset`, `/scenario`, editing) must not appear on normal user pages.

## 8. Gotchas
1. One shared simulation: everyone's Start/Pause/Mode/Scenario changes affect the same world.
2. After a server restart the engine **restores** houses, appliances, weather, settings and the clock from its database (`state.restored: true`). Use `/reset` for a clean run.
3. Round numbers for display (`toFixed(2)`); never compute prices or allocation in the frontend.
4. After editing a house or appliance, re-fetch `/nodes/{id}`; changes take effect from the next simulated hour. Flexible loads are re-planned automatically.
5. With DynamoDB each simulated hour does several network writes, so very high speeds (>2-3 h/s) are capped by database latency.
6. Event/Sudden loads only affect the next hour(s); `pending` lists those not started yet.
7. Interactive checks: `/docs` lets you try every call in the browser.

## 9. For the agent developer
Each slot, for every home, the engine POSTs to `FORECAST_URL`:
```json
{ "node_id":"B","day":0,"hour":14,"panel_kw":0.0,"base_kw":1.1,"household_size":5,
  "appliances":["fridge","lights","fan","tv","washer","geyser","ac","ac_night"],
  "appliance_details":[{"type":"ac","kw":1.5,"start":12,"end":18,"duty":0.7,"sensitivity":"cooling","flexible":false}],
  "temp_c":30.0,"cloud_cover":0.15 }
```
and expects within ~1.5 s: `{"pred_load": 0.92, "pred_solar": 0.0}` (kWh for that single hour). Fields beyond `node_id, day, hour, panel_kw, appliances` are optional context.
Surprise events are never included. If the agent errors or times out the engine falls back to its baseline forecaster, and `state.last.forecast_source` shows `"baseline"` instead of `"agent"`.

## 10. Quick test checklist
1. `GET /health` -> ok; open `/docs`.
2. `POST /step` a few times, then `GET /state` -> `last` is filled; `GET /ledger/B`, `GET /statement/B` return data.
3. `POST /nodes/B/appliances {"type":"workshop","kw":4,"start":10,"end":16}` then `GET /nodes/B` shows it.
4. `POST /scenario {"preset":"heatwave"}`, step, and watch `summary.demand_met_by_p2p_pct` and `history[].load` change.
5. `POST /scenario {"outage":true}` -> next slot has `grid_import: 0` for every node.
6. From the Next.js app, `fetch("<BASE>/state")` works with no CORS error.
