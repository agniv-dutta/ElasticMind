"""Backend configuration via environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ELASTICMIND_", env_file=".env")

    env: str = "development"
    db_url: str = "sqlite:///./backend/data/elasticmind.db"
    log_level: str = "INFO"

    loop_interval_s: int = 5
    policy: str = "ml"
    actuator: str = "local"
    min_instances: int = 1
    max_instances: int = 10
    capacity_per_instance: float = 100.0
    target_utilization: float = 0.70
    headroom: float = 0.20
    scale_up_cooldown_s: int = 30
    scale_down_cooldown_s: int = 120
    hysteresis: float = 0.05

    model_path: str = "ml/models/artifacts/lightgbm.joblib"
    horizon_min: int = 15

    # AWS (Phase 2)
    aws_region: str = "us-east-1"
    ecs_cluster: str = "elasticmind"
    ecs_service: str = "elasticmind-target"
    model_s3_uri: str = ""

    @property
    def db_path(self) -> Path:
        # sqlite path
        if self.db_url.startswith("sqlite:///"):
            p = self.db_url.replace("sqlite:///", "", 1)
            return Path(p if p else "backend/data/elasticmind.db")
        return Path("backend/data/elasticmind.db")
