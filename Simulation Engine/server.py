"""
server.py - FastAPI wrapper around the engine. The website (Section 3) and the dashboard talk only to these endpoints.

Run:  uvicorn server:app --port 8000        dashboard: http://localhost:8000      API docs: http://localhost:8000/docs
Env:  DB_BACKEND=sqlite|dynamodb  AWS_REGION  FORECAST_URL  READINGS_CSV  ADMIN_TOKEN  (see DOCKER.md / README.md)
If ADMIN_TOKEN is set, every POST/PATCH/DELETE must send header  X-Admin-Token: <token>  (reads stay open).
"""
import asyncio, copy, csv, io, os, threading, traceback
from contextlib import asynccontextmanager
from typing import Any, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import appliances as ap
import db
from engine import (DEFAULT_SCENARIO, DEFAULT_SETTINGS, MODE_NAMES, PRESETS, Engine, compare_modes,
                    load_csv_source)

SOURCE = load_csv_source(os.environ["READINGS_CSV"]) if os.environ.get("READINGS_CSV") else None


def admin(x_admin_token: Optional[str] = Header(default=None)):
    token = os.environ.get("ADMIN_TOKEN")
    if token and x_admin_token != token:
        raise HTTPException(401, "admin token required (header X-Admin-Token)")


class Sim:
    def __init__(self):
        self.lock = threading.RLock()
        self.running, self.speed, self.last, self.error = False, 1.0, None, None
        self.events, self.restored = [], False
        state = None
        try:
            state = db.load_config()
            self.engine = Engine.from_state(state, SOURCE) if state else Engine(source=SOURCE)
            self.restored = bool(state)
        except Exception:                                  # unreadable / incompatible saved state -> start clean
            traceback.print_exc()
            self.engine = Engine(source=SOURCE)
        if self.restored:
            self.events.append(dict(day=self.engine.day, hour=self.engine.hour,
                                    text="Engine restarted: houses, appliances, settings and clock restored from the database"))

    def save(self):
        db.save_config(self.engine.to_state())

    def tick(self):
        with self.lock:
            e = self.engine
            res = e.step()
            s = res["slot"]
            ev_rows = [dict(day=s["day"], hour=s["hour"], text=t) for t in res["events"]]
            db.insert_ledger(list(e.ledger)); db.insert_meter(list(e.meter_log)); db.insert_events(ev_rows)
            e.ledger.clear(); e.meter_log.clear()           # the database holds history; keep memory small
            self.events = (self.events + ev_rows)[-30:]
            self.last = res
            self.save()
            return res

    def reset(self, mode=None, defaults=False):
        with self.lock:
            self.running, self.error = False, None
            if defaults:
                self.engine = Engine(mode=mode or "hybrid", source=SOURCE)
            else:
                self.engine.reset_clock()
                if mode: self.engine.set_mode(mode)
            db.reset()
            self.last, self.events = None, []
            self.save()


sim = Sim()


def guarded(fn, *args, **kwargs):
    """Run an engine mutation under the lock, persist, and translate errors to HTTP 404/400."""
    with sim.lock:
        try:
            out = fn(*args, **kwargs)
        except KeyError as e:
            raise HTTPException(404, str(e.args[0]))
        except (ValueError, TypeError) as e:
            raise HTTPException(400, str(e))
        sim.save()
        return out


async def loop():
    while True:
        if sim.running:
            try:
                await asyncio.to_thread(sim.tick)
            except Exception as e:                          # show the problem instead of dying silently
                traceback.print_exc()
                sim.running, sim.error = False, f"{type(e).__name__}: {e}"
            await asyncio.sleep(max(0.05, 1.0 / sim.speed))
        else:
            await asyncio.sleep(0.2)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(loop())
    yield
    task.cancel()


