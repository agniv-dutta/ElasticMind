# ElasticMind Assumptions and Limitations (Simulated vs Measured)

Metrics carry provenance: values computed from simulator inputs are labelled
**simulated**; values received from the load generator or cloud telemetry are
labelled **measured**. Local load-generator observations measure the test run,
not production traffic. Energy is always labelled **estimated**.

## Shared metric formulas

`backend/app/metrics/calculator.py` is the only implementation of utilization,
SLA violation, latency, cost, and energy calculations. API, simulator, and
experiments must call it rather than reimplement these formulas.

- **Utilization** = `served_load / (running_replicas x capacity_per_replica)`.
  It may exceed 1 during overload; a zero running capacity yields zero.
- **SLA violations**: one violation per interval if demand exceeds total
  running capacity or latency exceeds `SLA_LATENCY_MS`.
- **Latency**: measured latency when supplied by telemetry; otherwise the
  simulator's documented M/M/c-style approximation.
- **Cost** = `replica-seconds x price_per_second`. Starting and draining
  replicas are billed during transitions.
- **Energy (estimated)** = sum over replicas of
  `(idle_w + (peak_w - idle_w) x util) x dt`, converted from joules to kWh.
  The utilization for power interpolation is bounded to [0, 1].

## Workload and data

- The traces used are synthetic (diurnal/steady/spiky) or user-supplied CSVs
  resampled to 1-minute buckets. Flash spikes, sudden drops and regime shifts
  are artificially injected (simulated).
- No real user behaviour, request bodies or IP distributions are represented.

## Forecasting

- P50/P90 come from deterministic predictors (baseline, Holt-Winters,
  LightGBM). Holt-Winters uses in-sample residual std to derive P90 — a
  documented approximation.
- Feature engineering uses lags, rolling mean/std, cyclical encodings and
  rate-of-change, all derived from the history series (no exogenous real data).
- Chronological train/val/test splits (no leakage) are used. Generalisation to
  a live production workload is unverified.

## Queueing and latency

- Simulated latency uses a M/M/c-style approximation (not a packet-level
  simulation). Values are used for comparison between policies, not for SLO
  guarantees.

## Capacity and scaling

- A fixed **service_rate** (requests per instance per minute) and
  **capacity_per_instance** are assumed. Real CPU/memory/headroom vary.
- **Provisioning delay** is treated as a fixed window (60–120 s in the
  simulator) and actuator decisions may lag by that amount.
- The local actuator has no real infrastructure effect.

## Cost, energy and carbon

- Instance cost is a placeholder price (USD per instance-hour) and may not
  match a specific AWS region or SKU.
- Power model: linear interpolation between **power_idle_w** and
  **power_max_w** by simulated utilization — a coarse approximation.
- **co2_kg_per_kwh** is a static regional value or time-of-day profile (when
  enabled) and treated as **simulated**.
- CloudWatch metrics in AWS mode are published as custom metrics; the dollar
  cost shown in the dashboard is an **estimated/simulated** running cost.

## Evaluation and robustness

- The simulator replays the trace at 1-minute resolution. Speed-up factors in
  ``loadgen`` are for demo convenience and do not imply real-time accuracy.
- SLA violations are defined as ``demand > total_capacity`` at that minute
  (a coarse binary). Cooling periods, retries and circuit breakers are not
  modelled.
- Misprediction scenarios (±50%, sudden spike) are scripted; recovery time and
  over-provisioning waste are also **simulated**.

## What would be needed for production

1. Validate against real traces and measure actual provisioning delays.
2. Replace the queueing approximation with a proper performance model or live
   measurements.
3. Calibrate power/cost/carbon parameters for the target region and instances.
4. Add safety constraints (multi-resource: CPU+memory, health checks, AZ
   spreading, limits on scale rate).
5. Guardrails against model drift (data drift, PSI/KS) and automated retraining
   with version promotion gates.
6. Audit logging, blast radius controls, rate limiting and graceful rollback.
