# P2P Energy Engine - Section 2 (simulation, matching, dispatch, API)

A virtual neighbourhood that shares rooftop-solar surplus between homes hour by hour, records who sold to whom,
and serves everything through an API + a built-in control room.

## Run it
```bash
pip install -r requirements.txt
uvicorn server:app --port 8000           # run it FROM this folder
```
Dashboard http://localhost:8000 | API docs http://localhost:8000/docs | `python engine.py` prints the mode comparison.
Docker: see `DOCKER.md`. AWS hosting: `DEPLOY_AWS.md`. DynamoDB: `AWS_DYNAMODB_SETUP.md`. Frontend developer: `FRONTEND_INTEGRATION.md`.

## What it can do
| Area | Features |
|---|---|
| **Houses** | Add / edit / delete homes at runtime (solar kW, battery kWh, people, feeder), 10-home demo community included |
| **Loads** | 15 appliance types (AC, geyser, EV, induction, pump, workshop...) or any custom load with kW, hour window, duty, weekday/weekend; turn on/off, edit, delete |
| **Flexible loads** | EV charger, washer, pump... can be flexible: the engine places their run-hours in the sunniest hours (demand response) |
| **Events** | Temporary loads (guests arrive, welding job) for N hours; "surprise" ones are hidden from the forecast agent |
| **Weather** | Temperature (AC / fans / geyser react) and cloud cover (solar reacts), presets: clear, heatwave, monsoon, winter |
| **Grid outage** | Cuts discom import/export: the community runs as an island on solar, batteries and P2P; unserved energy and curtailed solar are tracked |
| **Sharing modes** | Static (equal, capped), Dynamic (priority), Hybrid (base share + priority), tunable base share and priority policy |
| **Money** | Moving price between feed-in and retail-minus-fee (or fixed), discom grid fee, per-user earn/owe and savings vs no P2P, tariffs editable live |
| **Metrics** | P2P kWh, demand met, grid-import cut, local energy share, fairness (Jain), homes fully served, savings, CO2 avoided (editable factor), forecast error, unserved kWh |
| **Agent** | `forecast.py` calls your ML agent (`FORECAST_URL`) with appliance + weather context, falls back to a baseline if it is down |
| **Data** | SQLite or DynamoDB, state saved every hour (restart continues), CSV export (ledger, meter), community JSON export / import |
| **Safety** | Optional `ADMIN_TOKEN` for all changes, background failures shown on the dashboard instead of freezing |

## Files
| File | Role |
|---|---|
| `engine.py` | Houses, meter reading, plan -> match -> settle loop, scheduling of flexible loads, scenario, settings, metrics |
| `appliances.py` | Appliance catalog and load model (windows, duty, temperature sensitivity, events) |
| `allocators.py` | Static / Dynamic / Hybrid sharing policies |
| `forecast.py` | The plug-in point for the ML agent |
| `server.py` | FastAPI endpoints (control, editing, scenario, settings, config, read, export) |
| `db.py`, `db_sqlite.py`, `db_dynamo.py` | Storage layer (`DB_BACKEND=sqlite|dynamodb`) |
| `static/index.html` | Control-room dashboard (works offline) |
| `Dockerfile`, `docker-compose.yml`, `.env.example` | Container image |
| `test_features.py`, `test_db_backends.py` | 62 feature checks + SQLite vs DynamoDB (mocked) equivalence test (`pip install -r requirements-dev.txt`) |

## What happens every simulated hour
1. **Plan** - the agent predicts each home's load and solar (using appliances + weather) -> planned allocation
2. **Read** - virtual meters give actuals (noise, clouds, heat, surprise events)
3. **Classify** - supplier (surplus solar / spare battery), buyer (unmet need), neutral
4. **Match** - the pool is shared by the chosen mode, per feeder
5. **Settle** - ledger rows, battery charging with unsold surplus, discom import/export (or unserved/curtailed in an outage), savings
Energy is a virtual allocation of exports to imports in the same feeder and hour (virtual-net-metering style), not physically routed.

## Demo script (5 minutes)
1. **Start**. Explain green suppliers / orange buyers and the flow list.
2. **Heatwave** preset: demand jumps, supply gets scarce. Press **Compare sharing modes** - the modes now differ.
3. Open **Edit loads** on a home: add a 7 kW EV (flexible) and watch it land in solar hours; add a "Guests arrive" surprise event and read the live event (agent planned X, actual Y).
4. **Cut grid (outage)** at midday: the island keeps running; at night unserved energy appears -> argue for batteries.
5. **Monsoon** preset: solar collapses, grid import rises.
6. Ledger + Statement of a buyer and a seller (units, money, savings vs no P2P).
7. Export the community JSON and the ledger CSV.

## Settlement model (what to say about money)
- Units are reassigned on the discom bill (virtual net metering style); no price on that part.
- Money for P2P units settles between users via the platform wallet; the discom gets a per-unit grid fee.
- Price stays between feed-in and retail-minus-fee, so sellers earn more than exporting and buyers pay less than retail.
All tariffs and the CO2 factor are assumptions you can edit; check your state's rules before quoting real numbers.

## Known limits (be upfront)
Hourly slots, no distribution losses / battery efficiency / feeder capacity, synthetic data unless a dataset is loaded,
flexible-load placement uses the built-in baseline forecast (not the agent), one global simulation clock (run ONE instance),
and the dashboard has been smoke-tested against the API but only machine-checked, not clicked through in a browser by the author.
