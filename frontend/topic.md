# Refined Plan: P2P Energy Sharing

Your idea is solid. I've made a few refinements first, then the full flow, with most of the detail on Section 2.

## Refinements

**1. Energy isn't physically "diverted", so call it a virtual allocation.**
A's surplus goes onto the shared grid, and B draws from the grid. Your system decides on paper whose export covers whose import in that time slot. Judges will respect you for stating this. Call Section 2 the **Matching & Dispatch Engine** with **virtual smart meters**. Also restrict sharing to homes on the same feeder or locality, since that is what makes it practical in real life.

**2. The agent must forecast generation as well as consumption.**
Surplus = solar generation − consumption. If you only predict consumption, you can't predict who has surplus. So you need two forecasts: load (using household size, appliances, location, hour and day type) and solar (using weather, irradiance and panel size).

**3. Use "Exported / Imported" in the ledger instead of Debit/Credit.**
Debit/Credit confuses people, because A "debited" actually means A earned. Use clear columns: `Grid Import`, `Solar Export`, `P2P Sold`, `P2P Bought`.

**4. Static mode needs a cap.**
An equal split "irrespective of need" can give someone more than they need, which wastes energy. Use equal split capped at each node's need, and redistribute the leftover (water-filling). Pseudocode is below.

**5. Settlement (your open question): the practical way is to split units from money.**
- **Units (kWh):** the discom reassigns them in billing. A's exported units are allocated to B instead of being banked for A. This is similar to virtual net metering.
- **Money for P2P units:** settled between users through your platform wallet (UPI in real life), with a small platform fee.
- **Discom's share:** a grid or wheeling charge per P2P unit, shown as a line item. The discom owns the wires and must get paid for them.
- **Price:** a slot price between the feed-in tariff and the retail tariff. For example, the midpoint, so sellers earn more than exporting and buyers pay less than retail.

Check the current net-metering and virtual net-metering rules for your state before quoting specifics. For a hackathon, calling this a proposal that fits existing virtual net metering is enough.

## Section 1: Agent (forecasting)

- **Data:** pick from the Ausgrid Solar Home dataset (consumption and rooftop solar), the London Smart Meter dataset, UCI Household Power Consumption, REFIT, and BDG2. For India-like profiles, **generate synthetic data**: a base load curve, plus appliance rules (AC in summer afternoons and nights, geyser in the morning), plus noise. Get solar irradiance from NASA POWER or Open-Meteo.
- **Model:** start with **LightGBM** using lag features (same hour yesterday, same hour last week), hour, weekday, temperature, household size, appliance flags and city. Add an LSTM only if time remains. LightGBM is fast to train and easy to explain.
- **Output per node and per slot:** `pred_load`, `pred_solar`, `pred_surplus_or_need`, plus a confidence band.
- **AWS:** train in SageMaker (or locally), store the model in S3, and serve it through Lambda or a SageMaker endpoint. Optionally use **Amazon Bedrock** for a short plain-language explanation such as "You will likely have 3 kWh surplus tomorrow 12-3pm". That is a nice "agent" touch.

## Section 2: Simulation / Matching Engine (the main part)

### Architecture

```
Virtual Smart Meters (Python, 1 per household)
        │  every tick: {node_id, slot, load_kwh, solar_kwh}
        ▼
AWS IoT Core (MQTT)  ──►  Lambda (ingest)  ──►  DynamoDB (live state)
                                                   │
Forecast (Section 1) ──► plan for next slots ──────┤
                                                   ▼
                              Dispatch Engine (Lambda / ECS)
                      [classify → allocate by mode → reconcile]
                                                   ▼
                          Ledger table (DynamoDB / RDS) ──► Website
```

**Simplest route:** build the whole engine as one Python package that runs locally and reads and writes a database. Then wrap it in AWS (IoT Core, Lambda, DynamoDB) once it works. A working core with a thin AWS layer beats a broken, fully cloud-native build. Using IoT Core with the **AWS IoT Device Simulator** (or a small script publishing MQTT) also covers the "hardware" requirement.

### Step 1: Virtual meters and time-compressed clock

- Create a `Node` class with `id, has_solar, panel_kw, appliances, household_size, battery (optional)`.
- Create a **simulation clock**: 1 real second = 15 sim-minutes, with a speed slider. Slots are 15 minutes (or hourly if you want it simpler).
- Each tick, a node emits actual load and solar, taken from the dataset or the synthetic generator plus noise. The noise is what makes actuals differ from forecasts.

### Step 2: Classify nodes every slot

```
net = solar - load
if net > 0:  supplier, surplus = net
if net < 0:  buyer, need = -net
else: neutral
pool = sum(all surplus)
```

### Step 3: Allocation modes

