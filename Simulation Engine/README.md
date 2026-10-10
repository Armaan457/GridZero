# P2P Energy Engine (Section 2) - Simulation, Matching & Dispatch

## Run it (2 minutes)
```bash
pip install -r requirements.txt
uvicorn server:app --port 8000
# open http://localhost:8000      (API docs: http://localhost:8000/docs)
```
`python engine.py` alone prints the Static / Dynamic / Hybrid comparison without the server.

## Files
| File | Role |
|---|---|
| `allocators.py` | The 3 sharing policies (Static, Dynamic, Hybrid) - pure functions |
| `engine.py` | Virtual smart meters, batteries, plan -> read -> classify -> match -> settle, pricing, ledger, metrics |
| `forecast.py` | **Plug-in point for the ML agent** (HTTP or Python), falls back to a baseline forecaster |
| `db.py` | SQLite storage for ledger / meter history |
| `server.py` | FastAPI: control + data endpoints used by the website |
| `static/index.html` | Judge-facing live dashboard (works offline, no CDN) |

## What happens every simulated hour
1. **Plan** - forecast agent predicts each home's load and solar -> planned P2P allocation
2. **Read** - virtual smart meters give the actual load/solar (noise, cloud, sudden events)
3. **Classify** - supplier (solar surplus or spare battery) / buyer (unmet need) / neutral
4. **Match** - pool is shared among buyers by the chosen mode (per feeder)
5. **Settle** - ledger rows (seller, buyer, kWh, price, grid fee); unsold surplus charges the battery, rest goes to the discom; unmet need is imported from the discom
Energy is a *virtual allocation* of exports to imports in the same feeder and slot (virtual-net-metering style), not physically routed.

## Sharing modes
- **Static** - equal share to every needy home, capped at its need, leftovers re-split
- **Dynamic** - strict priority queue (smallest-need-first by default = max homes fully served)
- **Hybrid** - half the pool as equal base shares, the rest by priority queue

## Connect the ML agent (Section 1)
- **HTTP:** `FORECAST_URL=http://host:port/predict uvicorn server:app`. The engine POSTs
  `{node_id, hour, day, panel_kw, base_kw, household_size, appliances}` and expects `{"pred_load": kWh, "pred_solar": kWh}`.
- **Python:** edit `baseline_predict()` in `forecast.py` to call the trained model.
- The dashboard badge shows `forecast: agent` or `forecast: baseline`. Fallback is automatic if the agent is down.
- **Real dataset instead of synthetic readings:** `READINGS_CSV=data.csv uvicorn server:app`, with columns `node_id,hour,load_kwh,solar_kwh`.

## API (for the website team)
`POST /start /pause /step /reset /speed?value= /mode?name= /inject?node=B&kwh=3`
`GET /state /ledger/{node} /statement/{node} /ledger_all /events /compare?days=3`

## 3-minute demo script for judges
1. Open the dashboard, press **Start** (hybrid mode). Explain: green = suppliers, orange = buyers.
2. Watch ~10:00-14:00: solar homes (A, C, E, G) supply the pool; arrows show who feeds whom.
3. **Sudden demand:** around 11:00-12:00 press "+3 kWh" on Home B. Event log shows e.g.
   *agent planned 1.0 kWh P2P, actual need 4.0 -> P2P served 3.7, discom 0.3*. The dashed plan line vs the solid actual line on the chart shows the same.
4. Show **Ledger** of B (credited units, amount owed) and of A (units sold, amount earned) + the **Statement**.
5. Press **Compare sharing modes**: Dynamic serves the most homes fully, Static is fairest, Hybrid is the compromise.
6. Evening: no solar -> batteries (A, E) sell stored energy; discom imports rise. Say: "batteries are the next scaling step".

## Settlement model (what to say if asked "how does money flow?")
- **Units** are reassigned on the discom bill (virtual net metering style) - no price on that part.
- **Money for P2P units** settles between users through the platform wallet (UPI in real life).
- **Discom** gets a per-unit grid/wheeling fee (Rs 0.5 here) as a bill line item.
- **Price** moves between feed-in (Rs 3) and retail-minus-fee (Rs 7.5) with scarcity, so sellers earn more than export and buyers pay less than retail.
All tariffs are assumptions in `engine.py` - check your state's current net-metering / virtual-net-metering rules before quoting real numbers.

## Mapping to AWS (the hackathon story)
Virtual meter -> **IoT Core** (MQTT) -> **Lambda** running `Engine.step()` -> **DynamoDB** (ledger/meter tables from `db.py`) -> **API Gateway** -> website on **Amplify**; forecasts from **SageMaker** endpoint (`FORECAST_URL`); optional **Bedrock** for plain-language explanations. The allocation code does not change.

## Known limits (be upfront)
Hourly slots, no distribution losses or battery efficiency, one fixed tariff, synthetic default data, and no feeder capacity limits. All are listed as next steps.
