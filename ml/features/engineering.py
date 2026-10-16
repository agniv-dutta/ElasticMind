"""Feature engineering: lags, rolling stats, cyclical encodings, rate-of-change.

All inputs are 1-minute resolution workload traces with a ``timestamp`` column
and a ``requests`` column (requests per minute, **simulated** or measured).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_LAGS: tuple[int, ...] = (1, 2, 3, 5, 10, 15, 30, 60)
DEFAULT_WINDOWS: tuple[int, ...] = (5, 15, 60)


def build_features(
    df: pd.DataFrame,
    lags: tuple[int, ...] = DEFAULT_LAGS,
    windows: tuple[int, ...] = DEFAULT_WINDOWS,
    value_col: str = "requests",
) -> pd.DataFrame:
    """Return ``df`` with engineered features appended.

    Features
    --------
    - ``lag_k`` for k in ``lags`` (backshift of the demand series)
    - ``rollmean_k`` / ``rollstd_k`` for k in ``windows``
    - ``hour_sin/cos``, ``dow_sin/cos`` cyclical encodings
    - ``roc_1`` (rate of change vs previous minute), ``roc_5``, ``pct_change_1``
    - ``minute_of_day`` (0-1439), normalized trend index
    """
    if value_col not in df.columns:
        raise ValueError(f"missing value column {value_col!r}")
    out = df.copy()
    if "timestamp" in out.columns:
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
        out = out.sort_values("timestamp").reset_index(drop=True)
        ts = out["timestamp"]
        hour = ts.dt.hour + ts.dt.minute / 60.0
        dow = ts.dt.dayofweek.astype(float)
        out["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
        out["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)
        out["dow_sin"] = np.sin(2 * np.pi * dow / 7.0)
        out["dow_cos"] = np.cos(2 * np.pi * dow / 7.0)
        out["minute_of_day"] = (ts.dt.hour * 60 + ts.dt.minute).astype(float)
        out["minute_of_day"] /= 1440.0
    else:
        raise ValueError("DataFrame must contain a 'timestamp' column")

    s = out[value_col].astype(float)
    for k in lags:
        out[f"lag_{k}"] = s.shift(k)
    for k in windows:
        out[f"rollmean_{k}"] = s.shift(1).rolling(k, min_periods=1).mean()
        out[f"rollstd_{k}"] = s.shift(1).rolling(k, min_periods=1).std().fillna(0.0)
    out["roc_1"] = s.diff(1)
    out["roc_5"] = s.diff(5) / 5.0
    out["pct_change_1"] = s.pct_change(1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    out["trend_idx"] = np.arange(len(out), dtype=float) / max(len(out) - 1, 1)
    return out


def feature_columns(df: pd.DataFrame) -> list[str]:
    """All engineered feature columns present in ``df`` (excludes raw/target)."""
    keep = {"timestamp", "requests", "cpu_pct", "profile"}
    return [c for c in df.columns if c not in keep and df[c].dtype != object]


FEATURE_COLUMNS = (
    [f"lag_{k}" for k in DEFAULT_LAGS]
    + [f"rollmean_{k}" for k in DEFAULT_WINDOWS]
    + [f"rollstd_{k}" for k in DEFAULT_WINDOWS]
    + [
        "hour_sin",
        "hour_cos",
        "dow_sin",
        "dow_cos",
        "minute_of_day",
        "roc_1",
        "roc_5",
        "pct_change_1",
        "trend_idx",
    ]
)


def make_supervised(
    df: pd.DataFrame,
    horizon: int,
    value_col: str = "requests",
    lags: tuple[int, ...] = DEFAULT_LAGS,
    windows: tuple[int, ...] = DEFAULT_WINDOWS,
) -> pd.DataFrame:
    """Build ``(X, y)``-style frame where the target is demand ``horizon`` steps ahead.

    Row ``t`` uses features computed from data up to ``t`` to predict
    ``requests[t + horizon]`` — no leakage (features never see the future).
    """
    feat = build_features(df, lags=lags, windows=windows, value_col=value_col)
    feat["target"] = feat[value_col].shift(-horizon)
    cols = ["timestamp", "target"] + [c for c in feat.columns if c.startswith(
        ("lag_", "rollmean_", "rollstd_", "hour_", "dow_", "roc_", "pct_", "minute", "trend")
    )]
    out = feat[cols].dropna().reset_index(drop=True)
    return out