**Static (equal share, capped):**
```python
def static(pool, needs):
    got = {n: 0 for n in needs}
    active = {n for n in needs if needs[n] > 0}
    while pool > 1e-6 and active:
        share = pool / len(active)
        for n in list(active):
            give = min(share, needs[n] - got[n])
            got[n] += give; pool -= give
            if got[n] >= needs[n] - 1e-9: active.remove(n)
    return got
```

**Dynamic (priority queue):** pick a policy and make it configurable:
- *Largest need first:* serves heavy users first.
- *Smallest need first:* fully serves the most homes, which gives the highest number of satisfied nodes.
```python
def dynamic(pool, needs, policy="smallest_first"):
    order = sorted(needs, key=needs.get, reverse=(policy=="largest_first"))
    got = {}
    for n in order:
        got[n] = min(needs[n], pool); pool -= got[n]
    return got
```

**Hybrid:** phase 1 gives every buyer a base share (for example 50% of the pool, split equally and capped by need). Phase 2 runs the dynamic priority queue on the remaining pool and the remaining needs.
```python
def hybrid(pool, needs, beta=0.5):
    base = static(pool*beta, needs)
    residual = {n: needs[n]-base[n] for n in needs}
    extra = dynamic(pool*(1-beta), residual)
    return {n: base[n]+extra[n] for n in needs}
```

**Attributing sellers to buyers:** the engine allocates from the combined pool, then splits each buyer's units across sellers pro rata. That gives the ledger row "B got 4 kWh: 3 from A, 1 from C". Whatever is still unmet is imported from the discom.

### Step 4: Forecast vs reality (your "sudden need" case)

Use two layers:
1. **Planned schedule (forecast-based):** at the start of the day or hour, the engine computes an expected matching plan from predictions. This is shown in the UI and used for price signals and notifications.
2. **Actual settlement (meter-based):** each slot, the engine re-runs allocation on **real** readings. If B now needs energy and surplus exists, B is served. If no surplus remains, B imports from the discom. This also naturally handles the case where A produces less than predicted.

Log the **forecast error** per slot. It makes a good chart: predicted plan vs actual outcome.

### Step 5: Pricing and ledger write

For each (seller, buyer, slot) match, write one row:
```
slot, seller_id, buyer_id, kwh, price_per_kwh, amount, mode
```
From this, you derive each user's view:
- **A:** P2P Sold 10 kWh at 1–2pm, earned ₹X
- **B:** P2P Bought 10 kWh at 1–2pm, owes ₹X
- Plus `grid_import_kwh` and `solar_export_kwh` per slot (units only, no discom price)

Make writes idempotent, keyed on `(slot, seller, buyer)`, so a replayed tick doesn't double-count.

### Step 6: Metrics (use these to compare your 3 modes in the demo)

- % of surplus used (vs sent to the grid)
- % of demand met by P2P
- Grid import reduction
- Number of fully satisfied homes
- **Jain's fairness index**

Run all three modes on the same day of data and show a comparison table. That makes your Hybrid vs Static vs Dynamic design a result rather than just a claim.

## Section 3: Website

- **Stack:** React or Next.js hosted on AWS Amplify, backed by API Gateway + Lambda reading DynamoDB.
- **Pages:**
  1. **Dashboard:** hourly consumption and solar graph (actual vs predicted), today's surplus or need.
  2. **Ledger:** table with slot, grid import, P2P sold or bought, units, and money earned or owed for P2P only.
  3. **Live Simulation (for judges):** play/pause, speed slider, a mode switch (Static, Dynamic, Hybrid), a node map showing arrows A → B, and an **"Inject sudden demand at B"** button for your live override demo.
  4. **Compare Modes:** the metrics table and charts.
  5. **Monthly statement:** a mock "discom adjustment" showing the reassigned units and grid fee, which makes the settlement story concrete.

## Suggested build order

1. **Core engine in plain Python** (nodes, clock, three allocators, ledger). Test it with 5–10 nodes using synthetic data. *(This is the heart. Do it first.)*
2. **Forecast model** on the synthetic data. Plug in its output as the "planned schedule".
3. **API plus website** reading the ledger.
4. **Move to AWS:** IoT Core and the device simulator, Lambda, DynamoDB, Amplify.
5. **Polish:** the sudden-demand demo, the mode comparison, and the architecture diagram plus a one-line real-world story ("what changes when this goes live: real smart meters replace the virtual ones").

**Suggested team split:** one person on the ML agent, one on the engine and the AWS plumbing, and one on the frontend. Everyone helps with the demo script.

If you tell me how many days you have and how many teammates, I can turn this into a day-by-day schedule or write the starter code for the engine (Step 1 to Step 5).