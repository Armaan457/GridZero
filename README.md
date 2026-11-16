# GridZero

Intelligent peer-to-peer microgrid energy sharing platform that matches rooftop solar surplus with neighborhood deficit on the shared feeder dynamically.

---

## Overview

Traditional setups sell rooftop solar back to the utility at low feed-in tariffs (~₹3/kWh) while neighbors buy at retail (~₹8/kWh). **GridZero** enables direct community microgrid sharing:

- **Virtual Feeder Allocation:** Matches prosumer exports to neighbor imports across homes on the same feeder via virtual net metering—no dedicated wiring required.
- **10 Archetype Microgrid & Demand Response:** Models 10 realistic Indian household archetypes with 15 appliance profiles and automated flexible load scheduling (EV charging, washers) shifted into peak solar generation hours.
- **Dual Forecaster:** Predicts household load and solar generation using LightGBM quantile regression ($P_{10}, P_{50}, P_{90}$) with live Open-Meteo solar irradiance.
- **Three Allocation Modes:** Evaluates **Static** (water-filling equal share), **Dynamic** (priority queue), and **Hybrid** (base share + priority) policies benchmarked on Jain's Fairness Index.
- **Scenario & Grid Outage Resilience:** Simulates weather presets (Clear, Heatwave, Monsoon, Winter) and grid blackout scenarios where the microgrid islands onto solar, battery storage (with state-of-charge tracking and reserve margins), and P2P sharing.
- **Day-Ahead Look-Ahead Caching:** Synchronizes with the simulation clock to precompute 24-hour load and solar horizons in-memory, eliminating per-hour API bottlenecks and mirroring real-world utility dispatch.
- **Decoupled Settlement:** Kilowatt-hour units reassign on utility bills; money clears peer-to-peer at dynamic mid-market rates (₹3.00–₹7.50) with a ₹0.50/kWh DISCOM wheeling charge.
- **GenAI Advisory:** Amazon Bedrock (Nova Lite / Claude 3 Haiku) with SHAP attribution for plain-English dispatch guidance and weather-shock alerts.

---

## System Architecture

<div align="center">
<div style="max-width: 680px;">

```mermaid
%%{init: {'flowchart': {'nodeSpacing': 25, 'rankSpacing': 30}}}%%
flowchart TD
    subgraph UI ["Frontend · Next.js 16 (:3000)"]
        Views["Live Feeder Flow & Dashboard"]
        Controls["Scenario & Simulation Controls"]
    end

    subgraph SIM ["Simulation & Settlement Engine · FastAPI (:8000)"]
        SimServer["Async Simulation Clock"]
        Meters["Smart Meters & Batteries (10 Nodes)"]
        Allocators["Matching: Static · Dynamic · Hybrid"]
        Pricing["Scarcity Pricing (₹3.00–₹7.50/kWh)"]
        DB[("DynamoDB / SQLite Ledger")]
        
        SimServer --> Meters --> Allocators --> Pricing --> DB
    end

    subgraph ML ["ML Intelligence Service · FastAPI (:8001)"]
        MLServer["Inference API"]
        Weather["Open-Meteo Weather API"]
        Training["Retraining Pipeline"]
        LGBM["LightGBM Forecaster (P10/P50/P90)"]
        SHAP["SHAP Explainer"]
        Bedrock["Amazon Bedrock GenAI"]
        
        Weather --> LGBM
        Training --> LGBM
        MLServer --> LGBM --> SHAP --> Bedrock
    end

    subgraph Settlement ["Settlement & Physical Grid"]
        DISCOM["DISCOM Utility Net-Metering"]
        Wallet["P2P Financial Clearing Wallet"]
    end

    UI -->|Next.js Proxy /engine| SimServer
    SimServer -->|POST /predict| MLServer
    Allocators -->|Grid Import / Export| DISCOM
    Pricing -->|P2P Rupee Settlement| Wallet
```

</div>
</div>

---

## Tech Stack

| Layer | Technologies |
|---|---|
| **Frontend** | Next.js 16, React 19, Tailwind CSS and SWR |
| **Backend** | FastAPI and Uvicorn |
| **Storage** | Amazon S3 and DynamoDB |
| **AI/ML** | LightGBM, SHAP and Amazon Bedrock |
| **Data & APIs** | Open-Meteo Weather API |
| **Simulation** | Discrete-Event Engine and Virtual Smart Meters |
| **Containerization & Deployment** | Docker, Docker Compose, AWS ECR, AWS ECS Fargate and GitHub Actions |