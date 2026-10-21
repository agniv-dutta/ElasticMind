# STABILIZATION_AUDIT

This audit was produced by inspecting the repository (modules, configs, tests) as requested. All file paths are relative to the repo root. Test run included at the end.

## 1) Where is the trained LightGBM model loaded in the backend, and is the artifact present inside the backend container?

**Loading locations (backend):**
- `backend/app/main.py:43` imports `load_predictor` from `ml.models.registry`.
- `backend/app/main.py:121-124` in `predict()` does `load_predictor(settings.model_path)` inside `try/except` and returns HTTP 500 if it fails.
- `backend/app/main.py:257-259` in `control_loop_worker()` does `hist = generate_workload(...)`, `model = load_predictor(settings.model_path)`, `fc = model.predict(hist.tail(480))` every loop iteration (with `try/except` that keeps the loop alive on failure, lines ~329-331).
- `backend/app/core/config.py:41` sets `model_path: str = "ml/models/artifacts/lightgbm.joblib"`.
- `backend/app/aws/model_store.py:43-91` provides `load_model_from_s3(uri, local_dir, region, ...)` which downloads from S3 to `local_dir` and falls back to `local_fallback`; on AWS (`settings.actuator == "aws"`), `backend/app/main.py:64-70` calls `load_model_from_s3(settings.model_s3_uri, region=settings.aws_region)` best-effort during lifespan.
- `ml/models/registry.py:1-60` (exists in repo) provides `load_predictor/save_predictor` and lists registered model types.

**Artifact presence (repo state):**
- `ml/models/artifacts/` exists (directory). `ml/models/` contains `__init__.py`, `artifacts/`, `base.py`, `holt_winters.py`, `lightgbm_model.py`, `lstm.py`, `reactive.py`, `registry.py`.
- No `.joblib` files are visible in the tracked tree from `README` / layout, but `ml/train.py` writes to `ml/models/artifacts/*.joblib(.meta.json)`. The backend defaults to `ml/models/artifacts/lightgbm.joblib` (config). If missing, `/predict` raises 500 and the control loop will catch exceptions and `continue` (main.py:329-331), so the loop stays alive but decisions may fail until a model is present.

**Inside the backend container (Docker):**
- `infra/docker/backend.Dockerfile`:
  - copies `ml/`, `backend/`, `experiments/` (lines copying dirs)
  - runs `pip install -e ./ml -e ./backend` 
  - sets `CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]`
- **Verdict:** The image build copies `ml/` into the container but does **not** copy `ml/models/artifacts/` unless they exist at build time in the build context and are not excluded. `.gitignore` is present at root; trained artifacts may not be committed. Also `docker-compose.yml` (local) does not mount artifacts explicitly — it mounts source directories in dev? Let us check: `docker-compose.yml` has services `backend` building from `infra/docker/backend.Dockerfile` with no obvious artifact mount shown. The Terraform task definition (`infra/terraform/ecs.tf`) sets `ELASTICMIND_MODEL_S3_URI` and the backend attempts to load from S3 on AWS (`main.py:64-70`), else falls back to local path. **Conclusion:** Artifacts are **not guaranteed present** inside the backend container by default; they must be provided via (a) build-time copy of committed artifacts, (b) a mounted volume in local compose, or (c) S3 download on AWS startup. This is a potential runtime failure point (see fixes).

## 2) Trace one control-loop tick: metrics in -> forecast -> capacity calc -> policy -> safety net -> actuator. Which step produces the final desired count, and when does the safety net override the ML forecast?

**Trace (per iteration):** `backend/app/main.py:239-333` `control_loop_worker()`.

