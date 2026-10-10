"""
engine.py - P2P Energy Matching & Dispatch Engine (Section 2 core).

Each simulated hour (one "slot") the engine:
  1. PLAN    - asks the forecast agent what every node will load/generate and builds a planned allocation
  2. READ    - reads the (virtual) smart meter of every node  (actuals, with noise / sudden events)
  3. CLASSIFY- supplier (solar surplus or spare battery) / buyer (unmet need) / neutral
  4. MATCH   - shares the pool among buyers using Static / Dynamic / Hybrid policy (per feeder)
  5. SETTLE  - writes ledger rows (who bought from whom, price, discom grid fee), charges batteries
               with unsold surplus, sends the rest to / draws the rest from the discom grid
Energy is not physically "routed": it is a virtual allocation of grid exports to grid imports in the
same feeder and the same time slot (virtual-net-metering style).
"""
import csv, math, random
from allocators import MODES, EPS
import forecast

FEED_IN, RETAIL, GRID_FEE = 3.0, 8.0, 0.5       # Rs/kWh  (assumptions - replace with your state's tariff)


class Node:
    def __init__(self, id, panel_kw, base_kw, battery_kwh=0.0, household_size=4, appliances=None,
                 feeder="Feeder-1", seed=0):
        self.id, self.panel_kw, self.base_kw = id, panel_kw, base_kw
        self.household_size, self.appliances, self.feeder = household_size, appliances or [], feeder
        self.cap = battery_kwh
        self.rate = battery_kwh * 0.5            # max kWh charged/discharged per hour
        self.reserve = battery_kwh * 0.2         # never sell below 20 %
        self.soc = battery_kwh * 0.5
        self.rng = random.Random(seed)

    def meta(self):
        return dict(id=self.id, panel_kw=self.panel_kw, base_kw=self.base_kw,
                    household_size=self.household_size, appliances=self.appliances)

    def read(self, hour, boost=0.0, source=None):
        """Virtual smart-meter reading (kWh in this hour). `boost` = injected sudden load."""
        if source and (self.id, hour) in source:
            load, solar = source[(self.id, hour)]
            load *= self.rng.uniform(0.95, 1.05)
        else:
            load = self.base_kw * forecast.load_shape(hour) * self.rng.uniform(0.85, 1.15)
            solar = self.panel_kw * forecast.solar_shape(hour) * self.rng.uniform(0.7, 1.0)
        return round(load + boost, 3), round(solar, 3)


def load_csv_source(path):
    """CSV columns: node_id,hour,load_kwh,solar_kwh  (typical day per node). Returns {(node,hour):(load,solar)}."""
    out = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            out[(r["node_id"], int(r["hour"]))] = (float(r["load_kwh"]), float(r["solar_kwh"]))
    return out


def make_nodes():
    spec = [  # id, panel_kw, base_kw, battery_kwh, household_size, appliances
        ("A", 4.5, 0.5, 8, 3, ["fridge", "fan", "ac"]),
        ("B", 0.0, 1.4, 0, 5, ["ac", "geyser", "fridge"]),
        ("C", 3.0, 0.6, 0, 3, ["fridge", "fan"]),
        ("D", 0.0, 1.1, 0, 4, ["ac", "fridge"]),
        ("E", 4.0, 0.7, 8, 4, ["fridge", "ac"]),
        ("F", 0.0, 1.8, 0, 6, ["ac", "geyser", "washer"]),
        ("G", 2.0, 0.8, 0, 3, ["fridge", "fan"]),
        ("H", 0.0, 1.2, 0, 4, ["ac", "fridge"]),
        ("I", 0.0, 2.0, 0, 7, ["ac", "ac", "geyser"]),
        ("J", 0.0, 0.9, 0, 3, ["fridge", "fan"]),
    ]
    return [Node(i, p, b, bat, hs, ap, seed=k + 1) for k, (i, p, b, bat, hs, ap) in enumerate(spec)]


