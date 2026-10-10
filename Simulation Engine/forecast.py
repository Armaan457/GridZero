"""
forecast.py - the ONE place where Section 1 (the ML agent) plugs into Section 2 (the engine).

The engine calls predict(node_meta, day, hour) before every slot and uses the answer
to build the PLANNED allocation. Actual meter readings then decide the REAL allocation,
and the difference between the two is shown on the dashboard.

HOW TO CONNECT YOUR TEAMMATES' AGENT (pick one):
  A) HTTP:   set env var FORECAST_URL=http://<their-host>:<port>/predict
             The engine POSTs  {"node_id","hour","day","panel_kw","household_size","appliances"}
             and expects      {"pred_load": <kWh>, "pred_solar": <kWh>}
  B) Python: replace the body of baseline_predict() with  model.predict(...)  (load a pickle once, at import)

If the agent is down / slow, we automatically fall back to baseline_predict(), so the demo never breaks.
"""
import json, math, os, urllib.request

FORECAST_URL = os.environ.get("FORECAST_URL", "").strip()


def load_shape(hour):
    """Typical Indian household curve: morning peak, afternoon AC bump, big evening peak, low at night."""
    return (0.6 + 0.5 * math.exp(-((hour - 8) ** 2) / 4)
            + 0.5 * math.exp(-((hour - 15) ** 2) / 6)
            + 0.9 * math.exp(-((hour - 20) ** 2) / 5))


def solar_shape(hour):
    return max(0.0, math.sin(math.pi * (hour - 6) / 12)) if 6 <= hour <= 18 else 0.0


def baseline_predict(meta, day, hour):
    """Noise-free expected profile (stand-in for the trained model)."""
    pred_load = meta["base_kw"] * load_shape(hour)
    pred_solar = meta["panel_kw"] * solar_shape(hour) * 0.85      # 0.85 = mean cloud factor
    return round(pred_load, 3), round(pred_solar, 3)


def predict(meta, day, hour):
    """Return (pred_load_kwh, pred_solar_kwh, source) for one node and one hourly slot."""
    if FORECAST_URL:
        try:
            body = json.dumps({"node_id": meta["id"], "hour": hour, "day": day,
                               "panel_kw": meta["panel_kw"], "base_kw": meta["base_kw"],
                               "household_size": meta.get("household_size"),
                               "appliances": meta.get("appliances")}).encode()
            req = urllib.request.Request(FORECAST_URL, body, {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=1.5) as r:
                out = json.loads(r.read())
            return float(out["pred_load"]), float(out["pred_solar"]), "agent"
        except Exception:
            pass                                          # fall through to baseline
    l, s = baseline_predict(meta, day, hour)
    return l, s, "baseline"
