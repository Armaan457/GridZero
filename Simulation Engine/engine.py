"""
engine.py - P2P Energy Matching & Dispatch Engine (Section 2 core).

Each simulated hour (one "slot") the engine:
  1. PLAN     - asks the forecast agent what every home will load / generate -> planned allocation
  2. READ     - reads every home's virtual smart meter (appliance loads + solar + weather + surprise events)
  3. CLASSIFY - supplier (solar surplus or spare battery) / buyer (unmet need) / neutral
  4. MATCH    - shares the pool among buyers (Static / Dynamic / Hybrid), per feeder
  5. SETTLE   - ledger rows (price, grid fee, savings), battery charging with unsold surplus,
                discom import/export (or blackout + islanding during a grid outage)
Energy is not physically routed: it is a virtual allocation of exports to imports in the same feeder
and the same hour (virtual-net-metering style).
"""
import copy, csv, random, re
import appliances as ap
import forecast
from allocators import static_alloc, dynamic_alloc, hybrid_alloc, EPS

MODE_NAMES = ("static", "dynamic", "hybrid")
DEFAULT_SETTINGS = dict(feed_in=3.0, retail=8.0, grid_fee=0.5, dynamic_price=True, beta=0.5,
                        policy="smallest_first", co2_factor=0.82)   # Rs/kWh, kg CO2 per kWh (assumptions - tune)
DEFAULT_SCENARIO = dict(temp_c=30.0, cloud_cover=0.15, outage=False)
PRESETS = {
    "clear":    dict(temp_c=30.0, cloud_cover=0.10, outage=False),
    "heatwave": dict(temp_c=41.0, cloud_cover=0.05, outage=False),
    "monsoon":  dict(temp_c=27.0, cloud_cover=0.80, outage=False),
    "winter":   dict(temp_c=14.0, cloud_cover=0.15, outage=False),
    "outage":   dict(outage=True),
    "restore":  dict(outage=False),
}


class Node:
    def __init__(self, id, panel_kw=0.0, battery_kwh=0.0, household_size=4, feeder="Feeder-1",
                 appliances=None, soc=None, seed=None):
        self.id, self.panel_kw, self.cap = str(id), float(panel_kw), float(battery_kwh)
        self.household_size, self.feeder = int(household_size), feeder
        self.appliances = appliances if appliances is not None else ap.default_appliances(self.household_size)
        self.soc = self.cap * 0.5 if soc is None else min(float(soc), self.cap)
        self.rng = random.Random(seed if seed is not None else sum((i + 1) * ord(c) for i, c in enumerate(self.id)))

    @property
    def rate(self): return self.cap * 0.5          # max kWh charged / discharged per hour
    @property
    def reserve(self): return self.cap * 0.2       # never sell below 20 %

    def expected_load(self, day, hour, temp_c, skip_flexible=False, include_surprise=True):
        t = ap.STANDBY_KW
        for a in self.appliances:
            if a.get("once") and a.get("surprise") and not include_surprise: continue
            t += ap.expected_kw(a, day, hour, temp_c, skip_flexible)
        return t

    def read(self, day, hour, ctx, source=None):
        """Virtual smart-meter reading (kWh in this hour): (load, solar)."""
        temp, cloud = ctx["temp_c"], ctx["cloud_cover"]
        if source and (self.id, hour) in source:                   # optional real dataset for the base load
            load = source[(self.id, hour)][0] * self.rng.uniform(0.95, 1.05)
            load += sum(ap.expected_kw(a, day, hour, temp) for a in self.appliances if a.get("once"))
        else:
            load = ap.STANDBY_KW * self.rng.uniform(0.8, 1.2)
            for a in self.appliances:
                e = ap.expected_kw(a, day, hour, temp)
                load += e if a.get("once") else e * self.rng.uniform(0.9, 1.1)
        solar = self.panel_kw * forecast.solar_shape(hour) * forecast.solar_factor(cloud) * self.rng.uniform(0.9, 1.0)
        return round(load, 3), round(solar, 3)

    def to_dict(self):
        return dict(id=self.id, panel_kw=self.panel_kw, battery_kwh=self.cap, household_size=self.household_size,
                    feeder=self.feeder, soc=round(self.soc, 4), appliances=copy.deepcopy(self.appliances))

    def brief(self):
        return dict(id=self.id, panel_kw=self.panel_kw, battery_kwh=self.cap, soc=round(self.soc, 2),
                    feeder=self.feeder, household_size=self.household_size, n_appliances=len(self.appliances))


