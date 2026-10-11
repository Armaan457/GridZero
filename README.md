# GridZero

Intelligent peer-to-peer microgrid energy sharing platform that matches rooftop solar surplus with neighborhood deficit on the shared feeder in real time.

---

## Overview

Traditional setups sell rooftop solar back to the utility at low feed-in tariffs (~₹3/kWh) while neighbors buy at retail (~₹8/kWh). **GridZero** enables direct community microgrid sharing:

- **Virtual Feeder Allocation:** Matches prosumer exports to neighbor imports across homes on the same feeder via virtual net metering—no dedicated wiring required.
- **Dual Forecaster:** Predicts household load and solar generation using LightGBM quantile regression ($P_{10}, P_{50}, P_{90}$) with live Open-Meteo solar irradiance.
- **Three Allocation Modes:** Evaluates **Static** (water-filling equal share), **Dynamic** (priority queue), and **Hybrid** (base share + priority) policies benchmarked on Jain's Fairness Index.
- **Decoupled Settlement:** Kilowatt-hour units reassign on utility bills; money clears peer-to-peer at dynamic mid-market rates (₹3.00–₹7.50) with a ₹0.50/kWh DISCOM wheeling charge.
- **GenAI Advisory:** Amazon Bedrock (Nova Lite) with SHAP attribution for plain-English dispatch guidance and weather-shock alerts.

---

## System Architecture

```mermaid
flowchart TD
    subgraph UI ["Frontend · Next.js 16 (Port 3000)"]
        Views["Live Feeder Flow · Dashboard · Policy Comparison · Statement"]
        Controls["Simulation Controls & Load Injection (POST /inject)"]
    end

    subgraph SIM ["Simulation Engine · FastAPI (Port 8000)"]
        SimServer["Async Simulation Loop (server.py)"]
        Meters["Virtual Smart Meters & Batteries (10 Nodes)"]
        ForecastClient["Forecast Client (forecast.py · Baseline Fallback)"]
        Allocators["Matching Policies: Static, Dynamic, Hybrid"]
        Pricing["Dynamic Scarcity Pricing (₹3.00 - ₹7.50 / kWh)"]
        DB["SQLite Database (p2p.db Ledger & Telemetry)"]
        
        SimServer --> Meters
        Meters --> ForecastClient
        ForecastClient --> Allocators
        Allocators --> Pricing
        Pricing --> DB
    end

    subgraph ML ["ML & Intelligence Service · FastAPI (Port 8001)"]
        MLServer["Inference API (POST /predict)"]
        Weather["Open-Meteo API (Solar GHI, DNI, Cloud Cover)"]
        LGBM["LightGBM Quantile Forecaster (P10, P50, P90)"]
        SHAP["SHAP TreeExplainer (Feature Attribution)"]
        Bedrock["Amazon Bedrock Agent (Nova Lite / Claude 3)"]
        
        Weather --> LGBM
        MLServer --> LGBM
        LGBM --> SHAP
        SHAP --> Bedrock
    end

    subgraph Settlement ["Settlement & Physical Grid"]
        DISCOM["DISCOM Utility (Virtual Net-Metering + ₹0.50/kWh Fee)"]
        Wallet["Platform Wallet (P2P Rupee Clearing)"]
    end

    UI -->|Next.js Proxy /engine| SimServer
    ForecastClient -->|POST /predict| MLServer
    Allocators -->|Grid Import / Export Balance| DISCOM
    Pricing -->|P2P Rupee Settlement| Wallet
```

---

## Tech Stack

| Layer | Technologies |
|---|---|
| **Frontend** | Next.js 16, React 19, Tailwind CSSand SWR |
| **Backend** | FastAPI and Uvicorn |
| **Storage** | Amazon S3 and SQLite |
| **AI/ML** | LightGBM, SHAP and Amazon Bedrock |
| **Data & APIs** | Open-Meteo Weather API |
| **Simulation** | Discrete-Event Engine and Virtual Smart Meters |
