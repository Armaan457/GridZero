const BASE = "/engine";

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
  day: number;
  hour: number;
  node: string;
  role: "supplier" | "buyer" | "neutral";
  feeder: string;
  load: number;
  solar: number;
  pred_load: number;
  pred_solar: number;
  planned_p2p: number;
  p2p_bought: number;
  p2p_sold: number;
  grid_import: number;
  grid_export: number;
  batt_charge: number;
  soc: number;
};

export type Slot = {
  day: number;
  hour: number;
  supply: number;
  demand: number;
  matched: number;
  grid_import: number;
  price: number;
  planned_matched: number;
};

export type StepResult = {
  slot: Slot;
  mode: string;
  forecast_source: "agent" | "baseline";
  nodes: NodeSlot[];
  matches: { seller: string; buyer: string; kwh: number }[];
  events: string[];
};

export type EngineState = {
  running: boolean;
  speed: number;
  mode: "static" | "dynamic" | "hybrid";
  day: number;
  hour: number;
  pending: Record<string, number>;
  tariff: { feed_in: number; retail: number; grid_fee: number };
  nodes: { id: string; panel_kw: number; base_kw: number; battery_kwh: number; soc: number; feeder: string }[];
  last: StepResult | null;
  events: { day: number; hour: number; text: string }[];
  history: Slot[];
  summary: Record<string, number | string>;
};

export type LedgerRow = {
  day: number;
  hour: number;
  load: number;
  solar: number;
  grid_import: number;
  grid_export: number;
  p2p_bought: number;
  p2p_sold: number;
  soc: number;
  p2p_earned_rs: number;
  p2p_owed_rs: number;
};

export type Statement = {
  node: string;
  discom_import_kwh: number;
  discom_export_kwh: number;
  p2p_sold_kwh: number;
  p2p_earned_rs: number;
  p2p_bought_kwh: number;
  p2p_owed_rs: number;
  grid_fee_on_discom_bill_rs: number;
  net_wallet_rs: number;
  note: string;
};

export type CompareRow = Record<string, number | string>;

export const NODES = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"] as const;

export const engine = {
  state: () => get<EngineState>("/state"),
  ledger: (node: string, limit = 48) => get<LedgerRow[]>(`/ledger/${node}?limit=${limit}`),
  statement: (node: string) => get<Statement>(`/statement/${node}`),
  compare: (days = 3) => get<CompareRow[]>(`/compare?days=${days}`),
  ledgerAll: (limit = 100) => get<unknown[]>(`/ledger_all?limit=${limit}`),
  events: () => get<{ day: number; hour: number; text: string }[]>("/events"),
  start: () => post<{ running: boolean }>("/start"),
  pause: () => post<{ running: boolean }>("/pause"),
  step: () => post<StepResult>("/step"),
  speed: (v: number) => post<{ speed: number }>(`/speed?value=${v}`),
  mode: (m: string) => post<{ mode: string }>(`/mode?name=${m}`),
  inject: (node: string, kwh = 3) => post<{ queued: Record<string, number> }>(`/inject?node=${node}&kwh=${kwh}`),
  reset: (mode = "hybrid") => post<{ ok: boolean }>(`/reset?mode=${mode}`),
};

export function kwh(n: number | undefined | null) {
  if (n == null || Number.isNaN(n)) return "—";
  return `${n.toFixed(2)} kWh`;
}

export function rs(n: number | undefined | null) {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : n < 0 ? "−" : "";
  return `${sign} ₹${Math.abs(n).toFixed(2)}`;
}

export function slotLabel(day: number, hour: number) {
  return `D${day} ${String(hour).padStart(2, "0")}:00`;
}
