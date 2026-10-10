"""
server.py - FastAPI wrapper around the engine. The website (Section 3) talks only to these endpoints.

Run:  uvicorn server:app --reload --port 8000        then open  http://localhost:8000
Docs: http://localhost:8000/docs   (auto-generated, handy for teammates)
"""
import asyncio, os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import db
from engine import Engine, make_nodes, compare_modes, load_csv_source, FEED_IN, RETAIL, GRID_FEE
from allocators import MODES

SOURCE = load_csv_source(os.environ["READINGS_CSV"]) if os.environ.get("READINGS_CSV") else None


class Sim:
    def __init__(self):
        self.reset()
        self.running, self.speed = False, 1.0           # speed = sim-hours per real second
        self.pending_boosts = {}
        self.last = None
        self.events = []

    def reset(self, mode="hybrid"):
        self.engine = Engine(make_nodes(), mode=mode, source=SOURCE)
        self.last, self.events, self.pending_boosts = None, [], {}
        db.reset()

    def tick(self):
        boosts, self.pending_boosts = self.pending_boosts, {}
        n_l, n_m = len(self.engine.ledger), len(self.engine.meter_log)
        res = self.engine.step(boosts)
        db.insert_many("ledger", self.engine.ledger[n_l:])
        db.insert_many("meter", self.engine.meter_log[n_m:])
        s = res["slot"]
        for e in res["events"]:
            self.events.append(dict(day=s["day"], hour=s["hour"], text=e))
        db.insert_many("events", [dict(day=s["day"], hour=s["hour"], text=e) for e in res["events"]])
        self.events = self.events[-30:]
        self.last = res
        return res


sim = Sim()


async def loop():
    while True:
        if sim.running:
            sim.tick()
            await asyncio.sleep(max(0.05, 1.0 / sim.speed))
        else:
            await asyncio.sleep(0.2)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(loop())
    yield
    task.cancel()


app = FastAPI(title="P2P Energy Engine", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------- control ----------
@app.post("/start")
def start(): sim.running = True; return {"running": True}

@app.post("/pause")
def pause(): sim.running = False; return {"running": False}

@app.post("/step")
def step(): return sim.tick()                                   # advance one hour manually

@app.post("/speed")
def speed(value: float = 1.0):
    sim.speed = min(max(value, 0.1), 20); return {"speed": sim.speed}

@app.post("/mode")
def mode(name: str):
    if name not in MODES: raise HTTPException(400, f"mode must be one of {list(MODES)}")
    sim.engine.mode = name; return {"mode": name}

@app.post("/inject")
def inject(node: str, kwh: float = 3.0):
    """Sudden demand at a node in the NEXT slot - the 'agent predicted no need but now there is' demo."""
    if node not in [n.id for n in sim.engine.nodes]: raise HTTPException(404, "unknown node")
    sim.pending_boosts[node] = sim.pending_boosts.get(node, 0.0) + kwh
    return {"queued": sim.pending_boosts}

@app.post("/reset")
def reset(mode: str = "hybrid"):
    sim.running = False; sim.reset(mode); return {"ok": True}


# ---------- read ----------
@app.get("/state")
def state():
    e = sim.engine
    return dict(running=sim.running, speed=sim.speed, mode=e.mode, day=e.day, hour=e.hour,
                pending=sim.pending_boosts, last=sim.last, events=sim.events[-12:],
                history=e.history[-72:], summary=e.summary(),
                tariff=dict(feed_in=FEED_IN, retail=RETAIL, grid_fee=GRID_FEE),
                nodes=[dict(id=n.id, panel_kw=n.panel_kw, base_kw=n.base_kw, battery_kwh=n.cap,
                            soc=round(n.soc, 2), feeder=n.feeder) for n in e.nodes])

@app.get("/compare")
def compare(days: int = 3):
    return compare_modes(min(max(days, 1), 7))

@app.get("/ledger/{node}")
def ledger(node: str, limit: int = 48):
    """User-facing ledger: units only for discom part; P2P units + money for P2P part."""
    rows = db.query("SELECT day,hour,load,solar,grid_import,grid_export,p2p_bought,p2p_sold,soc "
                    "FROM meter WHERE node=? ORDER BY day DESC, hour DESC LIMIT ?", (node, limit))
    out = []
    for r in rows:
        price = db.query("SELECT price FROM ledger WHERE day=? AND hour=? LIMIT 1", (r["day"], r["hour"]))
        p = price[0]["price"] if price else None
        r["p2p_earned_rs"] = round(r["p2p_sold"] * p, 2) if p else 0
        r["p2p_owed_rs"] = round(r["p2p_bought"] * p, 2) if p else 0
        out.append(r)
    return out[::-1]

@app.get("/statement/{node}")
def statement(node: str):
    """Monthly-style statement: units reassigned on the discom bill + wallet settlement."""
    sold = db.query("SELECT COALESCE(SUM(kwh),0) k, COALESCE(SUM(amount),0) a FROM ledger WHERE seller=?", (node,))[0]
    bought = db.query("SELECT COALESCE(SUM(kwh),0) k, COALESCE(SUM(amount),0) a, COALESCE(SUM(grid_fee),0) f "
                      "FROM ledger WHERE buyer=?", (node,))[0]
    m = db.query("SELECT COALESCE(SUM(grid_import),0) gi, COALESCE(SUM(grid_export),0) ge FROM meter WHERE node=?", (node,))[0]
    return dict(node=node, discom_import_kwh=round(m["gi"], 2), discom_export_kwh=round(m["ge"], 2),
                p2p_sold_kwh=round(sold["k"], 2), p2p_earned_rs=round(sold["a"], 2),
                p2p_bought_kwh=round(bought["k"], 2), p2p_owed_rs=round(bought["a"], 2),
                grid_fee_on_discom_bill_rs=round(bought["f"], 2),
                net_wallet_rs=round(sold["a"] - bought["a"], 2),
                note="P2P units are reassigned on the discom bill (virtual net metering); money settles "
                     "between users via the platform wallet; the discom receives the per-unit grid fee.")

@app.get("/ledger_all")
def ledger_all(limit: int = 100):
    return db.query("SELECT * FROM ledger ORDER BY day DESC, hour DESC LIMIT ?", (limit,))[::-1]

@app.get("/events")
def events(): return db.query("SELECT * FROM events ORDER BY rowid DESC LIMIT 50")


# ---------- dashboard ----------
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def index(): return FileResponse("static/index.html")
