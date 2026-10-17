"""Simple split-conformal intervals for P90-style coverage."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class ConformalResult:
    frame: pd.DataFrame  # columns timestamp, horizon_min, p50, p90, p90_lower, p90_upper, model


def compute_conformal_intervals(
    y_true_cal: pd.Series,
    y_pred_cal_p50: pd.Series,
    y_pred_cal_p90: pd.Series,
    horizon: int,
    alpha: float = 0.1,
) -> dict[str, float]:
    resid = (y_true_cal - y_pred_cal_p90).abs().sort_values()
    n = len(resid)
    if n == 0:
        q = 0.0
    else:
        q = float(resid.iloc[min(n - 1, int(np.ceil((1 - alpha) * (n + 1)) - 1))]) if False else float(resid.quantile(1 - alpha))
    q = float(resid.quantile(1 - alpha)) if n > 0 else 0.0
    return {"q": q}


def apply_intervals(frame: pd.DataFrame, q_map: dict[int, float]) -> pd.DataFrame:
    df = frame.copy()
    if "p90_lower" not in df.columns:
        df["p90_lower"] = df["p90"]
    if "p90_upper" not in df.columns:
        df["p90_upper"] = df["p90"]
    for h, q in q_map.items():
        mask = df["horizon_min"] == h
        if mask.any():
            df.loc[mask, "p90_lower"] = (df.loc[mask, "p90"] - q).clip(lower=0)
            df.loc[mask, "p90_upper"] = df.loc[mask, "p90"] + q
    return df