class Engine:
    def __init__(self, nodes=None, mode="hybrid", dynamic_price=True, source=None):
        self.nodes = nodes or make_nodes()
        self.mode, self.dynamic_price, self.source = mode, dynamic_price, source
        self.day, self.hour = 0, 0
        self.ledger, self.meter_log = [], []
        self.history = []                                   # per-slot totals for charts
        self.st = dict(supply=0.0, demand=0.0, matched=0.0, grid_in=0.0, grid_out=0.0,
                       fulfil=[], fee=0.0, gain=0.0, abs_err_load=0.0, abs_err_solar=0.0, n_err=0)

    # ---------- price ----------
    def price(self, pool, need):
        lo, hi = FEED_IN, RETAIL - GRID_FEE
        if not self.dynamic_price or pool + need <= EPS:
            return round((lo + hi) / 2, 2)
        ratio = need / (need + pool)                        # scarce supply -> price rises
        return round(lo + (hi - lo) * ratio, 2)

    # ---------- plan (forecast based) ----------
    def plan(self, day, hour):
        preds, needs, pool = {}, {}, 0.0
        for n in self.nodes:
            pl, ps, src = forecast.predict(n.meta(), day, hour)
            preds[n.id] = (pl, ps, src)
            net = ps - pl
            if net < -EPS: needs[n.id] = -net
            elif net > EPS: pool += net
        planned = MODES[self.mode](pool, needs) if needs and pool > EPS else {k: 0.0 for k in needs}
        return preds, planned, needs

    # ---------- one hourly slot ----------
    def step(self, boosts=None):
        boosts = boosts or {}
        day, hour = self.day, self.hour
        preds, planned, planned_need = self.plan(day, hour)
        rows, matches, events = {}, [], []
        tot_pool = tot_need = tot_matched = 0.0

        for feeder in sorted({n.feeder for n in self.nodes}):
            group = [n for n in self.nodes if n.feeder == feeder]
            surplus, offers, needs, reading, info = {}, {}, {}, {}, {}
            for n in group:
                load, solar = n.read(hour, boosts.get(n.id, 0.0), self.source)
                reading[n.id] = (load, solar)
                net, batt_self = solar - load, 0.0
                if net < 0 and n.cap:                       # battery covers own load first
                    batt_self = min(-net, n.soc, n.rate)
                    n.soc -= batt_self
                    net += batt_self
                info[n.id] = dict(batt_self=batt_self, net=net)
                if net > EPS:
                    surplus[n.id] = net
                elif net < -EPS:
                    needs[n.id] = -net
                elif n.cap:                                 # fully self-covered -> may sell spare battery
                    spare = min(n.rate - batt_self, n.soc - n.reserve)
                    if spare > EPS: offers[n.id] = spare
            sources = {**surplus, **offers}
            pool, need = sum(sources.values()), sum(needs.values())
            got = MODES[self.mode](pool, needs) if needs and pool > EPS else {k: 0.0 for k in needs}
            matched = sum(got.values())
            price = self.price(pool, need)
            sold_by = {s: 0.0 for s in sources}
            for buyer, kwh in got.items():
                if kwh <= EPS: continue
                for seller, s in sources.items():
                    part = kwh * s / pool
                    sold_by[seller] += part
                    matches.append(dict(seller=seller, buyer=buyer, kwh=round(part, 3)))
                    self.ledger.append(dict(day=day, hour=hour, seller=seller, buyer=buyer, kwh=round(part, 4),
                                            price=price, amount=round(part * price, 3),
                                            grid_fee=round(part * GRID_FEE, 3), mode=self.mode,
                                            source="battery" if seller in offers else "solar"))
            for n in group:
                load, solar = reading[n.id]
                sold, bought = sold_by.get(n.id, 0.0), got.get(n.id, 0.0)
                leftover = surplus.get(n.id, 0.0) - sold if n.id in surplus else 0.0
                charge = 0.0
                if n.cap:
                    if n.id in offers: n.soc -= sold         # battery energy actually sold
                    if leftover > EPS:                       # unsold surplus charges the battery
                        charge = min(leftover, n.cap - n.soc, n.rate)
                        n.soc += charge
                grid_export = max(0.0, leftover - charge)
                grid_import = max(0.0, needs.get(n.id, 0.0) - bought)
                pl, ps, src = preds[n.id]
                self.st["abs_err_load"] += abs(pl - load); self.st["abs_err_solar"] += abs(ps - solar); self.st["n_err"] += 1
                role = "supplier" if n.id in sources else ("buyer" if n.id in needs else "neutral")
                rows[n.id] = dict(day=day, hour=hour, node=n.id, load=load, solar=solar, role=role,
                                  pred_load=pl, pred_solar=ps, planned_p2p=round(planned.get(n.id, 0.0), 3),
                                  p2p_bought=round(bought, 4), p2p_sold=round(sold, 4),
                                  grid_import=round(grid_import, 4), grid_export=round(grid_export, 4),
                                  batt_charge=round(charge, 4), soc=round(n.soc, 3), feeder=n.feeder)
                if needs.get(n.id, 0) > EPS: self.st["fulfil"].append(bought / needs[n.id])
                if n.id in boosts:
                    events.append(f"Sudden +{boosts[n.id]:.1f} kWh load at {n.id}: agent planned P2P "
                                  f"{planned.get(n.id, 0.0):.2f} kWh, actual need {needs.get(n.id, 0):.2f} kWh -> "
                                  f"P2P served {bought:.2f} kWh, discom grid {grid_import:.2f} kWh")
            tot_pool += pool; tot_need += need; tot_matched += matched
            self.st["fee"] += matched * GRID_FEE

        self.meter_log.extend(rows.values())
        gi = sum(r["grid_import"] for r in rows.values()); go = sum(r["grid_export"] for r in rows.values())
        self.st["supply"] += tot_pool; self.st["demand"] += tot_need; self.st["matched"] += tot_matched
        self.st["grid_in"] += gi; self.st["grid_out"] += go
        self.st["gain"] += tot_matched * (RETAIL - FEED_IN - GRID_FEE)
        slot = dict(day=day, hour=hour, supply=round(tot_pool, 3), demand=round(tot_need, 3),
                    matched=round(tot_matched, 3), grid_import=round(gi, 3), price=self.price(tot_pool, tot_need),
                    planned_matched=round(sum(planned.values()), 3))
        self.history.append(slot)
        self.hour += 1
        if self.hour == 24: self.hour, self.day = 0, self.day + 1
        return dict(slot=slot, mode=self.mode, nodes=list(rows.values()), matches=matches, events=events,
                    forecast_source=next(iter(preds.values()))[2])

    def summary(self):
        s, f = self.st, self.st["fulfil"]
        jain = (sum(f) ** 2) / (len(f) * sum(x * x for x in f)) if f and sum(x * x for x in f) > 0 else 0
        return dict(mode=self.mode,
                    supply_used_pct=round(100 * s["matched"] / s["supply"], 1) if s["supply"] else 0,
                    demand_met_by_p2p_pct=round(100 * s["matched"] / s["demand"], 1) if s["demand"] else 0,
                    homes_fully_served_pct=round(100 * sum(1 for x in f if x > 0.999) / len(f), 1) if f else 0,
                    fairness_jain=round(jain, 3), p2p_kwh=round(s["matched"], 2),
                    grid_import_kwh=round(s["grid_in"], 2), user_gain_rs=round(s["gain"], 1),
                    discom_fee_rs=round(s["fee"], 1),
                    forecast_mae_load=round(s["abs_err_load"] / s["n_err"], 3) if s["n_err"] else 0)


def compare_modes(days=3):
    """Run every mode on identical data (same seeds) and return the metrics table."""
    out = []
    for m in MODES:
        e = Engine(make_nodes(), mode=m)
        for _ in range(days * 24): e.step()
        out.append(e.summary())
    return out


if __name__ == "__main__":
    for row in compare_modes(): print(row)
