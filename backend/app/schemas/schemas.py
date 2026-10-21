"""Pydantic schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field
from backend.app.core.config import Settings


class PredictRequest(BaseModel):
    horizon_min: int = Field(default_factory=lambda: Settings().FORECAST_HORIZON_MIN)
    history_minutes: int = 240


class PredictResponse(BaseModel):
    model: str
    forecast: list[dict]


class ForecastPoint(BaseModel):
    timestamp: datetime
    horizon_min: int
    p50: float
    p90: float


class CapacityResponse(BaseModel):
    current_instances: int
    desired_instances: int | None = None
    capacity_per_instance: float = Field(..., description="simulated")
    target_utilization: float = Field(..., description="simulated")


class PolicyRequest(BaseModel):
    policy: str = Field(pattern="^(static|reactive|ml)$")
    fixed: int | None = None


class FaultBiasRequest(BaseModel):
    bias_percent: float = Field(ge=-100, le=200)


class FaultSpikeRequest(BaseModel):
    magnitude: float = Field(gt=0, le=10)
    duration_minutes: int = Field(gt=0, le=30)


class MetricsResponse(BaseModel):
    current_utilization: float = Field(..., description="simulated")
    latency_ms: float = Field(..., description="simulated")
    cost_usd: float = Field(..., description="simulated")
    energy_kwh: float = Field(..., description="simulated")
    sla_count: int = Field(..., description="simulated")
    timestamp: datetime


class HistoryQuery(BaseModel):
    from_ts: datetime | None = None
    to_ts: datetime | None = None
