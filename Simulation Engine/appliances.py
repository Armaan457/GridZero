"""
appliances.py - appliance catalog and load model.

A home's load is the sum of its appliances. Every appliance is a plain dict (JSON friendly):
  id, type, name, kw (rated power), start/end (hour window, end may be 24, window may wrap midnight),
  duty (fraction of the window it is actually drawing power), days ("all"/"weekday"/"weekend"),
  sensitivity ("none"/"cooling"/"heating": scales with outside temperature),
  enabled, flexible (+ duration_h: runs only that many hours, placed by the engine in the best solar hours),
  once ({"day","hour","hours"}: a one-off event load), surprise (True = the forecast agent is NOT told about it).
"""
import uuid

STANDBY_KW = 0.03          # always-on base (router, chargers, standby)

CATALOG = {
    "fridge":    dict(label="Refrigerator",              kw=0.15, start=0,  end=24, duty=0.35),
    "lights":    dict(label="LED lights",                kw=0.20, start=18, end=24, duty=1.0),
    "fan":       dict(label="Ceiling fans",              kw=0.15, start=9,  end=23, duty=0.8, sensitivity="cooling"),
    "tv":        dict(label="TV / entertainment",        kw=0.15, start=19, end=23, duty=0.8),
    "laptop":    dict(label="Work-from-home setup",      kw=0.12, start=10, end=18, duty=1.0),
    "ac":        dict(label="Air conditioner (daytime)", kw=1.5,  start=12, end=18, duty=0.7, sensitivity="cooling"),
    "ac_night":  dict(label="Air conditioner (night)",   kw=1.5,  start=22, end=7,  duty=0.6, sensitivity="cooling"),
    "geyser":    dict(label="Water heater (geyser)",     kw=2.0,  start=6,  end=8,  duty=0.5, sensitivity="heating"),
    "washer":    dict(label="Washing machine",           kw=0.5,  start=8,  end=12, duty=0.5),
    "microwave": dict(label="Microwave",                 kw=1.2,  start=19, end=21, duty=0.15),
    "induction": dict(label="Induction cooktop",         kw=1.8,  start=18, end=21, duty=0.35),
    "pump":      dict(label="Water pump",                kw=0.75, start=6,  end=9,  duty=0.35),
    "ev":        dict(label="EV charger (flexible)",     kw=3.3,  start=9,  end=23, duty=1.0, flexible=True, duration_h=3),
    "workshop":  dict(label="Workshop / shop machinery", kw=3.0,  start=10, end=17, duty=0.5),
    "custom":    dict(label="Custom load",               kw=1.0,  start=0,  end=24, duty=1.0),
}
DAYS = ("all", "weekday", "weekend")
SENS = ("none", "cooling", "heating")


def in_window(hour, start, end):
    if start == end: return True                      # whole day
    if start < end: return start <= hour < end
    return hour >= start or hour < end                # wraps midnight


def temp_factor(sens, temp_c):
    if sens == "cooling": return min(2.0, max(0.0, (temp_c - 22) / 10))      # 32C -> 1.0
    if sens == "heating": return min(2.0, max(0.3, (34 - temp_c) / 6))       # 16C -> 2.0 (floor 0.3)
    return 1.0


def expected_kw(a, day, hour, temp_c=30.0, skip_flexible=False):
    """Expected (noise-free) kWh drawn by appliance dict `a` in the hour slot (day, hour)."""
    if not a.get("enabled", True): return 0.0
    o = a.get("once")
    if o:
        slot, s = day * 24 + hour, o["day"] * 24 + o["hour"]
        return float(a["kw"]) if s <= slot < s + o["hours"] else 0.0
    d = a.get("days", "all")
    wd = day % 7                                       # day 0 = Monday
    if (d == "weekday" and wd >= 5) or (d == "weekend" and wd < 5): return 0.0
    if a.get("flexible"):
        if skip_flexible: return 0.0
        return float(a["kw"]) if hour in a.get("sched", []) else 0.0
    if not in_window(hour, int(a.get("start", 0)), int(a.get("end", 24))): return 0.0
    return float(a["kw"]) * float(a.get("duty", 1.0)) * temp_factor(a.get("sensitivity", "none"), temp_c)


def make_appliance(type_="custom", **over):
    """Build a validated appliance dict from the catalog defaults plus overrides."""
    base = dict(CATALOG.get(type_, CATALOG["custom"]))
    if type_ not in CATALOG: raise ValueError(f"unknown appliance type '{type_}'. Valid: {sorted(CATALOG)}")
    base.update({k: v for k, v in over.items() if v is not None})
    a = dict(id=uuid.uuid4().hex[:6], type=type_, name=base.get("name") or base["label"], kw=float(base["kw"]),
             start=int(base["start"]), end=int(base["end"]), duty=float(base.get("duty", 1.0)),
             days=base.get("days", "all"), sensitivity=base.get("sensitivity", "none"),
             enabled=bool(base.get("enabled", True)), flexible=bool(base.get("flexible", False)),
             duration_h=int(base.get("duration_h", 1)), surprise=bool(base.get("surprise", False)))
    if base.get("once"): a["once"] = dict(base["once"])
    validate(a)
    return a


def validate(a):
    if not (0 < a["kw"] <= 50): raise ValueError("kw must be between 0 and 50")
    if not (0 <= a["start"] <= 24 and 0 <= a["end"] <= 24): raise ValueError("start/end must be hours 0..24")
    if not (0 <= a["duty"] <= 1): raise ValueError("duty must be between 0 and 1")
    if a["days"] not in DAYS: raise ValueError(f"days must be one of {DAYS}")
    if a["sensitivity"] not in SENS: raise ValueError(f"sensitivity must be one of {SENS}")
    if a["flexible"]:
        if not a["start"] < a["end"]: raise ValueError("flexible loads need a same-day window (start < end)")
        if not 1 <= a["duration_h"] <= a["end"] - a["start"]:
            raise ValueError(f"duration_h must be 1..{a['end'] - a['start']} for this window")
    if a.get("once") and not (1 <= a["once"]["hours"] <= 168): raise ValueError("event hours must be 1..168")


def default_appliances(size=4, ac="night"):
    """Starter appliance set by household size. ac: none / night / day / both."""
    types = ["fridge", "lights", "fan", "tv"]
    if size >= 3: types.append("laptop")
    if size >= 4: types += ["washer", "geyser"]
    if size >= 6: types.append("induction")
    if ac in ("night", "both"): types.append("ac_night")
    if ac in ("day", "both"): types.append("ac")
    return [make_appliance(t) for t in types]


_PATCHABLE = {"name": str, "kw": float, "start": int, "end": int, "duty": float, "days": str,
              "sensitivity": str, "enabled": bool, "flexible": bool, "duration_h": int}


def apply_patch(a, patch):
    """Return an updated, validated copy of appliance dict `a`. Unknown keys are rejected."""
    bad = set(patch) - set(_PATCHABLE)
    if bad: raise ValueError(f"cannot change {sorted(bad)}; allowed: {sorted(_PATCHABLE)}")
    new = dict(a)
    for k, v in patch.items():
        if v is not None: new[k] = _PATCHABLE[k](v)
    validate(new)
    if new.get("flexible") != a.get("flexible") or any(new.get(k) != a.get(k) for k in ("start", "end", "duration_h")):
        new.pop("sched", None); new.pop("sched_day", None)       # engine re-plans flexible hours
    return new
