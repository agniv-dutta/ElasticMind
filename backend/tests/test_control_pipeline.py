from backend.app.autoscaler.config import AutoscalerConfig
from backend.app.autoscaler.control import ControlLoop
from backend.app.autoscaler.pipeline import ControlPipeline
from backend.app.core.config import Settings
from backend.app.db.models import Decision, get_session_factory, get_engine, init_db


def make_pipeline(settings: Settings | None = None):
    settings = settings or Settings(_env_file=None, _yaml_file=None)
    cfg = AutoscalerConfig(
        min_instances=1,
        max_instances=8,
        capacity_per_instance=100,
        target_utilization=0.7,
        headroom=0.0,
        fast_scale_up_cooldown_s=0,
        slow_scale_down_cooldown_s=0,
        hysteresis=0,
    )
    loop = ControlLoop(cfg)
    loop.reset(1)
    return ControlPipeline(settings, cfg, loop)


def test_rising_forecast_scales_before_observed_load_rises():
    pipeline = make_pipeline()
    tick = pipeline.tick(
        observed_load=20,
        utilization=0.2,
        latency_ms=30,
        forecast_p50=180,
        forecast_p90=220,
        horizon=15,
        model_version="test-model",
        now=1000,
    )

    assert tick.decision_source == "ml"
    assert tick.desired_ml > 1
    assert tick.final_desired == tick.desired_ml
    assert tick.observed_load == 20


def test_safety_net_overrides_only_after_unforecast_spike_and_logs_candidates():
    pipeline = make_pipeline()
    tick = pipeline.tick(
        observed_load=100,
        utilization=1.0,
        latency_ms=50,
        forecast_p50=20,
        forecast_p90=25,
        horizon=15,
        model_version="test-model",
        now=1000,
    )

    assert tick.decision_source == "safety_net"
    assert tick.desired_ml == 1
    assert tick.desired_reactive > tick.desired_ml
    assert tick.final_desired == tick.desired_reactive
    assert "ML candidate 1" in tick.reason
    assert f"reactive candidate {tick.desired_reactive}" in tick.reason


def test_safety_net_does_not_fire_when_utilization_and_latency_are_below_threshold():
    pipeline = make_pipeline()
    tick = pipeline.tick(
        observed_load=10,
        utilization=0.1,
        latency_ms=50,
        forecast_p50=100,
        forecast_p90=120,
        horizon=15,
        model_version="test-model",
        now=1000,
    )
    assert tick.decision_source == "ml"


def test_missing_or_failed_forecast_uses_loudly_described_reactive_fallback():
    pipeline = make_pipeline()
    tick = pipeline.tick(
        observed_load=40,
        utilization=0.4,
        latency_ms=50,
        forecast_p50=None,
        forecast_p90=None,
        horizon=15,
        model_version=None,
        fallback_reason="FileNotFoundError: model missing",
        now=1000,
    )
    assert tick.decision_source == "fallback"
    assert "FileNotFoundError" in tick.reason


def test_static_policy_is_reported_as_static():
    pipeline = make_pipeline(Settings(_env_file=None, _yaml_file=None, policy="static"))
    tick = pipeline.tick(
        observed_load=20,
        utilization=0.2,
        latency_ms=30,
        forecast_p50=20,
        forecast_p90=25,
        horizon=15,
        model_version="test-model",
        now=1000,
    )
    assert tick.decision_source == "static"


def test_control_tick_fields_round_trip_through_sqlite():
    pipeline = make_pipeline()
    tick = pipeline.tick(
        observed_load=20,
        utilization=0.2,
        latency_ms=30,
        forecast_p50=100,
        forecast_p90=120,
        horizon=15,
        model_version="v1",
        now=1000,
    )
    engine = get_engine("sqlite://")
    init_db(engine)
    session_factory = get_session_factory(engine)
    with session_factory() as session:
        session.add(Decision(
            timestamp=tick.timestamp.replace(tzinfo=None),
            reason=tick.reason,
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
        session.commit()
        stored = session.query(Decision).one()
        assert stored.decision_source == "ml"
        assert stored.final_desired == tick.final_desired
        assert stored.observed_load == tick.observed_load