1. **Sleep / tick**: `await asyncio.sleep(settings.loop_interval_s)` (line 254). `settings` from `backend/app/core/config.py:27-59` (`loop_interval_s=60`, `policy`, `actuator`, etc.).
2. **Get history / metrics input**: `hist = generate_workload(profile="diurnal", days=1, seed=42)[["timestamp", "requests"]]` (line 256). **"Actual" load observed** = `actual = float(hist["requests"].iloc[-1])` (line 263).
3. **Forecast**: `model = load_predictor(settings.model_path)` (257), `fc = model.predict(hist.tail(480))` (258), `h = min(settings.horizon_min, max(model.horizons))` (259), `p50, p90 = fc.latest(h)` (260). Forecast is produced by the loaded predictor (ML).
4. **Observe error / update robust state**: if `prev_pred` exists, `robust.observe(prev_pred, actual)` (264-265), `prev_pred = p50` (266). `robust` is `SafeguardedController` created at line ~248-250.
5. **Capacity/utilization calc**: `cap = robust._loop.state.current_instances * cfg.capacity_per_instance` (268), `util_now = actual / max(cap, 1e-6)` (269). Uses `AutoscalerConfig` (`backend/app/autoscaler/config.py:10-28`) defaults: `capacity_per_instance=100.0`, `target_utilization=0.70`, `headroom=0.20`, cooldowns/hysteresis as specified.
6. **Policy/safety net evaluation**: `dec = robust.step(predicted_load_p50=p50, predicted_load_p90=p90, current_capacity=cap, current_utilization=util_now, current_instances=act.current(), now=asyncio.get_event_loop().time())` (270-277). `SafeguardedController` is in `backend/app/robustness/safeguards.py`.
7. **Actuation**: `act.set_desired(dec.desired)` (278). Actuator from `backend/app/main.py:77-89` (`LocalSimActuator` or `AwsEcsActuator` depending on `settings.actuator`). Optional CloudWatch publish if `app.state.metrics_pub` exists (280-299).
8. **Persist**: writes `Decision` and `Metric` to SQLite via `SessionLocal()` (299-326).

**Which step produces the final desired count?**
- **`SafeguardedController.step()` produces the final decision object `dec` with `dec.desired`** (and reason/action). That decision is passed directly to the actuator (`act.set_desired(dec.desired)`). The base `ControlLoop.evaluate()` inside the safeguarded controller produces an intermediate decision, but **the safety net can override it** (see below).

**When does the safety net override the ML forecast?** (`backend/app/robustness/safeguards.py`):
- **Safety net (immediate right-size on high utilization):** In `SafeguardedController.step()` (lines ~120-185), if `current_utilization is not None and current_utilization >= self.trigger_utilization` (default `trigger_utilization = 0.9`, set in `__init__` line ~70-90), it sets `self.state.safety_net_triggered = True`, computes `observed_load = current_utilization * max(current_capacity, 1.0)`, computes `needed = ceil(observed_load * (1.0 + self.base_headroom) / eff)` where `eff = self.cfg.capacity_per_instance * self.cfg.target_utilization`, clamps to `[min_instances, max_instances]` and returns a `ScalingDecision` with reason like `"safety_net (util=...) → N inst"` — **overriding the ML forecast-driven decision**.
- **Drift detection / reactive fallback:** `observe(pred_p50, actual)` updates `ForecastErrorTracker` (line ~50-120). If rolling MAPE >= `drift_mape_threshold` (default ~0.25) for enough samples, `drift_alarm` becomes true and after some window `active_mode` switches to `"reactive"` (confidence-aware headroom increased). In fallback/reactive mode the controller may behave more conservatively/reactively (logic in `SafeguardedController` uses tracker state). Also `SafeguardedController.step()` consults `self.tracker.state.drift_alarm` / `active_mode`.
- **Confidence-aware headroom:** applied based on forecast error history (lines ~160-185).
- **Note:** `ControlLoop` itself also has cooldowns/hysteresis (control.py:83-150) — those can block/modify actions but the safety net in `SafeguardedController` can produce a decision that is then applied (and `SafeguardedController` wraps/uses `ControlLoop`).

## 3) Where are cost, energy, utilization and SLA computed? List every place the same metric is computed differently (discrepancies).

### Utilization
- `backend/app/autoscaler/policy.py:36-90` `MLForecastPolicy.compute_desired()`: uses `predicted_load_p90` vs `capacity_needed = ceil(predicted_load_p90 * (1+headroom) / (capacity_per_instance * target_utilization))` (capacity-based).
- `backend/app/main.py:268-269` loop computes `util_now = actual / max(cap, 1e-6)` where `cap = instances * capacity_per_instance` (instantaneous util from observed load).
- `backend/app/simulator/simulator.py:80-200` `WorkloadReplaySimulator.simulate()`: computes utilization per step based on `running_capacity` and arrival/load, tracks SLA violations when load > effective capacity / provisioning delay effects.
- `backend/app/robustness/safeguards.py:133-150` safety net uses `current_utilization >= trigger_utilization` (passed in).
- **Discrepancy:** Utilization is computed as (load/capacity) in different forms (policy uses target-utilization in sizing formula; loop computes observed util as `actual/cap`; simulator computes its own). Units/semantics differ slightly.

