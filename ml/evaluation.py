"""Forecast evaluation metrics: MAE, RMSE, MAPE, under-prediction rate."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass
class EvalMetrics:
    mae: float
    rmse: float
    mape: float
    under_pred_rate: float
    pinball_90: float
    n: int

    def to_dict(self) -> dict:
        return asdict(self)


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray, q90: np.ndarray | None = None) -> EvalMetrics:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    if y_true.shape != y_pred.shape:
        raise ValueError("y_true and y_pred must have the same shape")
    if len(y_true) == 0:
        raise ValueError("empty inputs")

    err = y_pred - y_true
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err**2)))
    denom = np.where(np.abs(y_true) < 1e-9, np.nan, np.abs(y_true))
    mape = float(np.nanmean(np.abs(err) / denom) * 100.0)
    under = float(np.mean(y_pred < y_true))

    if q90 is not None:
        q = np.asarray(q90, dtype=float)
        d = y_true - q
        pinball90 = float(np.mean(np.maximum(0.9 * d, (0.9 - 1.0) * d)))
    else:
        pinball90 = float("nan")

    return EvalMetrics(mae=mae, rmse=rmse, mape=mape, under_pred_rate=under,
                       pinball_90=pinball90, n=len(y_true))


def rolling_backtest(
    history: pd.DataFrame,
    predict_fn,
    horizons: tuple[int, ...],
    stride: int = 15,
    max_points: int | None = None,
) -> pd.DataFrame:
    """Chronological rolling-origin backtest.

    Parameters
    ----------
    history:
        Full trace (``timestamp``, ``requests``).
    predict_fn:
        ``fn(history_so_far) -> ForecastResult`` (uses only past data).
    horizons:
        Horizons to evaluate.
    stride:
        Re-evaluate every ``stride`` minutes.
    max_points:
        Cap the number of origin points (bounds runtime).

    Returns
    -------
    DataFrame with columns: origin, horizon_min, y_true, y_pred_p50, y_pred_p90.
    """
    d = history[["timestamp", "requests"]].copy().reset_index(drop=True)
    rows = []
    origins = list(range(60, len(d) - max(horizons), stride))  # need >= 60 min burn-in
    if max_points is not None and len(origins) > max_points:
        step = len(origins) / max_points
        origins = [origins[int(i * step)] for i in range(max_points)]

    for i in origins:
        hist = d.iloc[: i + 1]
        fc = predict_fn(hist)
        for h in horizons:
            sub = fc.for_horizon(h)
            if sub.empty:
                continue
            y_true = float(d["requests"].iloc[i + h])
            rows.append(
                {
                    "origin": d["timestamp"].iloc[i],
                    "horizon_min": h,
                    "y_true": y_true,
                    "y_pred_p50": float(sub["p50"].iloc[-1]),
                    "y_pred_p90": float(sub["p90"].iloc[-1]),
                }
            )
    return pd.DataFrame(rows)
