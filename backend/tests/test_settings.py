"""Regression tests ensuring runtime consumers derive values from Settings."""

from backend.app.autoscaler.config import AutoscalerConfig
from backend.app.core.config import Settings
from backend.app.simulator.simulator import SimConfig


def test_autoscaler_config_from_default_settings():
    cfg = AutoscalerConfig.from_settings(Settings(_env_file=None, _yaml_file=None))
    assert cfg.min_instances == 1
    assert cfg.max_instances == 10


def test_shared_settings_feed_runtime_configs(monkeypatch) -> None:
    monkeypatch.setenv("ELASTICMIND_TIME_SCALE", "4")
    monkeypatch.setenv("ELASTICMIND_STARTUP_DELAY_S", "80")
    monkeypatch.setenv("ELASTICMIND_COOLDOWN_UP_S", "40")
    monkeypatch.setenv("ELASTICMIND_COOLDOWN_DOWN_S", "120")
    monkeypatch.setenv("ELASTICMIND_CAPACITY_PER_REPLICA_RPM", "750")
    monkeypatch.setenv("ELASTICMIND_MIN_REPLICAS", "2")
    monkeypatch.setenv("ELASTICMIND_MAX_REPLICAS", "8")
    monkeypatch.setenv("ELASTICMIND_PRICE_PER_REPLICA_HOUR", "0.25")

    settings = Settings(_env_file=None, _yaml_file=None)
    autoscaler = AutoscalerConfig.from_settings(settings)
    simulator = SimConfig.from_settings(settings)

    assert autoscaler.capacity_per_instance == 750
    assert (autoscaler.min_instances, autoscaler.max_instances) == (2, 8)
    assert autoscaler.provisioning_delay_s == 20
    assert autoscaler.fast_scale_up_cooldown_s == 40
    assert autoscaler.slow_scale_down_cooldown_s == 120
    assert simulator.service_rate == 750
    assert simulator.provisioning_delay_s == 20
    assert simulator.cost_per_instance_hour == 0.25


def test_yaml_values_are_overridden_by_environment(monkeypatch) -> None:
    from pathlib import Path

    yaml_path = Path(__file__).with_name("_settings_test.yaml")
    yaml_path.write_text("PROFILE: local_demo\nTIME_SCALE: 2\nTARGET_UTILIZATION: 0.6\n")
    monkeypatch.setenv("ELASTICMIND_TARGET_UTILIZATION", "0.8")
    try:
        class YamlSettings(Settings):
            model_config = {**Settings.model_config, "yaml_file": str(yaml_path)}

        settings = YamlSettings(_env_file=None)
        assert settings.PROFILE == "local_demo"
        assert settings.TIME_SCALE == 2
        assert settings.TARGET_UTILIZATION == 0.8
    finally:
        yaml_path.unlink(missing_ok=True)