### SLA
- `backend/app/simulator/simulator.py` tracks `sla_violations` when demand exceeds provisioned capacity considering `provisioning_delay_s` and `service_rate` (see config: `SimConfig` has `service_rate=100.0`, `sla_latency_ms=200.0` etc., simulator logic). `experiments/run_eval.py` summarizes via `summarize_simulation()`.
- `backend/app/main.py:195` `/metrics/current` returns `sla_count=0` (hardcoded). `backend/app/main.py:302` in loop passes `sla_violations=0` to CloudWatch publisher.
- `backend/app/autoscaler/aws_actuator.py` not directly computing SLA. `backend/tests/test_simulator.py` validates SLA behavior.
- **Discrepancy:** SLA violations are **computed in the simulator** (authoritative for experiments) but **hardcoded to 0 in the live API/loop** (`main.py:195,302`). The dashboard will show simulated experiment results vs live API values that may differ.

### Cost
- `backend/app/main.py:192` `/metrics/current`: `cost_usd = current * (cfg.capacity_per_instance * 0.0001)` (placeholder formula).
- `backend/app/main.py:303` loop publishes `estimated_cost=running * cfg.capacity_per_instance * 0.0001` to CloudWatch.
- `backend/app/simulator/simulator.py` computes cost using `cost_per_instance_hour` and `energy_kwh_per_instance_hour` from `SimConfig` (lines ~50-150 in simulator).
- `experiments/run_eval.py` includes cost in summaries.
- **Discrepancy:** Three different cost formulas (API uses `capacity_per_instance * 0.0001`; simulator uses its own `SimConfig` rates). Values will differ between live API and simulator results.

### Energy
- `backend/app/main.py:193` `/metrics/current`: `energy_kwh = current * 0.05` (placeholder, "simulated").
- `backend/app/simulator/simulator.py` computes energy using `SimConfig.energy_kwh_per_instance_hour`.
- **Discrepancy:** Different constants/formulas.

### Latency
- `backend/app/main.py:191` `/metrics/current`: `latency_ms = 25.0` (hardcoded).
- `loadgen/runner.py:99-108` measures real latency from HTTP requests to target app (`latency_p50_ms`, `latency_p95_ms`).
- `backend/app/simulator/simulator.py` computes latency (M/M/c style) in simulation.
- **Discrepancy:** Live API returns hardcoded latency; loadgen measures real latency; simulator estimates latency differently.

**Summary of discrepancies:** Live endpoints/loop use placeholders/hardcoded values in places (`/metrics/current`, loop passes `sla_violations=0`), while the **simulator/experiments** compute authoritative simulated metrics. This is important for evaluation vs runtime display.

## 4) Which parts use hard-coded constants (capacity per instance, target utilization, prices, power watts)?

### Capacity / utilization / scaling
- `backend/app/autoscaler/config.py:10-28` **`AutoscalerConfig`** defaults: `capacity_per_instance=100.0`, `target_utilization=0.70`, `headroom=0.20`, `min_instances=1`, `max_instances=10`, cooldowns/hysteresis/delays. (Central config)
- `backend/app/simulator/simulator.py:30-60` **`SimConfig`** defaults: `service_rate=100.0`, `provisioning_delay_s=90.0`, `cost_per_instance_hour=0.10`, `energy_kwh_per_instance_hour=0.05`, `latency_sla_ms=200.0`, `latency_base_ms=20.0`.
- `backend/app/main.py:268` uses `cfg.capacity_per_instance` (from `AutoscalerConfig`).
- `backend/app/robustness/safeguards.py` uses `self.cfg.capacity_per_instance` and `self.cfg.target_utilization`.

### Prices / power / cost
- `backend/app/simulator/simulator.py` SimConfig has `cost_per_instance_hour`, `energy_kwh_per_instance_hour`.
- `backend/app/main.py:192,303` hardcoded `capacity_per_instance * 0.0001` (placeholder).
- `backend/app/main.py:193` hardcoded `current * 0.05`.
- `experiments/cost_aware.py:11-40` has `instance_cost_usd_per_hour=0.096`, `sla_penalty_usd_per_violation=5.0`, spot discount/risk.
- `backend/app/aws/metrics.py:65-120` publishes `EstimatedCost` (computed by caller; main passes placeholder).
- `target_app/app.py:1-40` has `TARGET_APP_CPU_BURN_MS` default 40 (configurable via env).

