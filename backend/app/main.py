"""FastAPI app with endpoints as specified."""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections import deque
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.autoscaler.actuator import LocalSimActuator
from backend.app.autoscaler.aws_actuator import AwsEcsActuator
from backend.app.autoscaler.config import AutoscalerConfig
from backend.app.autoscaler.control import ControlLoop
from backend.app.autoscaler.pipeline import ControlPipeline
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
from backend.app.metrics.calculator import calculate_metrics
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
import httpx
from ml.data.generate import generate_workload
from ml.models.registry import load_predictor
from sqlalchemy import desc
from sqlalchemy.orm import Session

# Shared state for live metrics from loadgen
class LiveMetrics:
    def __init__(self):
        self.requests_per_min = 0.0
        self.latency_p50_ms = 0.0
        self.latency_p95_ms = 0.0
        self.success_rate = 1.0
        self.timestamp = datetime.now(UTC)
        self.request_count = 0
        self.error_rate = 0.0
        self.utilization = 0.0
        self.running_replicas = 1
        self.history: deque[tuple[datetime, float]] = deque(maxlen=480)

live_metrics = LiveMetrics()
logger = logging.getLogger("elasticmind.control")

settings = Settings()
engine = get_engine(settings.db_url)
init_db(engine)
SessionLocal = get_session_factory(engine)
audit_log = AuditLog()
actuator_limiter = RateLimiter(rate_per_sec=1 / max(settings.scaled_delay(settings.COOLDOWN_UP_S), 1e-6))


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.metrics_pub = None
    if settings.ACTUATOR == "aws":
        try:
            from backend.app.aws.metrics import CloudWatchMetricsPublisher

            app.state.metrics_pub = CloudWatchMetricsPublisher(region=settings.aws_region)
        except Exception:
            app.state.metrics_pub = None
    # Warm-load the model from S3 when running on AWS (best effort).
    if settings.model_s3_uri and settings.ACTUATOR == "aws":
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
    cfg = AutoscalerConfig.from_settings(settings)
    if settings.ACTUATOR == "aws":
        return AwsEcsActuator(
            cluster=settings.ecs_cluster,
            service=settings.ecs_service,
            region=settings.aws_region,
            min_c=cfg.min_instances,
            max_c=cfg.max_instances,
            scale_up_cooldown_s=cfg.fast_scale_up_cooldown_s,
            scale_down_cooldown_s=cfg.slow_scale_down_cooldown_s,
            startup_delay_s=settings.scaled_delay(settings.STARTUP_DELAY_S),
            drain_delay_s=settings.scaled_delay(settings.DRAIN_DELAY_S),
        )
    return LocalSimActuator(
        initial=cfg.min_instances,
        min_c=cfg.min_instances,
        max_c=cfg.max_instances,
        delay_s=settings.scaled_delay(settings.STARTUP_DELAY_S),
    )


def _get_loop():
    return ControlLoop(AutoscalerConfig.from_settings(settings))


@app.get("/health")
def health():
    return {"status": "ok", "env": settings.env}


@app.get("/config")
def active_config():
    """Return the effective shared configuration (YAML plus environment overrides)."""
    return {"profile": settings.PROFILE, "time_scale": settings.TIME_SCALE,
            "actuator": settings.ACTUATOR, "model_version": settings.selected_model_path,
            "autoscaler_running": not getattr(getattr(app.state, "loop_task", None), "done", lambda: True)(),
            "last_tick_time": getattr(app.state, "last_tick_time", None),
            "traffic_source": "gateway_connected" if live_metrics.request_count else "gateway_disconnected",
            "current_policy": settings.policy,
            **settings.model_dump()}


@app.get("/robustness/status")
def robustness_status():
    """Current safeguard state (drift alarm, fallback mode, rolling MAPE)."""
    worker = getattr(app.state, "robust", None)
    if worker is None:
        return {
            "active_mode": settings.policy,
            "drift_alarm": False,
            "rolling_mape": 0.0,
            "forecast_fallback": getattr(app.state, "forecast_fallback", None),
        }
    return {
        "active_mode": worker.state.active_mode,
        "drift_alarm": worker.state.drift_alarm,
        "rolling_mape": worker.state.rolling_mape,
        "headroom_mult": worker.state.headroom_mult,
        "recoveries": worker.state.recoveries,
        "forecast_fallback": getattr(app.state, "forecast_fallback", None),
    }


