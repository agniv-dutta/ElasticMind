"""FastAPI app with endpoints as specified."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
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
        self.sla_violation_minutes = 0.0
        self.history: deque[tuple[datetime, float]] = deque(maxlen=480)
        self.telemetry_source = "none"
        self.telemetry_status = "waiting"
        self.last_telemetry_at: datetime | None = None
        self.last_telemetry_error: str | None = None

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
    app.state.telemetry_source = "none"
    app.state.forecast_source = "none"
    app.state.actuator_status = "initializing"
    app.state.loop_paused = False
    app.state.forecast_bias_percent = 0.0
    app.state.load_spike = None
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


async def _sync_gateway_replicas(app: FastAPI, replicas: int) -> None:
    """Keep the gateway pool aligned while tolerating a temporarily absent gateway."""
    desired = max(1, int(replicas))
    now = asyncio.get_running_loop().time()
    same_value = getattr(app.state, "gateway_synced_replicas", None) == desired
    last_sync = getattr(app.state, "gateway_last_sync", 0.0)
    if (now < getattr(app.state, "gateway_retry_at", 0.0)
            or (same_value and now - last_sync < 30.0)):
        return

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.0)) as client:
            response = await client.put(
                f"{settings.GATEWAY_URL.rstrip('/')}/replicas",
                json={"desired": desired},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        failures = getattr(app.state, "gateway_sync_failures", 0) + 1
        app.state.gateway_sync_failures = failures
        # Back off between 2 and 60 seconds; a dead local gateway should not
        # produce a traceback on every control tick, but recovery stays quick.
        delay = min(60.0, 2.0 ** min(failures, 6))
        app.state.gateway_retry_at = now + delay
        url = getattr(getattr(exc, "request", None), "url", None)
        logger.warning(
            "Gateway replica sync failed: type=%s message=%s url=%s; retrying in %.0fs",
            type(exc).__name__, str(exc), url or f"{settings.GATEWAY_URL.rstrip('/')}/replicas", delay,
        )
        return

    app.state.gateway_synced_replicas = desired
    app.state.gateway_last_sync = now
    app.state.gateway_last_sync_at = datetime.now(UTC)
    app.state.gateway_sync_failures = 0
    app.state.gateway_retry_at = 0.0


@app.get("/health")
def health():
    return {"status": "ok", "env": settings.env}


@app.get("/config")
def active_config():
    """Return the effective shared configuration (YAML plus environment overrides)."""
    # reload calibration if present
    try:
        from pathlib import Path
        import yaml
        p = Path("configs/calibration.yaml")
        if not p.exists():
            p = Path(__file__).resolve().parents[2] / "configs" / "calibration.yaml"
        if settings.PROFILE in {"local_demo", "aws_demo"} and p.exists():
            data = yaml.safe_load(p.read_text(encoding="utf-8-sig")) or {}
            v = data.get("CAPACITY_PER_REPLICA_RPM") or data.get("\ufeffCAPACITY_PER_REPLICA_RPM")
            if v is not None:
                val = float(v)
                settings.CAPACITY_PER_REPLICA_RPM = val
                try:
                    settings.capacity_per_instance = val
                except Exception:
                    pass
    except Exception:
        pass
    cfg = AutoscalerConfig.from_settings(settings)
    data = settings.model_dump(by_alias=False)
    return {"profile": settings.PROFILE, "time_scale": settings.TIME_SCALE,
            "PROFILE": settings.PROFILE, "TIME_SCALE": settings.TIME_SCALE,
            "actuator": settings.ACTUATOR, "model_version": settings.selected_model_path,
            "autoscaler_running": not getattr(getattr(app.state, "loop_task", None), "done",
lambda: True)(),
            "last_tick_time": getattr(app.state, "last_tick_time", None),
            "traffic_source": "gateway_connected" if getattr(app.state,
"gateway_synced_replicas", None) is not None else "gateway_disconnected",
            "current_policy": settings.policy,
            "CAPACITY_PER_REPLICA_RPM": cfg.capacity_per_instance,
            "scale_up_threshold_rpm": round(cfg.capacity_per_instance * cfg.target_utilization, 2),
            "min_history_points": settings.min_history_points,
            "sample_interval_s": round(settings.CONTROL_INTERVAL_S / settings.TIME_SCALE, 2),
            "loop_paused": bool(getattr(app.state, "loop_paused", False)),
            "forecast_bias_percent": float(getattr(app.state, "forecast_bias_percent", 0.0) or 0.0),
            "load_spike": getattr(app.state, "load_spike", None),
            **{k:v for k,v in data.items() if k not in {"profile","PROFILE"}}}


@app.get("/status")
async def system_status():
    """Expose live gateway reachability and the last successful replica sync."""
    gateway_url = settings.GATEWAY_URL.rstrip("/")
    gateway_healthy = False
    running_replicas = 0
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(2.0, connect=1.0)) as client:
            response = await client.get(f"{gateway_url}/health")
            response.raise_for_status()
            data = response.json()
            running_replicas = int(data.get("running_replicas", 0))
            gateway_healthy = True
    except httpx.HTTPError:
        pass
    synced = getattr(app.state, "gateway_synced_replicas", None) is not None
    return {
        "gateway_url": gateway_url,
        "gateway_connected": gateway_healthy and synced,
        "gateway_healthy": gateway_healthy,
        "gateway_synced": synced,
        "gateway_running_replicas": running_replicas,
        "gateway_last_sync": getattr(app.state, "gateway_last_sync_at", None),
        "requests_received": live_metrics.request_count,
        "current_rpm": round(live_metrics.requests_per_min, 1),
        "telemetry_source": live_metrics.telemetry_source,
        "telemetry_status": live_metrics.telemetry_status,
        "last_telemetry_at": live_metrics.last_telemetry_at,
        "telemetry_error": live_metrics.last_telemetry_error,
        "forecast_source": getattr(app.state, "forecast_source", "none"),
        "actuator_status": getattr(app.state, "actuator_status", "unknown"),
    }


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
    history_rows = list(live_metrics.history)
    history = [{"timestamp": ts.isoformat(), "actual": float(value)} for ts, value in history_rows[-360:]]
    min_points = settings.min_history_points
    sample_interval_s = settings.CONTROL_INTERVAL_S / settings.TIME_SCALE
    history_meta = {
        "min_history_points": min_points,
        "history_eta_seconds": round(settings.history_eta_seconds(len(history_rows)), 1),
        "sample_interval_s": round(sample_interval_s, 2),
    }
    if len(history_rows) < min_points:
        latest = float(history_rows[-1][1]) if history_rows else 0.0
        fallback_forecast = [
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "horizon_min": horizon,
                "p50": latest,
                "p90": latest,
            }
            for horizon in (5, 15, 30)
        ]
        return {"model": "reactive-fallback", "history": history, "forecast": fallback_forecast,
                "decision_source": "fallback", "forecast_fallback": "insufficient_live_history",
                "unit": "rpm", "history_points": len(history_rows), **history_meta}
    try:
        model = load_predictor(settings.selected_model_path)
    except Exception as e:
        return {"model": "reactive-fallback", "history": history, "forecast": [],
                "decision_source": "fallback", "forecast_fallback": f"model_load_failed: {type(e).__name__}",
                "unit": "rpm", "history_points": len(history_rows), **history_meta}

    # Forecast live demand in the same requests-per-minute units reported by the gateway.
    hist = __import__("pandas").DataFrame(
        [(ts, rpm) for ts, rpm in history_rows], columns=["timestamp", "requests"]
    )
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
    return {"model": fc.model, "history": history, "forecast": points,
            "decision_source": "ml", "unit": "rpm", "history_points": len(history_rows),
            **history_meta}


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
    app.state.loop_paused = False
    return {"started": True, "paused": False}


@app.post("/autoscaler/stop")
def stop_loop():
    app.state.loop_paused = True
    return {"stopped": True, "paused": True}


@app.post("/faults/bias")
def fault_bias(req: FaultBiasRequest):
    """Inject a forecast bias (percent) so the ML prediction is skewed."""
    app.state.forecast_bias_percent = float(req.bias_percent)
    return {"bias_percent": req.bias_percent, "simulated": True}


@app.post("/faults/spike")
def fault_spike(req: FaultSpikeRequest):
    """Inject a load spike: multiply observed rpm by magnitude for N minutes."""
    app.state.load_spike = {
        "magnitude": float(req.magnitude),
        "until": time.time() + float(req.duration_minutes) * 60.0,
    }
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
    # accumulate SLA violation minutes roughly from p95 breach
    if live_metrics.latency_p95_ms > settings.SLA_LATENCY_MS:
        live_metrics.sla_violation_minutes += (duration_s / 60.0)
    live_metrics.timestamp = datetime.now(UTC)
    live_metrics.telemetry_source = "local_gateway"
    live_metrics.telemetry_status = "fresh"
    live_metrics.last_telemetry_at = live_metrics.timestamp
    live_metrics.last_telemetry_error = None
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
        latency_source = "measured" if live_metrics.telemetry_source == "local_gateway" else "estimated"
    else:
        # Fallback to synthetic baseline when no loadgen data
        util = None
        latency_ms = 0.0
        sla_count = 0
        metric_source = "simulated"
        latency_source = "simulated"
    
    metric_values = calculate_metrics(
        demand=live_metrics.requests_per_min if live_metrics.request_count > 0 else 0.0,
        served_load=live_metrics.requests_per_min if live_metrics.request_count > 0 else 0.0,
        running_replicas=current, capacity_per_replica=cfg.capacity_per_instance,
        service_rate=cfg.capacity_per_instance, latency_sla_ms=settings.SLA_LATENCY_MS,
        billed_replica_seconds=current * settings.CONTROL_INTERVAL_S,
        price_per_second=settings.PRICE_PER_REPLICA_HOUR / 3600.0,
        dt_seconds=settings.CONTROL_INTERVAL_S, idle_w=settings.IDLE_WATTS,
        peak_w=settings.PEAK_WATTS,
        measured_latency_ms=(
            latency_ms
            if live_metrics.request_count > 0 and live_metrics.telemetry_source == "local_gateway"
            else None
        ),
    )
    util = metric_values.utilization
    latency_ms = metric_values.latency_ms
    sla_count = metric_values.sla_violations
    cost_usd = metric_values.cost_usd
    energy_kwh = metric_values.energy_kwh_estimated
    history_points = len(live_metrics.history)
    return MetricsResponse(
        current_utilization=util,
        latency_ms=latency_ms,
        latency_p50_ms=(
            round(float(live_metrics.latency_p50_ms), 2)
            if live_metrics.request_count > 0 and live_metrics.telemetry_source == "local_gateway"
            else None
        ),
        latency_p95_ms=(
            round(float(live_metrics.latency_p95_ms), 2)
            if live_metrics.request_count > 0 and live_metrics.telemetry_source == "local_gateway"
            else None
        ),
        cost_usd=cost_usd,
        energy_kwh=energy_kwh,
        sla_count=sla_count,
        timestamp=now,
        provenance={"utilization": metric_source, "sla_count": metric_source,
                    "latency_ms": latency_source, "cost_usd": "estimated",
                    "energy_kwh": "simulated", "error_rate": metric_source,
                    "request_count": metric_source, "running_replicas": "measured",
                    "telemetry_source": live_metrics.telemetry_source},
        energy_label="estimated",
        request_count=live_metrics.request_count,
        error_rate=live_metrics.error_rate,
        running_replicas=live_metrics.running_replicas,
        sla_violation_minutes=round(live_metrics.sla_violation_minutes, 4),
        min_history_points=settings.min_history_points,
        history_points=history_points,
        history_eta_seconds=round(settings.history_eta_seconds(history_points), 1),
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
    q = db.query(Decision).order_by(desc(Decision.timestamp)).limit(500)
    fields = (
        "desired", "current", "action", "running_replicas", "starting_replicas", "draining_replicas",
        "observed_load", "forecast_p50", "forecast_p90", "horizon", "model_version",
        "desired_ml", "desired_reactive", "final_desired", "decision_source", "reason",
        "ml_candidate", "reactive_candidate", "applied", "blocked_by",
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


async def _refresh_aws_telemetry(app: FastAPI) -> str | None:
    """Append one fresh ALB RequestCount sample when AWS mode is enabled."""
    if settings.ACTUATOR != "aws":
        return None
    publisher = getattr(app.state, "metrics_pub", None)
    if publisher is None:
        reason = "aws_cloudwatch_unavailable"
        live_metrics.telemetry_status = "error"
        live_metrics.last_telemetry_error = reason
        return reason
    if not settings.AWS_ALB_LOAD_BALANCER or not settings.AWS_ALB_TARGET_GROUP:
        reason = "aws_telemetry_not_configured"
        live_metrics.telemetry_status = "error"
        live_metrics.last_telemetry_error = reason
        return reason
    try:
        sample = await asyncio.to_thread(
            publisher.read_workload_sample,
            settings.AWS_ALB_LOAD_BALANCER,
            settings.AWS_ALB_TARGET_GROUP,
            settings.AWS_TELEMETRY_PERIOD_S,
            settings.AWS_TELEMETRY_STALE_AFTER_S,
        )
    except Exception as exc:
        reason = f"aws_telemetry_read_failed: {type(exc).__name__}"
        live_metrics.telemetry_status = "error"
        live_metrics.last_telemetry_error = reason
        return reason
    if sample is None:
        reason = "aws_telemetry_missing_or_stale"
        live_metrics.telemetry_status = "stale"
        live_metrics.last_telemetry_error = reason
        return reason
    timestamp = sample["timestamp"]
    if live_metrics.last_telemetry_at is not None and timestamp <= live_metrics.last_telemetry_at:
        reason = "aws_telemetry_duplicate"
        live_metrics.telemetry_status = "stale"
        live_metrics.last_telemetry_error = reason
        return reason
    live_metrics.requests_per_min = float(sample["requests_per_min"])
    live_metrics.request_count = int(round(sample["request_count"]))
    live_metrics.success_rate = 1.0
    live_metrics.error_rate = 0.0
    live_metrics.timestamp = timestamp
    live_metrics.last_telemetry_at = timestamp
    live_metrics.telemetry_source = sample["source"]
    live_metrics.telemetry_status = "fresh"
    live_metrics.last_telemetry_error = None
    live_metrics.history.append((timestamp, live_metrics.requests_per_min))
    app.state.telemetry_source = sample["source"]
    return None


async def control_loop_worker(app: FastAPI):
    """Run forecast → candidate generation → source selection → action → persistence."""
    cfg = AutoscalerConfig.from_settings(settings)
    loop = ControlLoop(cfg)
    pipeline = ControlPipeline(settings, cfg, loop)
    app.state.pipeline = pipeline
    act = _get_actuator()
    await _sync_gateway_replicas(app, act.current())
    try:
        while True:
            await asyncio.sleep(settings.scaled_delay(settings.CONTROL_INTERVAL_S))
            try:
                if getattr(app.state, "loop_paused", False):
                    app.state.last_tick_time = datetime.now(UTC).isoformat()
                    continue
                telemetry_failure = await _refresh_aws_telemetry(app)
                actual = live_metrics.requests_per_min if live_metrics.request_count > 0 else 0.0
                spike = getattr(app.state, "load_spike", None)
                if spike and time.time() < float(spike.get("until", 0.0)):
                    actual = actual * float(spike.get("magnitude", 1.0))
                current = act.current()
                loop.state.current_instances = current
                latency = live_metrics.latency_p95_ms if live_metrics.request_count > 0 else 0.0
                utilization = (live_metrics.utilization
                               if live_metrics.request_count > 0 and settings.ACTUATOR != "aws"
                               else calculate_metrics(
                    demand=actual, served_load=actual, running_replicas=current,
                    capacity_per_replica=cfg.capacity_per_instance,
                    service_rate=cfg.capacity_per_instance,
                    latency_sla_ms=settings.SLA_LATENCY_MS,
                    billed_replica_seconds=current * settings.CONTROL_INTERVAL_S,
                    price_per_second=settings.PRICE_PER_REPLICA_HOUR / 3600.0,
                    dt_seconds=settings.CONTROL_INTERVAL_S,
                    idle_w=settings.IDLE_WATTS, peak_w=settings.PEAK_WATTS,
                    measured_latency_ms=latency if live_metrics.request_count > 0 else None,
                ).utilization)
                if settings.ACTUATOR == "aws":
                    live_metrics.running_replicas = current
                    live_metrics.utilization = utilization
                p50 = p90 = None
                horizon = settings.FORECAST_HORIZON_MIN
                model_version = None
                failure = telemetry_failure
                try:
                    if failure is not None:
                        raise ValueError(failure)
                    history_rows = list(live_metrics.history)
                    if len(history_rows) < settings.min_history_points:
                        raise ValueError(f"insufficient_live_history: {len(history_rows)}/{settings.min_history_points} samples")
                    import pandas as pd
                    hist = pd.DataFrame(
                        [(ts, rpm) for ts, rpm in history_rows],
                        columns=["timestamp", "requests"],
                    )
                    model = load_predictor(settings.selected_model_path)
                    horizon = min(horizon, max(model.horizons))
                    forecast = model.predict(hist.tail(480))
                    p50, p90 = map(float, forecast.latest(horizon))
                    bias_pct = float(getattr(app.state, "forecast_bias_percent", 0.0) or 0.0)
                    if bias_pct:
                        p50 = p50 * (1.0 + bias_pct / 100.0)
                        p90 = p90 * (1.0 + bias_pct / 100.0)
                    model_version = str(getattr(model, "version", type(model).__name__))
                    if not (math.isfinite(p50) and math.isfinite(p90)):
                        raise ValueError("model returned non-finite forecast values")
                    if getattr(app.state, "forecast_fallback", None):
                        logger.info("Forecast recovered; returning to ML-led control")
                    app.state.forecast_fallback = None
                    app.state.forecast_source = live_metrics.telemetry_source
                except Exception as exc:
                    failure = f"{type(exc).__name__}: {exc}"
                    if failure.startswith("ValueError: insufficient_live_history"):
                        if getattr(app.state, "forecast_fallback", None) != failure:
                            logger.info("Using reactive fallback while live forecast history builds: %s", failure)
                    else:
                        logger.exception("FORECAST FAILURE: using reactive fallback for this control tick")
                    app.state.forecast_fallback = failure
                    app.state.forecast_source = "fallback"

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
                    replica_state = act.get_state() if hasattr(act, "get_state") else None
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
                        ml_candidate=tick.ml_candidate,
                        reactive_candidate=tick.reactive_candidate,
                        applied=tick.applied,
                        blocked_by=tick.blocked_by,
                        decision_source=tick.decision_source,
                        cooldown_state=tick.cooldown_state,
                        running_replicas=replica_state.running if replica_state else current,
                        starting_replicas=(max(replica_state.pending_start, final - replica_state.running)
                                            if replica_state else 0),
                        draining_replicas=replica_state.draining if replica_state else 0,
                    ))
                    db.commit()
                safety_override = tick.decision_source == "safety_net"
                if safety_override or actuator_limiter.allow():
                    try:
                        action = act.set_desired(final, force=safety_override)
                        loop.state.current_instances = action.desired
                        app.state.actuator_status = "healthy"
                        audit_log.record(action.desired, action.current, action.reason, tick.reason)
                    except Exception as exc:
                        app.state.actuator_status = f"error: {type(exc).__name__}"
                        logger.exception("ACTUATOR FAILED: desired=%s", final)
                        continue
                gateway_replicas = (
                    act.get_state().running if hasattr(act, "get_state") else act.current()
                )
                await _sync_gateway_replicas(app, gateway_replicas)
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
