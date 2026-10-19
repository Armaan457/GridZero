"""
test_db_backends.py - proves SQLite and DynamoDB give IDENTICAL API answers and both persist engine state
(DynamoDB is mocked with moto, no AWS account needed).
Run:  pip install moto httpx && python test_db_backends.py
"""
import json, os, sys, tempfile

def run_scenario(backend):
    for m in ("db", "db_sqlite", "db_dynamo", "server", "engine", "forecast", "appliances"):
        sys.modules.pop(m, None)
    os.environ["DB_BACKEND"] = backend
    os.environ["SQLITE_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
    from fastapi.testclient import TestClient
    import server
    c = TestClient(server.app)
    c.post("/reset?defaults=true")
    c.post("/nodes", json={"id": "K", "panel_kw": 5, "battery_kwh": 6, "household_size": 4})
    c.post("/scenario", json={"preset": "heatwave"})
    for i in range(30):
        if i == 12: c.post("/inject?node=B&kwh=3")
        if i == 20: c.post("/scenario", json={"outage": True})
        if i == 22: c.post("/scenario", json={"outage": False})
        c.post("/step")
    out = dict(ledgerB=c.get("/ledger/B?limit=6").json(), ledgerK=c.get("/ledger/K?limit=3").json(),
               stmtB=c.get("/statement/B").json(), stmtK=c.get("/statement/K").json(),
               all=c.get("/ledger_all?limit=8").json(), events=c.get("/events").json(),
               cfg=c.get("/config").json(), nodes=[n["id"] for n in c.get("/nodes").json()])
    for nd in out["cfg"]["nodes"]:                      # appliance ids are random per run, not a backend difference
        for a in nd["appliances"]: a.pop("id", None)
    # restart: a new process would call db.load_config() and continue from the same clock
    import db
    saved = db.load_config()
    out["saved_clock"] = [saved["day"], saved["hour"]]
    out["saved_nodes"] = [n["id"] for n in saved["nodes"]]
    out["saved_scenario"] = saved["scenario"]
    c.post("/reset")
    out["after_reset"] = (c.get("/ledger/B").json(), c.get("/ledger_all").json(), c.get("/events").json())
    return json.loads(json.dumps(out))

if __name__ == "__main__":
    os.environ.update(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x", AWS_DEFAULT_REGION="ap-southeast-2")
    from moto import mock_aws
    a = run_scenario("sqlite")
    with mock_aws():
        b = run_scenario("dynamodb")
    for k in a:
        same = a[k] == b[k]
        print(f"{k:14s} {'OK  identical' if same else 'DIFFERENT'}")
        if not same: print("  sqlite  :", str(a[k])[:300]); print("  dynamodb:", str(b[k])[:300])
    assert a == b, "backends differ"
    assert a["after_reset"] == [[], [], []]
    assert a["saved_clock"] == [1, 6] and "K" in a["saved_nodes"] and a["saved_scenario"]["temp_c"] == 41.0
    print("\nALL GOOD - both backends return the same data and persist the engine state")