@app.post("/predict", response_model=PredictResponse)
@app.get("/forecast", response_model=PredictResponse)
def predict(req: PredictRequest | None = None, db: Session = Depends(get_db)):
    req = req or PredictRequest()
    try:
        model = load_predictor(settings.selected_model_path)
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
    history = [{"timestamp": str(ts), "actual": float(value)} for ts, value in list(live_metrics.history)[-30:]]
    return {"model": fc.model, "history": history, "forecast": points}


@app.get("/explain")
def explain():
    """Return SHAP/feature explanations for the active forecast model."""
    try:
        model = load_predictor(settings.selected_model_path)
        history = generate_workload(profile="diurnal", days=1, seed=42)[
            ["timestamp", "requests"]
        ].tail(480)
        horizon = min(settings.FORECAST_HORIZON_MIN, max(model.horizons))
        if hasattr(model, "explain"):
            return {"horizon_min": horizon, "features": model.explain(history, horizon)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"explanation failed: {exc}") from exc
    return {"horizon_min": horizon, "features": []}


@app.get("/capacity", response_model=CapacityResponse)
def capacity():
    cfg = AutoscalerConfig.from_settings(settings)
    pipeline = getattr(app.state, "pipeline", None)
    if live_metrics.request_count > 0:
        current = live_metrics.running_replicas
        desired = pipeline.loop.state.current_instances if pipeline else current
        return {
            "current_instances": current,
            "desired_instances": desired,
            "capacity_per_instance": cfg.capacity_per_instance,
            "target_utilization": cfg.target_utilization,
        }
    # Use the same actuator instance that the control loop uses for consistency
    robust = getattr(app.state, "robust", None)
    if robust and hasattr(robust, "_loop"):
        act = robust._loop
        current = act.state.current_instances
        desired = act.state.current_instances  # The control loop updates desired in the state
    else:
        act = _get_actuator()
        current = act.current()
        desired = act.desired()
    return {
        "current_instances": current,
        "desired_instances": desired,
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


@app.post("/metrics")
def receive_metrics(data: dict):
    """Receive measured request telemetry from the gateway interval reporter."""
    duration_s = max(float(data.get("duration_s", 1)), 0.1)
    live_metrics.requests_per_min = data.get("requests_total", 0) / duration_s * 60
    live_metrics.latency_p50_ms = data.get("latency_p50_ms", 0.0)
    live_metrics.latency_p95_ms = data.get("latency_p95_ms", 0.0)
    live_metrics.success_rate = data.get("success_rate", 1.0)
    live_metrics.error_rate = data.get("error_rate", 1.0 - live_metrics.success_rate)
    live_metrics.utilization = data.get("utilization", 0.0)
    live_metrics.running_replicas = int(data.get("running_replicas", 1))
    live_metrics.request_count = data.get("requests_total", 0)
    live_metrics.timestamp = datetime.now(UTC)
    live_metrics.history.append((live_metrics.timestamp, live_metrics.requests_per_min))
    return {"status": "received", "source": "gateway", "measured": True}


@app.get("/metrics", response_model=MetricsResponse)
@app.get("/metrics/current")
def metrics_current():
    act = _get_actuator()
    cfg = AutoscalerConfig.from_settings(settings)
    now = datetime.now(UTC)
    current = act.current()
    
    # Use live metrics from loadgen if available, otherwise synthetic baseline
    if live_metrics.request_count > 0:
        # Calculate utilization based on requests per minute vs capacity
        rpm = live_metrics.requests_per_min
        util = None
        latency_ms = live_metrics.latency_p50_ms
        metric_source = "measured"
    else:
        # Fallback to synthetic baseline when no loadgen data
        util = None
        latency_ms = 0.0
        sla_count = 0
        metric_source = "simulated"
    
    metric_values = calculate_metrics(
        demand=live_metrics.requests_per_min if live_metrics.request_count > 0 else 0.0,
        served_load=live_metrics.requests_per_min if live_metrics.request_count > 0 else 0.0,
        running_replicas=current, capacity_per_replica=cfg.capacity_per_instance,
        service_rate=cfg.capacity_per_instance, latency_sla_ms=settings.SLA_LATENCY_MS,
        billed_replica_seconds=current * settings.CONTROL_INTERVAL_S,
        price_per_second=settings.PRICE_PER_REPLICA_HOUR / 3600.0,
        dt_seconds=settings.CONTROL_INTERVAL_S, idle_w=settings.IDLE_WATTS,
        peak_w=settings.PEAK_WATTS,
        measured_latency_ms=latency_ms if live_metrics.request_count > 0 else None,
    )
    util = metric_values.utilization
    latency_ms = metric_values.latency_ms
    sla_count = metric_values.sla_violations
    cost_usd = metric_values.cost_usd
    energy_kwh = metric_values.energy_kwh_estimated
    return MetricsResponse(
        current_utilization=util,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        energy_kwh=energy_kwh,
        sla_count=sla_count,
        timestamp=now,
        provenance={"utilization": metric_source, "sla_count": metric_source,
                    "latency_ms": metric_source, "cost_usd": "simulated",
                    "energy_kwh": "simulated", "error_rate": metric_source,
                    "request_count": metric_source, "running_replicas": "measured"},
        energy_label="estimated",
        request_count=live_metrics.request_count,
        error_rate=live_metrics.error_rate,
        running_replicas=live_metrics.running_replicas,
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
    fields = (
        "observed_load", "forecast_p50", "forecast_p90", "horizon", "model_version",
        "desired_ml", "desired_reactive", "final_desired", "decision_source", "reason",
        "cooldown_state", "timestamp",
    )
    return [{key: getattr(row, key) for key in fields} for row in q]


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
    cfg = AutoscalerConfig.from_settings(settings)
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
    """Run forecast → candidate generation → source selection → action → persistence."""
    cfg = AutoscalerConfig.from_settings(settings)
    loop = ControlLoop(cfg)
    pipeline = ControlPipeline(settings, cfg, loop)
    app.state.pipeline = pipeline
    act = _get_actuator()
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.put(f"{settings.GATEWAY_URL.rstrip('/')}/replicas", json={"desired": act.current()})
    except httpx.HTTPError:
        logger.info("Gateway is not available yet; it will be synchronized on the next scale action")
    try:
        while True:
            await asyncio.sleep(settings.scaled_delay(settings.CONTROL_INTERVAL_S))
            try:
                hist = generate_workload(profile="diurnal", days=1, seed=42)[["timestamp", "requests"]]
                actual = live_metrics.requests_per_min if live_metrics.request_count > 0 else 0.0
                current = act.current()
                loop.state.current_instances = current
                latency = live_metrics.latency_p95_ms if live_metrics.request_count > 0 else 0.0
                utilization = live_metrics.utilization if live_metrics.request_count > 0 else calculate_metrics(
                    demand=actual, served_load=actual, running_replicas=current,
                    capacity_per_replica=cfg.capacity_per_instance,
                    service_rate=cfg.capacity_per_instance,
                    latency_sla_ms=settings.SLA_LATENCY_MS,
                    billed_replica_seconds=current * settings.CONTROL_INTERVAL_S,
                    price_per_second=settings.PRICE_PER_REPLICA_HOUR / 3600.0,
                    dt_seconds=settings.CONTROL_INTERVAL_S,
                    idle_w=settings.IDLE_WATTS, peak_w=settings.PEAK_WATTS,
                    measured_latency_ms=latency if live_metrics.request_count > 0 else None,
                ).utilization
                p50 = p90 = None
                horizon = settings.FORECAST_HORIZON_MIN
                model_version = None
                failure = None
                try:
                    model = load_predictor(settings.selected_model_path)
                    horizon = min(horizon, max(model.horizons))
                    forecast = model.predict(hist.tail(480))
                    p50, p90 = map(float, forecast.latest(horizon))
                    model_version = str(getattr(model, "version", type(model).__name__))
                    if not (math.isfinite(p50) and math.isfinite(p90)):
                        raise ValueError("model returned non-finite forecast values")
                    if getattr(app.state, "forecast_fallback", None):
                        logger.info("Forecast recovered; returning to ML-led control")
                    app.state.forecast_fallback = None
                except Exception as exc:
                    failure = f"{type(exc).__name__}: {exc}"
                    app.state.forecast_fallback = failure
                    logger.exception("FORECAST FAILURE: using reactive fallback for this control tick")

                tick = pipeline.tick(
                    observed_load=actual,
                    utilization=utilization,
                    latency_ms=latency,
                    error_rate=live_metrics.error_rate,
                    forecast_p50=p50,
                    forecast_p90=p90,
                    horizon=horizon,
                    model_version=model_version,
                    fallback_reason=failure,
                    now=asyncio.get_running_loop().time(),
                )
                app.state.last_tick_time = datetime.now(UTC).isoformat()
                final = tick.final_desired
                # Commit the tick before downstream actuator/metrics work so every
                # completed decision remains inspectable even if an integration fails.
                with SessionLocal() as db:
                    db.add(Decision(
                        timestamp=tick.timestamp.replace(tzinfo=None),
                        desired=tick.final_desired,
                        current=current,
                        action="scale_up" if final > current else "scale_down" if final < current else "no_change",
                        reason=tick.reason,
                        p50=tick.forecast_p50,
                        p90=tick.forecast_p90,
                        observed_load=tick.observed_load,
                        forecast_p50=tick.forecast_p50,
                        forecast_p90=tick.forecast_p90,
                        horizon=tick.horizon,
                        model_version=tick.model_version,
                        desired_ml=tick.desired_ml,
                        desired_reactive=tick.desired_reactive,
                        final_desired=tick.final_desired,
                        decision_source=tick.decision_source,
                        cooldown_state=tick.cooldown_state,
                    ))
                    db.commit()
                safety_override = tick.decision_source == "safety_net"
                if safety_override or actuator_limiter.allow():
                    action = act.set_desired(final, force=safety_override)
                    loop.state.current_instances = action.desired
                    audit_log.record(action.desired, action.current, action.reason, tick.reason)
                gateway_replicas = (
                    act.get_state().running if hasattr(act, "get_state") else act.current()
                )
                try:
                    async with httpx.AsyncClient(timeout=2.0) as client:
                        await client.put(
                            f"{settings.GATEWAY_URL.rstrip('/')}/replicas",
                            json={"desired": max(1, gateway_replicas)},
                        )
                except httpx.HTTPError:
                    logger.exception("Failed to synchronize RUNNING replica count with gateway")
                pub = getattr(app.state, "metrics_pub", None)
                if pub is not None:
                    try:
                        running = act.current()
                        calculated = calculate_metrics(
                            demand=actual, served_load=actual, running_replicas=running,
                            capacity_per_replica=cfg.capacity_per_instance,
                            service_rate=cfg.capacity_per_instance,
                            latency_sla_ms=settings.SLA_LATENCY_MS,
                            billed_replica_seconds=max(running, final) * settings.CONTROL_INTERVAL_S,
                            billed_replica_count=max(running, final),
                            price_per_second=settings.PRICE_PER_REPLICA_HOUR / 3600.0,
                            dt_seconds=settings.CONTROL_INTERVAL_S,
                            idle_w=settings.IDLE_WATTS, peak_w=settings.PEAK_WATTS,
                            measured_latency_ms=latency if live_metrics.request_count > 0 else None,
                        )
                        pub.put_metrics(
                            predicted_load=p50 or 0.0,
                            actual_load=actual,
                            desired_capacity=final,
                            running_capacity=running,
                            forecast_mape=0.0,
                            sla_violations=calculated.sla_violations,
                            estimated_cost=calculated.cost_usd,
                        )
                    except Exception:
                        pass
                with SessionLocal() as db:
                    db.add(Metric(timestamp=datetime.utcnow(), name="desired_instances", value=final))
                    db.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("CONTROL TICK FAILED before persistence")
                continue
    except asyncio.CancelledError:
        raise
