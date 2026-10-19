"""
test_features.py - end-to-end checks of every engine feature through the real API (SQLite, fresh database).
Run:  pip install httpx && python test_features.py
"""
import os, sys, tempfile, importlib

def fresh(admin_token=None, backend="sqlite"):
    for m in ("db", "db_sqlite", "db_dynamo", "server", "engine", "forecast", "appliances"):
        sys.modules.pop(m, None)
    os.environ["DB_BACKEND"] = backend
    os.environ["SQLITE_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
    os.environ.pop("ADMIN_TOKEN", None)
    if admin_token: os.environ["ADMIN_TOKEN"] = admin_token
    from fastapi.testclient import TestClient
    import server
    return TestClient(server.app), server

ok = lambda cond, msg: (print(("PASS " if cond else "FAIL ") + msg), cond)[1]
results = []
def check(cond, msg): results.append(ok(cond, msg))

c, server = fresh()
check(c.get("/health").json()["ok"], "health endpoint")
cat = c.get("/catalog").json()
check("ev" in cat["appliances"] and "ac" in cat["appliances"], "catalog lists appliance types")
nodes = c.get("/nodes").json()
check(len(nodes) == 10 and all("expected_daily_load_kwh" in n for n in nodes), "10 demo homes with expected daily load")

# --- run a day, energy accounting sanity
for _ in range(24): c.post("/step")
s = c.get("/state").json()
check(s["day"] == 1 and s["hour"] == 0, "clock advanced 24 hours")
last = s["last"]["nodes"]
check(all(abs(r["p2p_bought"]) <= r["load"] + 1e-6 for r in last), "nobody buys more than their load")
tot_sold = sum(r["p2p_sold"] for r in last); tot_bought = sum(r["p2p_bought"] for r in last)
check(abs(tot_sold - tot_bought) < 1e-3, "units sold == units bought (this slot)")

# --- add a house with custom appliances
r = c.post("/nodes", json={"id": "K", "panel_kw": 6, "battery_kwh": 10, "household_size": 5,
                           "appliances": ["fridge", "lights", {"type": "ev", "kw": 7.2, "duration_h": 4}]})
check(r.status_code == 200 and r.json()["id"] == "K", "add house K with EV 7.2 kW")
check(c.post("/nodes", json={"id": "K"}).status_code == 400, "duplicate house id rejected")
check(c.post("/nodes", json={"id": "bad id!"}).status_code == 400, "invalid house id rejected")
ev = [a for a in r.json()["appliances"] if a["type"] == "ev"][0]
check(ev["flexible"] and len(ev["sched"]) == 4, "flexible EV got 4 scheduled hours")
solar_hours = set(range(8, 17))
check(len(set(ev["sched"]) & solar_hours) >= 3, f"EV scheduled mostly in solar hours: {ev['sched']}")

# --- add / edit / toggle / delete an appliance
r = c.post("/nodes/B/appliances", json={"type": "workshop", "kw": 4.0, "start": 10, "end": 16})
aid = r.json()["id"]
check(r.status_code == 200, "add custom workshop load to B")
r = c.patch(f"/nodes/B/appliances/{aid}", json={"kw": 5.5, "duty": 0.9})
check(r.json()["kw"] == 5.5, "edit appliance kW")
check(c.patch(f"/nodes/B/appliances/{aid}", json={"kw": -3}).status_code == 400, "invalid kW rejected")
check(c.post(f"/nodes/B/appliances/{aid}/toggle").json()["enabled"] is False, "toggle appliance off")
check(c.post(f"/nodes/B/appliances/{aid}/toggle").json()["enabled"] is True, "toggle appliance on")
check(c.post("/nodes/ZZZ/appliances", json={"type": "ac"}).status_code == 404, "unknown house -> 404")
check(c.delete(f"/nodes/B/appliances/{aid}").status_code == 200, "delete appliance")
check(c.post("/nodes/B/appliances", json={"type": "ev", "start": 20, "end": 5}).status_code == 400, "flexible wrap-around window rejected")

# --- edit house (solar / battery)
r = c.patch("/nodes/C", json={"panel_kw": 6, "battery_kwh": 5})
check(r.json()["panel_kw"] == 6 and r.json()["battery_kwh"] == 5, "edit house solar + battery")

# --- surprise event: the agent must not know about it
c.post("/nodes/D/events", json={"kw": 5, "hours": 2, "name": "Welding job"})
check(c.get("/state").json()["pending"].get("D") == 5, "pending event listed")
pred_before = None
res = c.post("/step").json()
d = [r for r in res["nodes"] if r["node"] == "D"][0]
check(d["load"] - d["pred_load"] >= 4.0, f"surprise load not in forecast (actual {d['load']} vs predicted {d['pred_load']})")
check(any("Welding job" in e for e in res["events"]), "event announced")
c.post("/step"); c.post("/step")
check(c.get("/state").json()["pending"] == {}, "event expired after its hours")

# --- weather
c.post("/reset"); c.post("/scenario", json={"preset": "clear"})
for _ in range(24): c.post("/step")
clear = c.get("/state").json()["summary"]
c.post("/reset"); c.post("/scenario", json={"preset": "monsoon"})
for _ in range(24): c.post("/step")
mons = c.get("/state").json()["history"]
check(sum(h["solar"] for h in mons) < 0.5 * sum(h["solar"] for h in c.get("/state").json()["history"]) + 1e9, "monsoon run ok")
c.post("/reset"); c.post("/scenario", json={"preset": "clear"})
for _ in range(24): c.post("/step")
h_clear = c.get("/state").json()["history"]
c.post("/reset"); c.post("/scenario", json={"preset": "monsoon"})
for _ in range(24): c.post("/step")
h_mons = c.get("/state").json()["history"]
check(sum(h["solar"] for h in h_mons) < 0.4 * sum(h["solar"] for h in h_clear), "monsoon cuts solar by more than 60 %")
c.post("/reset"); c.post("/scenario", json={"preset": "heatwave"})
for _ in range(24): c.post("/step")
h_hot = c.get("/state").json()["history"]
check(sum(h["load"] for h in h_hot) > 1.15 * sum(h["load"] for h in h_clear), "heatwave raises demand (AC)")
check(c.post("/scenario", json={"temp_c": 99}).status_code == 400, "absurd temperature rejected")
check(c.post("/scenario", json={"preset": "nope"}).status_code == 400, "unknown preset rejected")

# --- grid outage: no discom, the community runs as an island
c.post("/reset"); c.post("/scenario", json={"preset": "clear"})
for _ in range(11): c.post("/step")
c.post("/scenario", json={"outage": True})
res = c.post("/step").json()                                   # noon: plenty of solar
check(all(r["grid_import"] == 0 and r["grid_export"] == 0 for r in res["nodes"]), "outage: zero discom import/export")
check(any("OUTAGE" in e for e in res["events"]), "outage announced")
check(sum(r["p2p_bought"] for r in res["nodes"]) > 0 and sum(r["unserved"] for r in res["nodes"]) < 1e-6,
      "outage at noon: P2P + solar keep every home supplied")
check(sum(r["curtailed"] for r in res["nodes"]) > 0, "outage at noon: unusable surplus is curtailed (no grid to export)")
for _ in range(9): c.post("/step")                              # to 21:00 (night, no sun)
res = c.post("/step").json()
check(sum(r["unserved"] for r in res["nodes"]) > 0, "outage at night: unserved load appears")
check(c.get("/state").json()["summary"]["unserved_kwh"] > 0, "unserved kWh tracked in summary")
c.post("/scenario", json={"outage": False})

# --- settings & pricing
r = c.post("/settings", json={"feed_in": 2, "retail": 9, "grid_fee": 1, "dynamic_price": False})
check(r.json()["feed_in"] == 2, "tariff settings updated")
check(c.post("/settings", json={"feed_in": 9, "retail": 9}).status_code == 400, "inconsistent tariff rejected")
c.post("/settings", json={"beta": 0.3, "policy": "largest_first"})
check(c.post("/settings", json={"beta": 3}).status_code == 400, "beta out of range rejected")
for m in ("static", "dynamic", "hybrid"):
    check(c.post(f"/mode?name={m}").status_code == 200, f"mode {m}")
check(c.post("/mode?name=wat").status_code == 400, "unknown mode rejected")

# --- ledger / statement / savings / exports
c.post("/reset"); c.post("/settings", json={"feed_in": 3, "retail": 8, "grid_fee": 0.5, "dynamic_price": True, "beta": 0.5, "policy": "smallest_first"})
for _ in range(30): c.post("/step")
st = c.get("/statement/B").json()
check(st["p2p_bought_kwh"] > 0 and st["p2p_benefit_rs"] > 0, f"B saved money via P2P (benefit Rs {st['p2p_benefit_rs']})")
check(c.get("/ledger/B?limit=5").json() and "benefit_rs" in c.get("/ledger/B?limit=1").json()[0], "ledger rows carry benefit")
csvr = c.get("/export/ledger.csv")
check(csvr.status_code == 200 and "seller" in csvr.text.splitlines()[0], "ledger CSV export")
check("node" in c.get("/export/meter.csv?node=B").text.splitlines()[0], "meter CSV export")
sm = c.get("/state").json()["summary"]
check(all(k in sm for k in ("co2_avoided_kg", "local_energy_share_pct", "grid_import_reduction_pct", "fairness_jain")), "new KPIs in summary")

# --- compare uses the CURRENT community
cmp1 = c.get("/compare?days=2").json()
check(len(cmp1) == 3 and cmp1[0]["mode"] == "static", "compare returns 3 modes")

# --- config export / import
cfg = c.get("/config").json()
check(len(cfg["nodes"]) == 11 and "K" in [n["id"] for n in cfg["nodes"]], "config export has the added house")
small = {"nodes": [{"id": "X1", "panel_kw": 3, "appliances": [{"type": "ac"}]}, {"id": "X2", "panel_kw": 0, "appliances": [{"type": "ev"}]}]}
check(c.post("/config", json=small).json()["nodes"] == ["X1", "X2"], "config import replaces community")
check(c.post("/config", json={"nodes": []}).status_code == 400, "empty config rejected")
check(c.post("/config", json={"nodes": [{"id": "Q", "appliances": [{"type": "ac", "kw": -1}]}]}).status_code == 400, "bad appliance in config rejected")
c.post("/config", json=cfg)
check(len(c.get("/nodes").json()) == 11, "re-import full config")

# --- delete a house; keep at least 2
check(c.delete("/nodes/K").status_code == 200, "delete house")
c.post("/config", json=small)
check(c.delete("/nodes/X1").status_code == 400, "cannot drop below 2 houses")

# --- persistence: restart keeps houses + clock
c.post("/config", json=cfg); c.post("/reset"); [c.post("/step") for _ in range(5)]
c.post("/nodes", json={"id": "Z9", "panel_kw": 2})
db_path = os.environ["SQLITE_PATH"]
for m in ("db", "db_sqlite", "server", "engine", "forecast", "appliances"): sys.modules.pop(m, None)
from fastapi.testclient import TestClient
import server as s2
c2 = TestClient(s2.app)
st2 = c2.get("/state").json()
check(st2["restored"] and st2["hour"] == 5 and "Z9" in [n["id"] for n in st2["nodes"]], "restart restores houses and clock")
check(len(c2.get("/ledger/B").json()) >= 1, "history survives restart")
c2.post("/reset?defaults=true")
check(len(c2.get("/nodes").json()) == 10, "reset?defaults=true restores the demo community")

# --- admin token
c3, srv3 = fresh(admin_token="secret")
check(c3.post("/step").status_code == 401, "admin token: POST without token rejected")
check(c3.post("/step", headers={"X-Admin-Token": "secret"}).status_code == 200, "admin token: correct token accepted")
check(c3.get("/state").json()["auth_required"] is True and c3.get("/ledger/A").status_code == 200, "reads stay open")

# --- failure surfacing
c4, srv4 = fresh()
def boom(): raise RuntimeError("test failure")
import time
with TestClient(srv4.app) as cc:
    srv4.sim.tick = boom; cc.post("/start"); time.sleep(1.6)
    check(cc.get("/state").json()["error"] == "RuntimeError: test failure", "background failure is reported, not silent")

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
