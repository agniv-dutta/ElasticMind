# ElasticMind Architecture

> All values labelled *simulated* are produced by the local simulator/power
> model, not by real cloud infrastructure.

## System diagram

```mermaid
flowchart LR
    subgraph Traffic
        LG[loadgen<br/>Python async HTTP]
    end

    subgraph Scaled service
        TA[target_app<br/>FastAPI /work]
    end

    subgraph Control plane
        MC[metrics collector<br/>backend]
        DB[(SQLite<br/>metrics / forecasts<br/>decisions / experiments)]
        P[predictor<br/>LightGBM P50/P90]
        AS[autoscaler<br/>control loop]
        CA[capacity actuator<br/>LocalSim | AwsEcs]
    end

    subgraph Visualization
        DASH[React dashboard<br/>Vite + Recharts]
    end

    LG -->|HTTP load| TA
    TA -->|latency, request counts| MC
    MC -->|persist| DB
    DB --> P
    P -->|forecast P50/P90| AS
    AS -->|desired instances| CA
    CA -->|scale| TA
    DB -->|JSON API| DASH
    MC -->|POST /predict, faults| DASH
    DASH -->|policy switch, start/stop| AS
```

## Data flow in words

1. **loadgen** replays a workload trace (or synthetic profile) as real HTTP
   traffic against **target_app**, at a configurable speed-up factor.
2. **target_app** burns configurable CPU per request and reports its own
   per-request latency.
3. The **backend metrics collector** records measured request counts and
   latency, plus *simulated* utilization/cost/energy derived from the
   power/cost model, into **SQLite**.
4. The **predictor** engineers features (lags, rolling stats, cyclical
   encodings) and forecasts demand at 5/15/30-minute horizons with P50 and P90
   quantiles.
5. The **autoscaler** control loop converts the P90 forecast into a desired
   instance count using headroom, target utilization, min/max bounds,
   cooldowns and hysteresis, then calls the **capacity actuator**
   (`LocalSimActuator` locally, `AwsEcsActuator` on AWS).
6. The **React dashboard** polls the backend API every 5 s and renders
   actual vs predicted load, capacity, utilization, latency, cost, energy,
   SLA violations and the scaling decision log.

## Assignment stage mapping

| Stage | Where |
|---|---|
| Problem | `docs/REPORT_TEMPLATE.md` |
| Identify (data/features) | `ml/data/`, `ml/features/` |
| Choose (algorithm + horizon) | `ml/models/`, `experiments/results/model_comparison.csv` |
| Design (allocation) | `backend/app/autoscaler/` |
| Evaluate | `backend/app/simulator/`, `experiments/run_eval.py` |
| Discuss (wrong predictions) | Prompt 9 safeguards, `docs/ASSUMPTIONS.md` |
