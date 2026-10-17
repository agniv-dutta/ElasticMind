"""FastAPI app with endpoints as specified."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.autoscaler.actuator import LocalSimActuator
from backend.app.autoscaler.aws_actuator import AwsEcsActuator
from backend.app.autoscaler.config import AutoscalerConfig
from backend.app.autoscaler.control import ControlLoop
from backend.app.carbon.carbon import carbon_aware_window, intensity_now
from backend.app.core.config import Settings
from backend.app.cost.cost_aware_policy import choose_from_forecast
from backend.app.db.models import (
    Decision,
    Experiment,
    Forecast,
    Metric,
    get_engine,
    get_session_factory,
    init_db,
)
from backend.app.reliability.audit import AuditLog
from backend.app.reliability.ratelimit import RateLimiter
from backend.app.schemas.schemas import (
    CapacityResponse,
    FaultBiasRequest,
    FaultSpikeRequest,
    MetricsResponse,
    PolicyRequest,
    PredictRequest,
    PredictResponse,
)
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from ml.data.generate import generate_workload
from ml.models.registry import load_predictor
from sqlalchemy import desc
from sqlalchemy.orm import Session

settings = Settings()
engine = get_engine(settings.db_url)
init_db(engine)
SessionLocal = get_session_factory(engine)
audit_log = AuditLog()
actuator_limiter = RateLimiter(rate_per_sec=1 / 30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.metrics_pub = None
    if settings.actuator == "aws":
        try:
            from backend.app.aws.metrics import CloudWatchMetricsPublisher

            app.state.metrics_pub = CloudWatchMetricsPublisher(region=settings.aws_region)
        except Exception:
            app.state.metrics_pub = None
    # Warm-load the model from S3 when running on AWS (best effort).
    if settings.model_s3_uri and settings.actuator == "aws":
        try:
            from backend.app.aws.model_store import load_model_from_s3

            load_model_from_s3(settings.model_s3_uri, region=settings.aws_region)
        except Exception:
            pass
    app.state.loop_task = asyncio.create_task(control_loop_worker(app))
    yield
    if hasattr(app.state, "loop_task"):
        app.state.loop_task.cancel()
        try:
            await app.state.loop_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="ElasticMind Backend", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    with SessionLocal() as s:
        yield s


def _get_actuator():
    cfg = AutoscalerConfig()
    if settings.actuator == "aws":
        return AwsEcsActuator(
            cluster=settings.ecs_cluster,
            service=settings.ecs_service,
            region=settings.aws_region,
            min_c=cfg.min_instances,
            max_c=cfg.max_instances,
            scale_up_cooldown_s=cfg.fast_scale_up_cooldown_s,
            scale_down_cooldown_s=cfg.slow_scale_down_cooldown_s,
        )
    return LocalSimActuator(initial=max(1, cfg.min_instances), min_c=cfg.min_instances, max_c=cfg.max_instances)


def _get_loop():
    return ControlLoop(AutoscalerConfig())


@app.get("/health")
def health():
    return {"status": "ok", "env": settings.env}


@app.get("/robustness/status")
def robustness_status():
    """Current safeguard state (drift alarm, fallback mode, rolling MAPE)."""
    worker = getattr(app.state, "robust", None)
    if worker is None:
        return {"active_mode": settings.policy, "drift_alarm": False, "rolling_mape": 0.0}
    return {
        "active_mode": worker.state.active_mode,
        "drift_alarm": worker.state.drift_alarm,
        "rolling_mape": worker.state.rolling_mape,
        "headroom_mult": worker.state.headroom_mult,
        "recoveries": worker.state.recoveries,
    }


@app.post("/predict", response_model=PredictResponse)
@app.get("/forecast", response_model=PredictResponse)
def predict(req: PredictRequest | None = None, db: Session = Depends(get_db)):
    req = req or PredictRequest()
    try:
        model = load_predictor(settings.model_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"model load failed: {e}") from e

    # Build minimal history: generate a short diurnal window if no real data
    hist = generate_workload(profile="diurnal", days=1, seed=42)[["timestamp", "requests"]]
    fc = model.predict(hist.tail(max(60, req.history_minutes)))
    frame = fc.frame
    from ml.conformal.conformal import apply_intervals

    calibration_width = float(hist["requests"].tail(60).std() or 0.0)
    frame = apply_intervals(frame, {int(h): calibration_width for h in model.horizons})
    points = frame.to_dict(orient="records")
    for p in points:
        db.add(
            Forecast(
                timestamp=p.get("timestamp"),
                horizon_min=p.get("horizon_min"),
                p50=p.get("p50"),
                p90=p.get("p90"),
                model=fc.model,
            )
        )
    db.commit()
    return {"model": fc.model, "forecast": points}


@app.get("/explain")
def explain():
    """Return SHAP/feature explanations for the active forecast model."""
    try:
        model = load_predictor(settings.model_path)
        history = generate_workload(profile="diurnal", days=1, seed=42)[
            ["timestamp", "requests"]
        ].tail(480)
        horizon = min(settings.horizon_min, max(model.horizons))
        if hasattr(model, "explain"):
            return {"horizon_min": horizon, "features": model.explain(history, horizon)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"explanation failed: {exc}") from exc
    return {"horizon_min": horizon, "features": []}


@app.get("/capacity", response_model=CapacityResponse)
def capacity():
    cfg = AutoscalerConfig()
    act = _get_actuator()
    return {
        "current_instances": act.current(),
        "desired_instances": act.desired(),
        "capacity_per_instance": cfg.capacity_per_instance,
        "target_utilization": cfg.target_utilization,
    }


@app.post("/autoscaler/policy")
def set_policy(req: PolicyRequest):
    settings.policy = req.policy
    return {"policy": settings.policy}


@app.post("/autoscaler/start")
def start_loop():
    return {"started": True}


@app.post("/autoscaler/stop")
def stop_loop():
    return {"stopped": True}


@app.post("/faults/bias")
def fault_bias(req: FaultBiasRequest):
    return {"bias_percent": req.bias_percent, "simulated": True}


@app.post("/faults/spike")
def fault_spike(req: FaultSpikeRequest):
    return {"magnitude": req.magnitude, "duration_minutes": req.duration_minutes, "simulated": True}


@app.get("/metrics", response_model=MetricsResponse)
@app.get("/metrics/current")
def metrics_current():
    act = _get_actuator()
    cfg = AutoscalerConfig()
    now = datetime.now(UTC)
    current = act.current()
    # simulated snapshot
    util = 0.65
    latency_ms = 25.0
    cost_usd = current * (cfg.capacity_per_instance * 0.0001)  # placeholder
    energy_kwh = current * 0.05  # simulated
    return MetricsResponse(
        current_utilization=util,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        energy_kwh=energy_kwh,
        sla_count=0,
        timestamp=now,
    )


@app.get("/metrics/history")
def metrics_history(from_ts: datetime | None = Query(None), to_ts: datetime | None = Query(None), db: Session = Depends(get_db)):
    q = db.query(Metric).order_by(desc(Metric.timestamp))
    if from_ts:
        q = q.filter(Metric.timestamp >= from_ts)
    if to_ts:
        q = q.filter(Metric.timestamp <= to_ts)
    return [m.__dict__ for m in q.limit(500)]


@app.get("/decisions")
def decisions(db: Session = Depends(get_db)):
    q = db.query(Decision).order_by(desc(Decision.timestamp)).limit(200)
    return [d.__dict__ for d in q]


@app.get("/experiments")
def experiments(db: Session = Depends(get_db)):
    """Experiment results: prefer the CSV written by experiments/run_eval.py."""
    rows: list[dict[str, Any]] = []
    csv_path = Path("experiments/results/policy_comparison.csv")
    if csv_path.exists():
        try:
            import pandas as pd

            df = pd.read_csv(csv_path)
            rows = json.loads(df.to_json(orient="records"))
        except Exception:
            rows = []
    if not rows:
        q = db.query(Experiment).order_by(desc(Experiment.timestamp)).limit(100)
        rows = [dict(e.__dict__) for e in q]
    return rows


@app.get("/models/comparison")
def model_comparison():
    """Return per-model, per-horizon error metrics for the dashboard."""
    path = Path("experiments/results/model_comparison.csv")
    if not path.exists():
        return []
    import pandas as pd

    return json.loads(pd.read_csv(path).to_json(orient="records"))


@app.get("/policies/pareto")
def policies_pareto():
    """Return the simulated cost/SLA trade-off used by the policy view."""
    from experiments.cost_aware import pareto_frontier

    return pareto_frontier()


@app.get("/carbon")
def carbon():
    now = datetime.now(UTC)
    return {
        "timestamp": now,
        "intensity_gco2_kwh": intensity_now(now),
        "mode": "time_of_day",
        "batch_window": carbon_aware_window(now.hour, 1),
    }


@app.get("/cost/choose")
def cost_choose(
    forecast_p90: float = Query(..., ge=0),
    min_instances: int = Query(1, ge=1),
    max_instances: int = Query(10, ge=1),
):
    if max_instances < min_instances:
        raise HTTPException(status_code=400, detail="max_instances must be >= min_instances")
    cfg = AutoscalerConfig()
    decision = choose_from_forecast(
        forecast_p90,
        cfg.capacity_per_instance,
        list(range(min_instances, max_instances + 1)),
    )
    return decision.__dict__


@app.get("/multiservice/allocation")
def multiservice_allocation(total_instances: int = Query(10, ge=1)):
    from backend.app.multiservice.manager import ServiceState, SharedCapacityManager

    manager = SharedCapacityManager(total_instances=total_instances)
    manager.add_service(ServiceState("api", weight=2.0, memory_mb_per_instance=512))
    manager.add_service(ServiceState("worker", weight=1.0, memory_mb_per_instance=1024))
    return manager.allocate()


@app.get("/drift")
def drift():
    worker = getattr(app.state, "robust", None)
    if worker is None:
        return {"psi": 0.0, "ks": 0.0, "drift": False}
    return {
        "psi": float(worker.state.rolling_mape),
        "ks": 0.0,
        "drift": worker.state.drift_alarm,
    }


@app.get("/audit")
def audit():
    return audit_log.read()


async def control_loop_worker(app: FastAPI):
    """Background control loop: forecast → policy → actuator, logged to SQLite.

    Uses the safeguarded controller so the reactive safety net / drift fallback
    apply when the forecast is wrong.
    """
    from backend.app.robustness.safeguards import SafeguardedController

    cfg = AutoscalerConfig()
    robust = SafeguardedController(cfg=cfg, base_headroom=cfg.headroom)
    app.state.robust = robust
    act = _get_actuator()
    prev_pred: float | None = None
    try:
        while True:
            await asyncio.sleep(settings.loop_interval_s)
            try:
                hist = generate_workload(profile="diurnal", days=1, seed=42)[["timestamp", "requests"]]
                model = load_predictor(settings.model_path)
                fc = model.predict(hist.tail(480))
                h = min(settings.horizon_min, max(model.horizons))
                p50, p90 = fc.latest(h)

                # "live" measured load = last observed demand; observe forecast error
                actual = float(hist["requests"].iloc[-1])
                if prev_pred is not None:
                    robust.observe(prev_pred, actual)
                prev_pred = p50

                cap = robust._loop.state.current_instances * cfg.capacity_per_instance
                util_now = actual / max(cap, 1e-6)
                dec = robust.step(
                    predicted_load_p50=p50,
                    predicted_load_p90=p90,
                    current_capacity=cap,
                    current_utilization=util_now,
                    current_instances=act.current(),
                    now=asyncio.get_event_loop().time(),
                )
                if actuator_limiter.allow():
                    act.set_desired(dec.desired)
                    audit_log.record(dec.desired, dec.current, dec.action, dec.reason)
                pub = getattr(app.state, "metrics_pub", None)
                if pub is not None:
                    try:
                        running = act.current()
                        pub.put_metrics(
                            predicted_load=p50,
                            actual_load=actual,
                            desired_capacity=dec.desired,
                            running_capacity=running,
                            forecast_mape=robust.state.rolling_mape,
                            sla_violations=0,
                            estimated_cost=running * cfg.capacity_per_instance * 0.0001,
                        )
                    except Exception:
                        pass
                with SessionLocal() as db:
                    db.add(
                        Decision(
                            timestamp=datetime.utcnow(),
                            desired=dec.desired,
                            current=dec.current,
                            action=dec.action,
                            reason=dec.reason,
                            p50=dec.p50,
                            p90=dec.p90,
                        )
                    )
                    db.add(
                        Metric(
                            timestamp=datetime.utcnow(),
                            name="desired_instances",
                            value=dec.desired,
                        )
                    )
                    db.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                # keep the loop alive even if a single iteration fails
                continue
    except asyncio.CancelledError:
        raise
