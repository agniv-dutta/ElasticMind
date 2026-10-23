"""The shared, typed configuration for backend, load generator, and experiments."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class Settings(BaseSettings):
    """Application settings; YAML is the base and ELASTICMIND_* env vars override it."""

    model_config = SettingsConfigDict(
        env_prefix="ELASTICMIND_", env_file=".env", yaml_file="config.yaml", extra="allow"
    )

    PROFILE: Literal["offline", "local_demo", "aws_demo"] = "offline"
    TIME_SCALE: float = Field(default=1.0, gt=0)
    ACTUATOR: Literal["local", "aws"] = "local"  # local default per requirement
    CONTROL_INTERVAL_S: float = Field(default=5.0, gt=0)
    FORECAST_HORIZON_MIN: int = Field(default=15, gt=0)
    TARGET_UTILIZATION: float = Field(default=0.70, gt=0, le=1)
    CAPACITY_PER_REPLICA_RPM: float = Field(default=500.0, gt=0)
    MIN_REPLICAS: int = Field(default=1, ge=1)
    MAX_REPLICAS: int = Field(default=10, ge=1)
    STARTUP_DELAY_S: float = Field(default=90.0, ge=0)
    DRAIN_DELAY_S: float = Field(default=30.0, ge=0)
    SLA_LATENCY_MS: float = Field(default=200.0, gt=0)
    PRICE_PER_REPLICA_HOUR: float = Field(default=0.011, ge=0)
    IDLE_WATTS: float = Field(default=10.0, ge=0)
    PEAK_WATTS: float = Field(default=100.0, ge=0)
    COOLDOWN_UP_S: float = Field(default=30.0, ge=0)
    COOLDOWN_DOWN_S: float = Field(default=120.0, ge=0)
    SAFETY_UTILIZATION_THRESHOLD: float = Field(default=0.90, gt=0, le=1)
    SAFETY_MIN_UTILIZATION: float = Field(default=0.30, ge=0, le=1)
    SAFETY_LATENCY_BREACH_TICKS: int = Field(default=3, ge=1)
    SAFETY_LATENCY_WINDOW_SIZE: int = Field(default=5, ge=1)
    ERROR_RATE_THRESHOLD: float = Field(default=0.05, ge=0, le=1)
    # Live history required before ML takes over. None => profile default.
    MIN_HISTORY_POINTS: int | None = None
    ML_WARMUP_TARGET_S: float = Field(default=300.0, gt=0)
    # Aliases for AutoscalerConfig compatibility
    min_instances: int | None = None
    max_instances: int | None = None
    target_utilization: float | None = None
    fast_scale_up_cooldown_s: float | None = None
    slow_scale_down_cooldown_s: float | None = None
    hysteresis: float | None = None
    provisioning_delay_s: float | None = None
    capacity_per_instance: float | None = None
    capacity_per_replica: float | None = None

    # Operational settings which are not part of the shared simulation contract.
    env: str = "development"
    db_url: str = "sqlite:///./backend/data/elasticmind.db"
    log_level: str = "INFO"
    policy: str = "ml"
    headroom: float = 0.20
    hysteresis: float = 0.05
    model_path: str | None = None
    aws_region: str = "us-east-1"
    ecs_cluster: str = "elasticmind"
    ecs_service: str = "elasticmind-target"
    model_s3_uri: str = ""
    GATEWAY_URL: str = "http://localhost:8001"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        from pydantic_settings import YamlConfigSettingsSource

        # Earlier entries have higher priority: explicit values, env, dotenv, YAML, defaults.
        return (init_settings, env_settings, dotenv_settings, YamlConfigSettingsSource(settings_cls), file_secret_settings)

    @model_validator(mode="after")
    def valid_replica_range(self) -> Settings:
        if self.MAX_REPLICAS < self.MIN_REPLICAS:
            raise ValueError("MAX_REPLICAS must be >= MIN_REPLICAS")
        # Load calibration if present
        try:
            from pathlib import Path
            import yaml
            p = Path("configs/calibration.yaml")
            if not p.is_absolute():
                # try relative to cwd or repo root
                if not p.exists():
                    p = Path(__file__).resolve().parents[3] / "configs" / "calibration.yaml"
            if p.exists():
                data = yaml.safe_load(p.read_text(encoding='utf-8-sig')) or {}
                v = data.get("CAPACITY_PER_REPLICA_RPM") or data.get("\ufeffCAPACITY_PER_REPLICA_RPM")
                if v is not None:
                    val = float(v)
                    self.CAPACITY_PER_REPLICA_RPM = val
                    try:
                        self.capacity_per_instance = val
                    except Exception:
                        pass
                    try:
                        self.capacity_per_replica = val
                    except Exception:
                        pass
        except Exception:
            pass
        return self

    def scaled_delay(self, seconds: float) -> float:
        """Convert simulated seconds into wall-clock seconds at TIME_SCALE."""
        return seconds / self.TIME_SCALE

    @property
    def min_history_points(self) -> int:
        """Samples needed before the ML model takes over.

        Uses MIN_HISTORY_POINTS when set. Otherwise aims for ML ready within
        ~3 minutes for ``local_demo`` and ML_WARMUP_TARGET_S (5 min) elsewhere.
        Sample interval is CONTROL_INTERVAL_S / TIME_SCALE.
        """
        if self.MIN_HISTORY_POINTS is not None:
            return max(1, int(self.MIN_HISTORY_POINTS))
        target_s = 180.0 if self.PROFILE == "local_demo" else self.ML_WARMUP_TARGET_S
        interval_s = max(self.CONTROL_INTERVAL_S / self.TIME_SCALE, 1e-6)
        return max(1, int(round(target_s / interval_s)))

    def history_eta_seconds(self, points: int) -> float:
        """Wall-clock seconds remaining until ML can take over."""
        remaining = max(0, self.min_history_points - int(points))
        return remaining * max(self.CONTROL_INTERVAL_S / self.TIME_SCALE, 0.0)

    @property
    def selected_model_path(self) -> str:
        """Resolve a model artifact from PROFILE, unless explicitly overridden."""
        if self.model_path:
            return self.model_path
        if self.PROFILE in {"local_demo", "aws_demo"}:
            return "ml/models/artifacts/lightgbm_local_demo.joblib"
        return "ml/models/artifacts/lightgbm.joblib"

    @property
    def db_path(self) -> Path:
        if self.db_url.startswith("sqlite:///"):
            p = self.db_url.replace("sqlite:///", "", 1)
            return Path(p if p else "backend/data/elasticmind.db")
        return Path("backend/data/elasticmind.db")


def load_capacity_from_yaml(settings_obj, path="configs/calibration.yaml"):
    try:
        from pathlib import Path

        import yaml
        p = Path(path)
        if p.exists():
            data = yaml.safe_load(p.read_text()) or {}
            v = data.get("CAPACITY_PER_REPLICA_RPM")
            if v is not None:
                try:
                    settings_obj.capacity_per_instance = float(v)
                except Exception:
                    pass
                if hasattr(settings_obj, "CAPACITY_PER_REPLICA_RPM"):
                    settings_obj.CAPACITY_PER_REPLICA_RPM = float(v)
    except Exception:
        pass


# Create a module-level settings instance used by imports
settings = Settings()
try:
    # reload calibration
    from pathlib import Path
    import yaml
    p = Path("configs/calibration.yaml")
    if not p.exists():
        p = Path(__file__).resolve().parents[3] / "configs" / "calibration.yaml"
    if p.exists():
        data = yaml.safe_load(p.read_text(encoding='utf-8-sig')) or {}
        v = data.get("CAPACITY_PER_REPLICA_RPM") or data.get("\ufeffCAPACITY_PER_REPLICA_RPM")
        if v is not None:
            val = float(v)
            settings.CAPACITY_PER_REPLICA_RPM = val
            try:
                settings.capacity_per_instance = val
            except Exception:
                pass
            try:
                settings.capacity_per_replica = val
            except Exception:
                pass
except Exception:
    pass