def load_csv_source(path):
    """CSV columns: node_id,hour,load_kwh[,solar_kwh]  (typical day per node). Returns {(node,hour):(load,solar)}."""
    out = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            out[(r["node_id"], int(r["hour"]))] = (float(r["load_kwh"]), float(r.get("solar_kwh") or 0))
    return out


def new_stats():
    return dict(supply=0.0, demand=0.0, matched=0.0, load=0.0, solar=0.0, grid_in=0.0, grid_out=0.0, curtailed=0.0,
                unserved=0.0, fee=0.0, benefit=0.0, co2=0.0, nf=0, sf=0.0, sf2=0.0, nfull=0,
                abs_err_load=0.0, abs_err_solar=0.0, n_err=0, peak_grid=0.0, peak_base=0.0)


def make_nodes():
    flex_washer = ("washer", dict(flexible=True, start=8, end=17, duration_h=1))
    spec = [  # id, solar kW, battery kWh, household size, appliances
        ("A", 4.5, 8, 3, ["fridge", "lights", "fan", "tv", "laptop", "ac_night"]),
        ("B", 0.0, 0, 5, ["fridge", "lights", "fan", "tv", flex_washer, "geyser", "ac", "ac_night"]),
        ("C", 3.0, 0, 3, ["fridge", "lights", "fan", "tv", "laptop"]),
        ("D", 0.0, 0, 4, ["fridge", "lights", "fan", "tv", "geyser", "ac_night"]),
        ("E", 4.0, 8, 4, ["fridge", "lights", "fan", "tv", "washer", "ac_night", "ev"]),
        ("F", 0.0, 0, 6, ["fridge", "lights", "fan", "tv", flex_washer, "geyser", "ac", "ac_night", "induction"]),
        ("G", 2.0, 0, 3, ["fridge", "lights", "fan", "tv"]),
        ("H", 0.0, 0, 4, ["fridge", "lights", "fan", "tv", "ac", "geyser"]),
        ("I", 0.0, 0, 7, ["fridge", "lights", "fan", "tv", "washer", "geyser", "ac", "ac", "induction",
                          ("pump", dict(flexible=True, start=6, end=18, duration_h=1))]),
        ("J", 0.0, 0, 3, ["fridge", "lights", "fan", "tv", "laptop"]),
    ]
    return [Node(i, p, b, hs, appliances=[_mk(t) for t in apps]) for i, p, b, hs, apps in spec]


def _mk(item):
    if isinstance(item, str): return ap.make_appliance(item)
    if isinstance(item, (tuple, list)): return ap.make_appliance(item[0], **item[1])
    d = dict(item)
    return ap.make_appliance(d.pop("type", "custom"), **d)


