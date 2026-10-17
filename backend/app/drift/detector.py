"""Data drift detection (PSI/KS approximations, simulated-appropriate)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def psi(expected: pd.Series, actual: pd.Series, bins: int = 10) -> float:
    try:
        expected_counts, edges = np.histogram(expected.dropna(), bins=bins)
        actual_counts, _ = np.histogram(actual.dropna(), bins=edges)
        exp_pct = expected_counts / max(expected_counts.sum(), 1)
        act_pct = actual_counts / max(actual_counts.sum(), 1)
        exp_pct = np.where(exp_pct == 0, 0.0001, exp_pct)
        act_pct = np.where(act_pct == 0, 0.0001, act_pct)
        return float(np.sum((act_pct - exp_pct) * np.log(act_pct / exp_pct)))
    except Exception:
        return 0.0


def ks(expected: pd.Series, actual: pd.Series) -> float:
    try:
        left = np.sort(expected.dropna().to_numpy(dtype=float))
        right = np.sort(actual.dropna().to_numpy(dtype=float))
        if not len(left) or not len(right):
            return 0.0
        values = np.sort(np.unique(np.concatenate([left, right])))
        left_cdf = np.searchsorted(left, values, side="right") / len(left)
        right_cdf = np.searchsorted(right, values, side="right") / len(right)
        return float(np.max(np.abs(left_cdf - right_cdf)))
    except Exception:
        return 0.0


def drift_status(expected: pd.Series, actual: pd.Series) -> dict[str, float | bool]:
    """Return both drift statistics and conservative alarm thresholds."""
    psi_value = psi(expected, actual)
    ks_value = ks(expected, actual)
    return {
        "psi": psi_value,
        "ks": ks_value,
        "drift": psi_value >= 0.20 or ks_value >= 0.10,
    }