"""Predictor interface shared by all forecasting models."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import ClassVar

import numpy as np
import pandas as pd

DEFAULT_HORIZONS: tuple[int, ...] = (5, 15, 30)


@dataclass
class ForecastResult:
    """Multi-horizon forecast frame with P50/P90 quantiles.

    Frame columns: ``timestamp`` (forecast target time), ``horizon_min``,
    ``p50``, ``p90``.
    """

    frame: pd.DataFrame
    model: str = ""
    meta: dict = field(default_factory=dict)

    def for_horizon(self, horizon_min: int) -> pd.DataFrame:
        return self.frame[self.frame["horizon_min"] == horizon_min].reset_index(drop=True)

    def latest(self, horizon_min: int) -> tuple[float, float]:
        """(p50, p90) of the most recent forecast for ``horizon_min``."""
        f = self.for_horizon(horizon_min)
        if f.empty:
            raise ValueError(f"no forecast for horizon {horizon_min}")
        return float(f["p50"].iloc[-1]), float(f["p90"].iloc[-1])


class Predictor(abc.ABC):
    """Interface every forecasting model implements."""

    name: ClassVar[str] = "base"
    supports_quantiles: ClassVar[bool] = True

    def __init__(self, horizons: tuple[int, ...] = DEFAULT_HORIZONS) -> None:
        self.horizons = tuple(sorted(horizons))
        self.fitted_: bool = False

    @abc.abstractmethod
    def fit(self, history: pd.DataFrame) -> Predictor:
        """Train on a 1-min workload frame (``timestamp`` + ``requests``)."""

    @abc.abstractmethod
    def predict(self, history: pd.DataFrame) -> ForecastResult:
        """Forecast ``self.horizons`` steps ahead from the end of ``history``."""

    def _require_fitted(self) -> None:
        if not self.fitted_:
            raise RuntimeError(f"{self.name} is not fitted; call fit() first")

    @staticmethod
    def _frame(tail: pd.DataFrame) -> pd.DataFrame:
        if "timestamp" not in tail.columns or "requests" not in tail.columns:
            raise ValueError("history must have 'timestamp' and 'requests' columns")
        d = tail[["timestamp", "requests"]].copy()
        d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
        return d.sort_values("timestamp").reset_index(drop=True)


def quantile_loss(y: np.ndarray, q_pred: np.ndarray, q: float) -> float:
    """Pinball loss averaged over the sample (used for P90 calibration checks)."""
    y = np.asarray(y, dtype=float)
    q_pred = np.asarray(q_pred, dtype=float)
    d = y - q_pred
    return float(np.mean(np.maximum(q * d, (q - 1) * d)))