class Engine:
    def __init__(self, nodes=None, mode="hybrid", settings=None, scenario=None, source=None):
        self.nodes = nodes if nodes is not None else make_nodes()
        self.mode = mode if mode in MODE_NAMES else "hybrid"
        self.settings = {**DEFAULT_SETTINGS, **(settings or {})}
        self.scenario = {**DEFAULT_SCENARIO, **(scenario or {})}
        self.source = source
        self.day, self.hour = 0, 0
        self.ledger, self.meter_log, self.history, self.notes = [], [], [], []
        self.st = new_stats()
        self.reschedule()

    # ---------------------------------------------------------------- state
    def to_state(self):
        return dict(day=self.day, hour=self.hour, mode=self.mode, settings=self.settings, scenario=self.scenario,
                    nodes=[n.to_dict() for n in self.nodes], stats=self.st)

    @classmethod
    def from_state(cls, s, source=None):
        nodes = [Node(n["id"], n.get("panel_kw", 0), n.get("battery_kwh", 0), n.get("household_size", 4),
                      n.get("feeder", "Feeder-1"), copy.deepcopy(n.get("appliances", [])), n.get("soc")) for n in s["nodes"]]
        e = cls(nodes, s.get("mode", "hybrid"), s.get("settings"), s.get("scenario"), source)
        e.day, e.hour = int(s.get("day", 0)), int(s.get("hour", 0))
        if s.get("stats"): e.st = {**new_stats(), **s["stats"]}
        e.reschedule()
        return e

    def reset_clock(self):
        """Back to day 0, empty history and stats; houses, appliances and settings are kept."""
        self.day, self.hour = 0, 0
        self.ledger, self.meter_log, self.history, self.notes = [], [], [], []
        self.st = new_stats()
        for n in self.nodes:
            n.soc = n.cap * 0.5
            n.appliances = [a for a in n.appliances if not a.get("once")]
            for a in n.appliances: a.pop("sched", None); a.pop("sched_day", None)
        self.reschedule()

    def ctx(self):
        return dict(temp_c=self.scenario["temp_c"], cloud_cover=self.scenario["cloud_cover"])

    # ---------------------------------------------------------------- policies
    def _alloc(self, pool, needs):
        s = self.settings
        if self.mode == "static": return static_alloc(pool, needs)
        if self.mode == "dynamic": return dynamic_alloc(pool, needs, s["policy"])
        return hybrid_alloc(pool, needs, s["beta"], s["policy"])

    def price(self, pool, need):
        s = self.settings
        lo, hi = s["feed_in"], s["retail"] - s["grid_fee"]
        if not s["dynamic_price"] or pool + need <= EPS: return round((lo + hi) / 2, 2)
        return round(lo + (hi - lo) * need / (need + pool), 2)        # scarce supply -> price rises

    # ---------------------------------------------------------------- flexible load scheduling
    def reschedule(self, day=None, from_hour=None):
        """Place each flexible appliance's run-hours where the community has the most (forecast) solar surplus."""
        day = self.day if day is None else day
        frm = self.hour if from_hour is None else from_hour
        ctx = self.ctx()
        score = [0.0] * 24
        for n in self.nodes:
            for h in range(24):
                solar = n.panel_kw * forecast.solar_shape(h) * forecast.solar_factor(ctx["cloud_cover"]) * 0.95
                score[h] += solar - n.expected_load(day, h, ctx["temp_c"], skip_flexible=True, include_surprise=False)
        flex = [(n, a) for n in self.nodes for a in n.appliances
                if a.get("flexible") and a.get("enabled", True) and not a.get("once")]
        for n, a in sorted(flex, key=lambda x: -x[1]["kw"]):
            old = a.get("sched", []) if a.get("sched_day") == day else []
            done = [h for h in old if h < frm]
            remaining = max(0, a["duration_h"] - len(done))
            cand = sorted((h for h in range(a["start"], a["end"]) if h >= frm and h not in done), key=lambda h: -score[h])
            pick = sorted(cand[:remaining])
            for h in pick: score[h] -= a["kw"]
            a["sched"], a["sched_day"] = sorted(done + pick), day

    # ---------------------------------------------------------------- forecast / plan
    def node_meta(self, n, day):
        ctx = self.ctx()
        det = [copy.deepcopy(a) for a in n.appliances if a.get("enabled", True) and not (a.get("once") and a.get("surprise"))]
        base = sum(ap.STANDBY_KW + sum(ap.expected_kw(a, day, h, ctx["temp_c"]) for a in det) for h in range(24)) / 24
        return dict(id=n.id, panel_kw=n.panel_kw, base_kw=round(base, 3), household_size=n.household_size,
                    appliances=[a["type"] for a in det], appliance_details=det)

    def plan(self, day, hour, ctx):
        preds, by_feeder = {}, {}
        for n in self.nodes:
            pl, ps, src = forecast.predict(self.node_meta(n, day), day, hour, ctx)
            preds[n.id] = (pl, ps, src)
            by_feeder.setdefault(n.feeder, []).append((n.id, ps - pl))
        planned = {}
        for feeder, items in by_feeder.items():
            needs = {i: -net for i, net in items if net < -EPS}
            pool = sum(net for _, net in items if net > EPS)
            planned.update(self._alloc(pool, needs) if needs and pool > EPS else {k: 0.0 for k in needs})
        return preds, planned

    def _expire(self, slot):
        for n in self.nodes:
            n.appliances = [a for a in n.appliances if not (
                a.get("once") and a["once"]["day"] * 24 + a["once"]["hour"] + a["once"]["hours"] <= slot)]

    # ---------------------------------------------------------------- one hourly slot
    def step(self):
        day, hour = self.day, self.hour
        slot = day * 24 + hour
        if hour == 0: self.reschedule(day, 0)
        self._expire(slot)
        ctx, S, st = self.ctx(), self.settings, self.st
        outage = self.scenario["outage"]
        preds, planned = self.plan(day, hour, ctx)
        events, self.notes = list(self.notes), []
        announce = {n.id: [a for a in n.appliances if a.get("once") and a.get("surprise")
                           and a["once"]["day"] * 24 + a["once"]["hour"] == slot] for n in self.nodes}
        if outage: events.append("GRID OUTAGE: no discom import/export; homes rely on solar, batteries and P2P")
        rows, matches = {}, []
        tot_pool = tot_need = tot_matched = 0.0

        for feeder in sorted({n.feeder for n in self.nodes}):
            group = [n for n in self.nodes if n.feeder == feeder]
            surplus, offers, needs, reading, info = {}, {}, {}, {}, {}
            for n in group:
                load, solar = n.read(day, hour, ctx, self.source)
                reading[n.id] = (load, solar)
                net, batt_self = solar - load, 0.0
                if net < 0 and n.cap:                                  # battery covers own load first
                    batt_self = min(-net, n.soc, n.rate)
                    n.soc -= batt_self
                    net += batt_self
                info[n.id] = batt_self
                if net > EPS: surplus[n.id] = net
                elif net < -EPS: needs[n.id] = -net
                elif n.cap:                                            # fully covered -> may sell spare battery
                    spare = min(n.rate - batt_self, n.soc - n.reserve)
                    if spare > EPS: offers[n.id] = spare
            sources = {**surplus, **offers}
            pool, need = sum(sources.values()), sum(needs.values())
            got = self._alloc(pool, needs) if needs and pool > EPS else {k: 0.0 for k in needs}
            matched, price = sum(got.values()), self.price(pool, need)
            sold_by = {s: 0.0 for s in sources}
            for buyer, kwh in got.items():
                if kwh <= EPS: continue
                for seller, s in sources.items():
                    part = kwh * s / pool
                    sold_by[seller] += part
                    matches.append(dict(seller=seller, buyer=buyer, kwh=round(part, 3)))
                    self.ledger.append(dict(day=day, hour=hour, seller=seller, buyer=buyer, kwh=round(part, 4),
                                            price=price, amount=round(part * price, 3),
                                            grid_fee=round(part * S["grid_fee"], 3), mode=self.mode,
                                            source="battery" if seller in offers else "solar"))
            for n in group:
                load, solar = reading[n.id]
                sold, bought = sold_by.get(n.id, 0.0), got.get(n.id, 0.0)
                leftover = surplus.get(n.id, 0.0) - sold if n.id in surplus else 0.0
                charge = 0.0
                if n.cap:
                    if n.id in offers: n.soc -= sold
                    if leftover > EPS:                                 # unsold surplus charges the battery
                        charge = min(leftover, n.cap - n.soc, n.rate)
                        n.soc += charge
                rest = max(0.0, leftover - charge)
                unmet = max(0.0, needs.get(n.id, 0.0) - bought)
                grid_import, unserved = (0.0, unmet) if outage else (unmet, 0.0)
                grid_export, curtailed = (0.0, rest) if outage else (rest, 0.0)
                pl, ps, src = preds[n.id]
                st["abs_err_load"] += abs(pl - load); st["abs_err_solar"] += abs(ps - solar); st["n_err"] += 1
                role = "supplier" if n.id in sources else ("buyer" if n.id in needs else "neutral")
                benefit = bought * (S["retail"] - price - S["grid_fee"]) + sold * (price - S["feed_in"])
                rows[n.id] = dict(day=day, hour=hour, node=n.id, load=load, solar=solar, role=role,
                                  pred_load=pl, pred_solar=ps, planned_p2p=round(planned.get(n.id, 0.0), 3),
                                  p2p_bought=round(bought, 4), p2p_sold=round(sold, 4),
                                  grid_import=round(grid_import, 4), grid_export=round(grid_export, 4),
                                  batt_charge=round(charge, 4), soc=round(n.soc, 3), feeder=n.feeder,
                                  p2p_earned_rs=round(sold * price, 3), p2p_owed_rs=round(bought * price, 3),
                                  grid_fee_rs=round(bought * S["grid_fee"], 3), unserved=round(unserved, 4),
                                  curtailed=round(curtailed, 4), benefit_rs=round(benefit, 3))
                st["load"] += load; st["solar"] += solar; st["benefit"] += benefit
                st["unserved"] += unserved; st["curtailed"] += curtailed
                if needs.get(n.id, 0) > EPS:
                    r = bought / needs[n.id]
                    st["nf"] += 1; st["sf"] += r; st["sf2"] += r * r; st["nfull"] += 1 if r > 0.999 else 0
                for a in announce[n.id]:
                    events.append(f"Sudden +{a['kw']:.1f} kW load '{a['name']}' at {n.id}: agent planned P2P "
                                  f"{planned.get(n.id, 0.0):.2f} kWh, actual need {needs.get(n.id, 0):.2f} kWh -> P2P served "
                                  f"{bought:.2f} kWh, " + (f"UNSERVED {unserved:.2f} kWh (outage)" if outage
                                                           else f"discom grid {grid_import:.2f} kWh"))
            tot_pool += pool; tot_need += need; tot_matched += matched
            st["fee"] += matched * S["grid_fee"]

        self.meter_log.extend(rows.values())
        gi = sum(r["grid_import"] for r in rows.values()); go = sum(r["grid_export"] for r in rows.values())
        st["supply"] += tot_pool; st["demand"] += tot_need; st["matched"] += tot_matched
        st["grid_in"] += gi; st["grid_out"] += go; st["co2"] += tot_matched * S["co2_factor"]
        st["peak_grid"] = max(st["peak_grid"], gi); st["peak_base"] = max(st["peak_base"], tot_need)
        slot_row = dict(day=day, hour=hour, supply=round(tot_pool, 3), demand=round(tot_need, 3),
                        matched=round(tot_matched, 3), grid_import=round(gi, 3), price=self.price(tot_pool, tot_need),
                        planned_matched=round(sum(planned.values()), 3), load=round(sum(r["load"] for r in rows.values()), 3),
                        solar=round(sum(r["solar"] for r in rows.values()), 3),
                        unserved=round(sum(r["unserved"] for r in rows.values()), 3))
        self.history.append(slot_row)
        self.history = self.history[-240:]
        self.hour += 1
        if self.hour == 24: self.hour, self.day = 0, self.day + 1
        return dict(slot=slot_row, mode=self.mode, nodes=list(rows.values()), matches=matches, events=events,
                    scenario=dict(self.scenario), forecast_source=next(iter(preds.values()))[2] if preds else "baseline")

    # ---------------------------------------------------------------- editing the community (all safe at runtime)
    def get_node(self, node_id):
        for n in self.nodes:
            if n.id == node_id: return n
        raise KeyError(f"unknown node '{node_id}'")

    def get_appliance(self, node_id, aid):
        n = self.get_node(node_id)
        for i, a in enumerate(n.appliances):
            if a["id"] == aid: return n, i, a
        raise KeyError(f"unknown appliance '{aid}' on node {node_id}")

    def _next_id(self):
        used = {n.id for n in self.nodes}
        for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            if c not in used: return c
        i = 1
        while f"H{i}" in used: i += 1
        return f"H{i}"

    def add_node(self, id=None, panel_kw=0.0, battery_kwh=0.0, household_size=4, feeder="Feeder-1",
                 appliances=None, ac="night"):
        id = str(id).strip() if id else self._next_id()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,12}", id): raise ValueError("id must be 1-12 letters/digits/_/-")
        if any(n.id == id for n in self.nodes): raise ValueError(f"node '{id}' already exists")
        if not 0 <= panel_kw <= 100: raise ValueError("panel_kw must be 0..100")
        if not 0 <= battery_kwh <= 500: raise ValueError("battery_kwh must be 0..500")
        if not 1 <= household_size <= 30: raise ValueError("household_size must be 1..30")
        apps = ap.default_appliances(household_size, ac) if appliances is None else [_mk(x) for x in appliances]
        node = Node(id, panel_kw, battery_kwh, household_size, feeder or "Feeder-1", apps)
        self.nodes.append(node)
        self.notes.append(f"Home {id} joined the community ({panel_kw:g} kW solar, {battery_kwh:g} kWh battery)")
        self.reschedule()
        return node

    def update_node(self, node_id, panel_kw=None, battery_kwh=None, household_size=None, feeder=None):
        n = self.get_node(node_id)
        if panel_kw is not None:
            if not 0 <= panel_kw <= 100: raise ValueError("panel_kw must be 0..100")
            n.panel_kw = float(panel_kw)
        if battery_kwh is not None:
            if not 0 <= battery_kwh <= 500: raise ValueError("battery_kwh must be 0..500")
            was = n.cap
            n.cap = float(battery_kwh)
            n.soc = n.cap * 0.5 if was == 0 else min(n.soc, n.cap)
        if household_size is not None:
            if not 1 <= household_size <= 30: raise ValueError("household_size must be 1..30")
            n.household_size = int(household_size)
        if feeder: n.feeder = feeder
        self.reschedule()
        return n

    def remove_node(self, node_id):
        n = self.get_node(node_id)
        if len(self.nodes) <= 2: raise ValueError("keep at least 2 homes in the community")
        self.nodes.remove(n)
        self.notes.append(f"Home {node_id} left the community")
        self.reschedule()

    def add_appliance(self, node_id, type="custom", **over):
        n = self.get_node(node_id)
        a = ap.make_appliance(type, **over)
        n.appliances.append(a)
        self.notes.append(f"Home {node_id}: added load '{a['name']}' ({a['kw']:g} kW)")
        self.reschedule()
        return a

    def update_appliance(self, node_id, aid, **patch):
        n, i, a = self.get_appliance(node_id, aid)
        if a.get("once"): raise ValueError("event loads cannot be edited; delete and recreate")
        n.appliances[i] = ap.apply_patch(a, patch)
        self.reschedule()
        return n.appliances[i]

    def remove_appliance(self, node_id, aid):
        n, i, a = self.get_appliance(node_id, aid)
        n.appliances.pop(i)
        self.notes.append(f"Home {node_id}: removed load '{a['name']}'")
        self.reschedule()

    def add_event(self, node_id, kw, hours=1, surprise=True, name=None):
        """One-off extra load starting with the NEXT slot. surprise=True -> the forecast agent is not told."""
        n = self.get_node(node_id)
        a = ap.make_appliance("custom", name=name or "Sudden load", kw=kw, start=0, end=24, duty=1.0,
                              surprise=bool(surprise))
        a["type"] = "event"
        a["once"] = dict(day=self.day, hour=self.hour, hours=int(hours))
        ap.validate(a)
        n.appliances.append(a)
        return a

    # ---------------------------------------------------------------- scenario / settings / mode
    def set_scenario(self, temp_c=None, cloud_cover=None, outage=None):
        if temp_c is not None:
            if not -10 <= temp_c <= 55: raise ValueError("temp_c must be -10..55")
        if cloud_cover is not None:
            if not 0 <= cloud_cover <= 1: raise ValueError("cloud_cover must be 0..1")
        if temp_c is not None and temp_c != self.scenario["temp_c"]:
            self.notes.append(f"Weather: temperature set to {temp_c:g} C")
        if cloud_cover is not None and cloud_cover != self.scenario["cloud_cover"]:
            self.notes.append(f"Weather: cloud cover set to {round(cloud_cover * 100)} %")
        if outage is not None and bool(outage) != self.scenario["outage"]:
            self.notes.append("Grid outage STARTED" if outage else "Grid restored")
        for k, v in dict(temp_c=temp_c, cloud_cover=cloud_cover, outage=outage).items():
            if v is not None: self.scenario[k] = bool(v) if k == "outage" else float(v)
        self.reschedule()

    def apply_preset(self, name):
        if name not in PRESETS: raise ValueError(f"preset must be one of {sorted(PRESETS)}")
        self.set_scenario(**PRESETS[name])

    def set_settings(self, **kw):
        s = {**self.settings, **{k: v for k, v in kw.items() if v is not None}}
        bad = set(kw) - set(DEFAULT_SETTINGS)
        if bad: raise ValueError(f"unknown settings {sorted(bad)}")
        if s["feed_in"] < 0 or s["grid_fee"] < 0: raise ValueError("feed_in and grid_fee must be >= 0")
        if s["retail"] - s["grid_fee"] <= s["feed_in"]: raise ValueError("need feed_in < retail - grid_fee")
        if not 0 <= s["beta"] <= 1: raise ValueError("beta must be 0..1")
        if s["policy"] not in ("smallest_first", "largest_first"): raise ValueError("policy must be smallest_first or largest_first")
        if not 0 <= s["co2_factor"] <= 2: raise ValueError("co2_factor must be 0..2")
        for k in ("feed_in", "retail", "grid_fee", "beta", "co2_factor"): s[k] = float(s[k])
        s["dynamic_price"] = bool(s["dynamic_price"])
        self.settings = s

    def set_mode(self, name):
        if name not in MODE_NAMES: raise ValueError(f"mode must be one of {list(MODE_NAMES)}")
        self.mode = name

    # ---------------------------------------------------------------- metrics
    def summary(self):
        s = self.st
        jain = (s["sf"] ** 2) / (s["nf"] * s["sf2"]) if s["nf"] and s["sf2"] > 0 else 0
        pct = lambda a, b: round(100 * a / b, 1) if b else 0
        return dict(mode=self.mode,
                    supply_used_pct=pct(s["matched"], s["supply"]),
                    demand_met_by_p2p_pct=pct(s["matched"], s["demand"]),
                    homes_fully_served_pct=pct(s["nfull"], s["nf"]),
                    fairness_jain=round(jain, 3), p2p_kwh=round(s["matched"], 2),
                    grid_import_kwh=round(s["grid_in"], 2), user_gain_rs=round(s["benefit"], 1),
                    discom_fee_rs=round(s["fee"], 1),
                    local_energy_share_pct=pct(s["load"] - s["grid_in"] - s["unserved"], s["load"]),
                    co2_avoided_kg=round(s["co2"], 2), unserved_kwh=round(s["unserved"], 2),
                    curtailed_kwh=round(s["curtailed"], 2),
                    grid_import_reduction_pct=pct(s["matched"], s["grid_in"] + s["matched"]),
                    peak_grid_kw=round(s["peak_grid"], 2),
                    forecast_mae_load=round(s["abs_err_load"] / s["n_err"], 3) if s["n_err"] else 0)


def compare_modes(state, days=3, source=None):
    """Run every mode on the CURRENT community (same seeds, fresh clock) and return the metrics table."""
    out = []
    for m in MODE_NAMES:
        st = copy.deepcopy(state)
        st.update(mode=m, day=0, hour=0, stats=None)
        for nd in st["nodes"]:
            nd["soc"] = None
            nd["appliances"] = [a for a in nd["appliances"] if not a.get("once")]
            for a in nd["appliances"]: a.pop("sched", None); a.pop("sched_day", None)
        e = Engine.from_state(st, source)
        for _ in range(days * 24): e.step()
        out.append(e.summary())
    return out


if __name__ == "__main__":
    e = Engine()
    for row in compare_modes(e.to_state()): print(row)