app = FastAPI(title="P2P Energy Engine", version="2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------------ request bodies
class NodeIn(BaseModel):
    id: Optional[str] = None
    panel_kw: float = 0.0
    battery_kwh: float = 0.0
    household_size: int = 4
    feeder: str = "Feeder-1"
    ac: str = "night"                                   # none / night / day / both (used when appliances is omitted)
    appliances: Optional[List[Any]] = None              # list of catalog types ("ac") or dicts ({"type":"ev","kw":7})


class NodePatch(BaseModel):
    panel_kw: Optional[float] = None
    battery_kwh: Optional[float] = None
    household_size: Optional[int] = None
    feeder: Optional[str] = None


class ApplianceIn(BaseModel):
    type: str = "custom"
    name: Optional[str] = None
    kw: Optional[float] = None
    start: Optional[int] = None
    end: Optional[int] = None
    duty: Optional[float] = None
    days: Optional[str] = None
    sensitivity: Optional[str] = None
    flexible: Optional[bool] = None
    duration_h: Optional[int] = None
    enabled: Optional[bool] = None


class AppliancePatch(BaseModel):
    name: Optional[str] = None
    kw: Optional[float] = None
    start: Optional[int] = None
    end: Optional[int] = None
    duty: Optional[float] = None
    days: Optional[str] = None
    sensitivity: Optional[str] = None
    flexible: Optional[bool] = None
    duration_h: Optional[int] = None
    enabled: Optional[bool] = None


class EventIn(BaseModel):
    kw: float
    hours: int = 1
    surprise: bool = True                               # True: the forecast agent is NOT told about it
    name: Optional[str] = None


class ScenarioIn(BaseModel):
    preset: Optional[str] = None                        # clear / heatwave / monsoon / winter / outage / restore
    temp_c: Optional[float] = None
    cloud_cover: Optional[float] = None
    outage: Optional[bool] = None


class SettingsIn(BaseModel):
    feed_in: Optional[float] = None
    retail: Optional[float] = None
    grid_fee: Optional[float] = None
    dynamic_price: Optional[bool] = None
    beta: Optional[float] = None
    policy: Optional[str] = None
    co2_factor: Optional[float] = None


# ------------------------------------------------------------------ helpers
def describe_node(n):
    e, temp = sim.engine, sim.engine.scenario["temp_c"]
    d = n.to_dict()
    for a in d["appliances"]:
        a["daily_kwh"] = round(sum(ap.expected_kw(a, e.day, h, temp) for h in range(24)), 2)
    d["expected_daily_load_kwh"] = round(sum(n.expected_load(e.day, h, temp) for h in range(24)), 2)
    d["expected_daily_solar_kwh"] = round(sum(n.panel_kw * __import__("forecast").solar_shape(h) *
                                              __import__("forecast").solar_factor(e.scenario["cloud_cover"]) * 0.95
                                              for h in range(24)), 2)
    return d


def pending_events():
    e, slot, out = sim.engine, sim.engine.day * 24 + sim.engine.hour, {}
    for n in e.nodes:
        for a in n.appliances:
            o = a.get("once")
            if o and o["day"] * 24 + o["hour"] >= slot:
                out[n.id] = round(out.get(n.id, 0.0) + a["kw"], 2)
    return out


def clean_config(state):
    st = copy.deepcopy(state)
    for k in ("stats", "day", "hour"): st.pop(k, None)
    for nd in st["nodes"]:
        nd.pop("soc", None)
        nd["appliances"] = [a for a in nd["appliances"] if not a.get("once")]
        for a in nd["appliances"]: a.pop("sched", None); a.pop("sched_day", None)
    st["version"] = 2
    return st


# ------------------------------------------------------------------ control
@app.get("/health")
def health():
    return {"ok": True, "db_backend": db.BACKEND, "running": sim.running, "version": app.version}

@app.post("/start", dependencies=[Depends(admin)])
def start(): sim.error = None; sim.running = True; return {"running": True}

@app.post("/pause", dependencies=[Depends(admin)])
def pause(): sim.running = False; return {"running": False}

@app.post("/step", dependencies=[Depends(admin)])
def step(): return sim.tick()                                   # advance exactly one hour

@app.post("/speed", dependencies=[Depends(admin)])
def speed(value: float = 1.0):
    sim.speed = min(max(value, 0.1), 20); return {"speed": sim.speed}

@app.post("/mode", dependencies=[Depends(admin)])
def mode(name: str): guarded(sim.engine.set_mode, name); return {"mode": name}

@app.post("/inject", dependencies=[Depends(admin)])
def inject(node: str, kwh: float = 3.0):
    """Sudden extra load at a node in the NEXT slot (one hour, surprise: the agent is not told)."""
    guarded(sim.engine.add_event, node, kwh, 1, True, "Sudden load")
    return {"queued": pending_events()}

@app.post("/reset", dependencies=[Depends(admin)])
def reset(mode: Optional[str] = None, defaults: bool = False):
    """Clears history and the clock. Keeps your houses/appliances unless defaults=true (restores the 10-home demo)."""
    sim.reset(mode, defaults); return {"ok": True}


# ------------------------------------------------------------------ community editing
@app.get("/catalog")
def catalog():
    return dict(appliances=ap.CATALOG, days=list(ap.DAYS), sensitivity=list(ap.SENS), ac_options=["none", "night", "day", "both"])

@app.get("/nodes")
def nodes():
    with sim.lock: return [describe_node(n) for n in sim.engine.nodes]

@app.get("/nodes/{node_id}")
def node(node_id: str):
    with sim.lock:
        try: return describe_node(sim.engine.get_node(node_id))
        except KeyError as e: raise HTTPException(404, str(e.args[0]))

@app.post("/nodes", dependencies=[Depends(admin)])
def add_node(body: NodeIn):
    n = guarded(sim.engine.add_node, **body.model_dump())
    return describe_node(n)

@app.patch("/nodes/{node_id}", dependencies=[Depends(admin)])
def patch_node(node_id: str, body: NodePatch):
    n = guarded(sim.engine.update_node, node_id, **body.model_dump(exclude_none=True))
    return describe_node(n)

@app.delete("/nodes/{node_id}", dependencies=[Depends(admin)])
def delete_node(node_id: str):
    guarded(sim.engine.remove_node, node_id); return {"deleted": node_id}

@app.post("/nodes/{node_id}/appliances", dependencies=[Depends(admin)])
def add_appliance(node_id: str, body: ApplianceIn):
    return guarded(sim.engine.add_appliance, node_id, **body.model_dump(exclude_none=True))

@app.patch("/nodes/{node_id}/appliances/{aid}", dependencies=[Depends(admin)])
def patch_appliance(node_id: str, aid: str, body: AppliancePatch):
    return guarded(sim.engine.update_appliance, node_id, aid, **body.model_dump(exclude_none=True))

@app.post("/nodes/{node_id}/appliances/{aid}/toggle", dependencies=[Depends(admin)])
def toggle_appliance(node_id: str, aid: str):
    with sim.lock:
        try: _, _, a = sim.engine.get_appliance(node_id, aid)
        except KeyError as e: raise HTTPException(404, str(e.args[0]))
        return guarded(sim.engine.update_appliance, node_id, aid, enabled=not a.get("enabled", True))

@app.delete("/nodes/{node_id}/appliances/{aid}", dependencies=[Depends(admin)])
def delete_appliance(node_id: str, aid: str):
    guarded(sim.engine.remove_appliance, node_id, aid); return {"deleted": aid}

@app.post("/nodes/{node_id}/events", dependencies=[Depends(admin)])
def add_event(node_id: str, body: EventIn):
    """Temporary extra load starting next hour for `hours` hours (EV arrives, party, welding job...)."""
    a = guarded(sim.engine.add_event, node_id, body.kw, body.hours, body.surprise, body.name)
    return dict(event=a, pending=pending_events())


# ------------------------------------------------------------------ scenario / settings / config
@app.get("/scenario")
def get_scenario(): return dict(scenario=sim.engine.scenario, presets={k: v for k, v in PRESETS.items()})

@app.post("/scenario", dependencies=[Depends(admin)])
def set_scenario(body: ScenarioIn):
    def apply():
        if body.preset: sim.engine.apply_preset(body.preset)
        sim.engine.set_scenario(body.temp_c, body.cloud_cover, body.outage)
    guarded(apply)
    return sim.engine.scenario

@app.get("/settings")
def get_settings(): return dict(settings=sim.engine.settings, mode=sim.engine.mode, defaults=DEFAULT_SETTINGS)

@app.post("/settings", dependencies=[Depends(admin)])
def set_settings(body: SettingsIn):
    guarded(sim.engine.set_settings, **body.model_dump(exclude_none=True))
    return sim.engine.settings

@app.get("/config")
def export_config():
    """Export the whole community (houses, appliances, scenario, settings, mode) as JSON."""
    with sim.lock: return clean_config(sim.engine.to_state())

@app.post("/config", dependencies=[Depends(admin)])
def import_config(state: dict):
    """Replace the community with an exported config. History and the clock are cleared."""
    def apply():
        if not state.get("nodes"): raise ValueError("config needs a non-empty 'nodes' list")
        st, seen = dict(state), set()
        st["nodes"] = []
        for nd in state["nodes"]:
            if "id" not in nd: raise ValueError("every node needs an id")
            if nd["id"] in seen: raise ValueError(f"duplicate node id '{nd['id']}'")
            seen.add(nd["id"])
            nd = dict(nd)
            apps = []
            for a in nd.get("appliances") or []:
                if isinstance(a, str): a = {"type": a}
                keep = {k: v for k, v in a.items() if k not in ("type", "id", "sched", "sched_day", "once", "label")}
                full = ap.make_appliance(a.get("type", "custom"), **keep)      # fills defaults + validates
                if a.get("id"): full["id"] = str(a["id"])
                apps.append(full)
            nd["appliances"] = apps if nd.get("appliances") is not None else ap.default_appliances(nd.get("household_size", 4))
            nd.pop("soc", None)
            st["nodes"].append(nd)
        st.update(day=0, hour=0, stats=None)
        eng = Engine.from_state(st, SOURCE)
        eng.reset_clock()
        sim.engine, sim.running, sim.last, sim.events = eng, False, None, []
        db.reset()
    guarded(apply)
    return {"ok": True, "nodes": [n.id for n in sim.engine.nodes]}


# ------------------------------------------------------------------ read
@app.get("/state")
def state():
    with sim.lock:
        e = sim.engine
        return dict(running=sim.running, error=sim.error, speed=sim.speed, mode=e.mode, day=e.day, hour=e.hour,
                    pending=pending_events(), last=sim.last, events=sim.events[-12:], history=e.history[-72:],
                    summary=e.summary(), scenario=e.scenario, settings=e.settings,
                    auth_required=bool(os.environ.get("ADMIN_TOKEN")), db_backend=db.BACKEND, restored=sim.restored,
                    tariff=dict(feed_in=e.settings["feed_in"], retail=e.settings["retail"], grid_fee=e.settings["grid_fee"]),
                    nodes=[n.brief() for n in e.nodes])

@app.get("/compare")
def compare(days: int = 3):
    with sim.lock: st = sim.engine.to_state()
    return compare_modes(st, min(max(days, 1), 7), SOURCE)

@app.get("/ledger/{node}")
def ledger(node: str, limit: int = 48):
    """User-facing ledger: units only for the discom part; P2P units + money for the P2P part."""
    keep = ("day", "hour", "load", "solar", "grid_import", "grid_export", "p2p_bought", "p2p_sold", "soc",
            "p2p_earned_rs", "p2p_owed_rs", "unserved", "benefit_rs")
    return [{k: r.get(k, 0) for k in keep} for r in db.meter_rows(node, limit)]

@app.get("/statement/{node}")
def statement(node: str):
    """Monthly-style statement: units reassigned on the discom bill + wallet settlement + savings."""
    t = db.statement_totals(node)
    return dict(node=node, **t, net_wallet_rs=round(t["p2p_earned_rs"] - t["p2p_owed_rs"], 2),
                note="P2P units are reassigned on the discom bill (virtual net metering); money settles "
                     "between users via the platform wallet; the discom receives the per-unit grid fee.")

@app.get("/ledger_all")
def ledger_all(limit: int = 100): return db.ledger_all(limit)

@app.get("/events")
def events(): return db.events(50)


def _csv(rows, name):
    if not rows: return Response("no data yet\n", media_type="text/plain")
    buf = io.StringIO(); w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    w.writeheader(); w.writerows(rows)
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})

@app.get("/export/ledger.csv")
def export_ledger(limit: int = 5000): return _csv(db.ledger_all(limit), "p2p_ledger.csv")

@app.get("/export/meter.csv")
def export_meter(node: Optional[str] = None, limit: int = 5000):
    ids = [node] if node else [n.id for n in sim.engine.nodes]
    return _csv([r for i in ids for r in db.meter_rows(i, limit)], "meter_log.csv")


# ------------------------------------------------------------------ dashboard
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def index(): return FileResponse("static/index.html")