### Other constants
- `loadgen/runner.py` defaults/concurrency/speed factors.
- `backend/app/robustness/safeguards.py` defaults: `trigger_utilization=0.9`, `drift_mape_threshold=0.25`, headroom multipliers.
- `backend/app/autoscaler/aws_actuator.py` defaults for cooldowns/delays.

**Note:** The project states "label every simulated number as \"simulated\" in code and UI" — many places comply (comments/labels), but some live metrics still use placeholders (main.py metrics endpoints/loop).

## 5) What is the current actuator interface and what does LocalSimActuator do?

**Interface:** `backend/app/autoscaler/actuator.py`
- `@dataclass class ScalingAction`: `desired: int`, `current: int`, `reason: str`, `ts: float` (line 10-16).
- `class CapacityActuator(abc.ABC)`: abstract methods `desired()`, `set_desired(desired: int) -> ScalingAction`, `current()`, `apply_delay(action: ScalingAction) -> float` (18-29).
- **Implementations:**
  - `LocalSimActuator` (32-61): in-memory actuator for local simulation.
    - `__init__(self, initial: int = 2, min_c: int = 1, max_c: int = 10, delay_s: float = 90.0)`: clamps initial, stores min/max/delay, `self._last_action_ts = None`.
    - `desired()` returns `self._current` (47-48). `current()` returns `self._current` (50-51).
    - `set_desired(desired: int) -> ScalingAction` (53-58): `d = max(self._min, min(self._max, int(desired)))`, creates `ScalingAction(desired=d, current=self._current, reason="actuator_set", ts=time())`, sets `self._last_action_ts = action.ts`, sets `self._current = d`, returns action. **It updates state immediately (no async delay applied by the actuator itself)** — the provisioning delay is handled by the simulator/logic elsewhere (see `apply_delay` returns `self._delay`).
    - `apply_delay(action: ScalingAction) -> float` returns `self._delay` (60-61).
  - `AwsEcsActuator` (`backend/app/autoscaler/aws_actuator.py`): real ECS actuator using boto3; reads/writes `desiredCount` on ECS service, applies cooldowns/min-max, has `apply_delay()` returning `self._delay` (default 120.0). Activated via `settings.actuator == "aws"` in `main.py:77-89`.

**Usage:** `main.py` gets actuator via `_get_actuator()` (77-89), passes it to control loop logic; `control_loop_worker` calls `act.set_desired(dec.desired)` (278). The simulator uses actuators in its own flow (`backend/app/simulator/simulator.py`).

# Prioritized fix list

### P0 (Critical - correctness/runtime)
1. **Ensure model artifact availability** (`backend/app/main.py:121,257`, `backend/app/core/config.py:41`, `infra/docker/backend.Dockerfile`, `docker-compose.yml`). Either commit/train artifacts, mount them in local compose, or rely on S3 download and fail gracefully with clear errors. Add a startup check that logs model presence.
2. **Fix SLA/cost/energy/latency placeholders in live API** (`backend/app/main.py:182-201`): `/metrics/current` returns hardcoded `sla_count=0`, `latency_ms=25.0`, placeholder cost/energy. Either compute from real data/DB or clearly label as simulated and source from simulator/config.
3. **Fix loop passing `sla_violations=0`** (`backend/app/main.py:302`): should track or compute actual violations.
4. **Make control loop tick interval configurable and consistent** (`backend/app/core/config.py:27-59`, `main.py:254`): ensure behavior matches experiments.

### P1 (High - correctness of metrics)
5. **Consolidate cost/energy formulas** (`backend/app/main.py:192-193,303`, `backend/app/simulator/simulator.py`): use `SimConfig`/`AutoscalerConfig` single source of truth; remove magic numbers.
6. **Unify utilization calculation** across policy/simulator/loop/safety net with documented semantics.
7. **Make safety net thresholds configurable** (`backend/app/robustness/safeguards.py`) and ensure they work with the same config object.

### P2 (Medium - robustness/ops)
8. **Handle model load failures better** (`backend/app/main.py:257-259,329-331`): log errors, expose health/status indicating model loaded.
9. **Document actuator delay semantics** (LocalSimActuator applies delay via `apply_delay()` but sets state immediately; simulator uses it) — add comments/tests.
10. **Add tests for container artifact presence / S3 download fallback**.

# Test results (run on this machine)
Command: `python -m pytest --tb=no -q`  
Result: **84 passed, 1 warning in 74.37s** (warning: PyTorch NumPy API issue, non-blocking)
