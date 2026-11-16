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

```mermaid
flowchart TD
    subgraph UI ["Frontend · Next.js 16 (Port 3000)"]
        Views["Live Feeder Flow · Dashboard · Policy Comparison · Statement"]
        Controls["Simulation & Scenario Controls (Speed, Load Injection, Outage)"]
    end

    subgraph SIM ["Simulation & Settlement Engine · FastAPI (Port 8000)"]
        SimServer["Async Simulation Loop & Clock (server.py · engine.py)"]
        Meters["Virtual Smart Meters & Batteries (10 Archetype Nodes)"]
        Allocators["Matching Policies: Static, Dynamic, Hybrid (allocators.py)"]
        Pricing["Dynamic Scarcity Pricing (₹3.00 - ₹7.50 / kWh)"]
        DB[("Database · DynamoDB / SQLite (Ledger & Telemetry)")]
        
        SimServer --> Meters
        Meters --> Allocators
        Allocators --> Pricing
        Pricing --> DB
    end

    subgraph ML ["ML & Intelligence Service · FastAPI (Port 8001)"]
        MLServer["Inference API (POST /predict · /agent/advisory)"]
        Weather["Open-Meteo API (Solar GHI, DNI, Cloud Cover)"]
        LGBM["LightGBM Quantile Forecaster (P10, P50, P90)"]
        Bedrock["Amazon Bedrock Agent (Nova Lite · Advisories & SHAP XAI)"]
        
        Weather --> LGBM
        MLServer --> LGBM
        LGBM --> Bedrock
    end

    subgraph Settlement ["Settlement & Physical Grid"]
        DISCOM["DISCOM Utility (Virtual Net-Metering + ₹0.50/kWh Fee)"]
        Wallet["Platform Wallet (P2P Rupee Clearing)"]
    end

    UI -->|Next.js Proxy /engine| SimServer
    Meters -->|POST /predict| MLServer
    Allocators -->|Grid Import / Export Residuals| DISCOM
    Pricing -->|P2P Financial Settlement| Wallet
```

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