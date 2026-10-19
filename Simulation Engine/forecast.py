"""
forecast.py - the ONE place where Section 1 (the ML agent) plugs into Section 2 (the engine).

Before every slot the engine calls predict(meta, day, hour, ctx) for each home and builds the PLANNED allocation
from the answers. Actual meter readings then decide the REAL allocation; the gap is shown on the dashboard.

CONNECT THE AGENT (pick one):
  A) HTTP:   FORECAST_URL=http://<agent-host>:<port>/predict
     The engine POSTs JSON and expects {"pred_load": <kWh>, "pred_solar": <kWh>} for that one hour:
       { "node_id","day","hour","panel_kw","base_kw","household_size",
         "appliances": ["fridge","ac_night",...],             # types of the enabled appliances (always sent)
         "appliance_details": [ {type,kw,start,end,duty,...} ], # full detail (ignore if you don't need it)
         "temp_c": 30.0, "cloud_cover": 0.15 }                  # weather the engine is simulating
  B) Python: edit baseline_predict() to call your trained model.
If the agent is down or slower than 1.5 s the engine silently falls back to baseline_predict().
Surprise events (loads injected with surprise=true) are NOT included in what the agent sees.
"""
import json, math, os, urllib.request
import appliances as ap

FORECAST_URL = os.environ.get("FORECAST_URL", "").strip()


def load_shape(hour):
    """Fallback household curve (used only when a node has no appliance details)."""
    return (0.6 + 0.5 * math.exp(-((hour - 8) ** 2) / 4) + 0.5 * math.exp(-((hour - 15) ** 2) / 6)
            + 0.9 * math.exp(-((hour - 20) ** 2) / 5))


def solar_shape(hour):
    return max(0.0, math.sin(math.pi * (hour - 6) / 12)) if 6 <= hour <= 18 else 0.0


def solar_factor(cloud):
    """Fraction of clear-sky output at a given cloud cover (0..1)."""
    return max(0.0, 1.0 - 0.8 * min(max(cloud, 0.0), 1.0))


def baseline_predict(meta, day, hour, ctx=None):
    """Noise-free expectation from the appliance list + weather (stand-in for the trained model)."""
    ctx = ctx or {}
    temp, cloud = ctx.get("temp_c", 30.0), ctx.get("cloud_cover", 0.15)
    details = meta.get("appliance_details")
    if details is not None:
        load = ap.STANDBY_KW + sum(ap.expected_kw(a, day, hour, temp) for a in details)
    else:
        load = meta.get("base_kw", 1.0) * load_shape(hour)
    solar = meta["panel_kw"] * solar_shape(hour) * solar_factor(cloud) * 0.95
    return round(load, 3), round(solar, 3)


def predict(meta, day, hour, ctx=None):
    """Return (pred_load_kwh, pred_solar_kwh, source) for one node and one hourly slot."""
    ctx = ctx or {}
    if FORECAST_URL:
        try:
            body = json.dumps({"node_id": meta["id"], "day": day, "hour": hour, "panel_kw": meta["panel_kw"],
                               "base_kw": meta.get("base_kw"), "household_size": meta.get("household_size"),
                               "appliances": meta.get("appliances"), "appliance_details": meta.get("appliance_details"),
                               "temp_c": ctx.get("temp_c", 30.0), "cloud_cover": ctx.get("cloud_cover", 0.15)}).encode()
            req = urllib.request.Request(FORECAST_URL, body, {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=1.5) as r:
                out = json.loads(r.read())
            return float(out["pred_load"]), float(out["pred_solar"]), "agent"
        except Exception:
            pass                                          # fall through to baseline
    l, s = baseline_predict(meta, day, hour, ctx)
    return l, s, "baseline"
