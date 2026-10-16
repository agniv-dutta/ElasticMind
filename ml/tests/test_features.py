"""Tests for feature engineering."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.data.generate import generate_workload
from ml.features.engineering import (
    DEFAULT_LAGS,
    DEFAULT_WINDOWS,
    FEATURE_COLUMNS,
    build_features,
    feature_columns,
    make_supervised,
)


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    return generate_workload(profile="diurnal", days=2, seed=1)


def test_build_features_shapes(df: pd.DataFrame) -> None:
    out = build_features(df)
    assert len(out) == len(df)
    for k in DEFAULT_LAGS:
        assert f"lag_{k}" in out.columns
    for w in DEFAULT_WINDOWS:
        assert f"rollmean_{w}" in out.columns
        assert f"rollstd_{w}" in out.columns
    for c in ("hour_sin", "hour_cos", "dow_sin", "dow_cos", "roc_1", "roc_5", "pct_change_1"):
        assert c in out.columns


def test_lags_are_pure_past(df: pd.DataFrame) -> None:
    out = build_features(df)
    assert out["lag_1"].iloc[5] == df["requests"].iloc[4]
    assert out["lag_5"].iloc[10] == df["requests"].iloc[5]
    assert np.isnan(out["lag_1"].iloc[0])


def test_cyclical_encoding_bounded(df: pd.DataFrame) -> None:
    out = build_features(df)
    for c in ("hour_sin", "hour_cos", "dow_sin", "dow_cos"):
        assert out[c].abs().max() <= 1.0 + 1e-9


def test_rate_of_change(df: pd.DataFrame) -> None:
    out = build_features(df)
    expected = df["requests"].diff(1)
    assert np.allclose(out["roc_1"].dropna().values, expected.dropna().values)


def test_make_supervised_no_future_leakage(df: pd.DataFrame) -> None:
    h = 15
    sup = make_supervised(df, horizon=h)
    # target of row aligned with origin i equals requests[i + h]
    merged = sup.merge(df[["timestamp", "requests"]], on="timestamp", how="left")
    idx = {ts: i for i, ts in enumerate(df["timestamp"])}
    for _, row in merged.sample(25, random_state=0).iterrows():
        i = idx[row["timestamp"]]
        assert row["target"] == pytest.approx(df["requests"].iloc[i + h])
        # lag_60 at origin i must equal requests[i - 60]
        assert row["lag_60"] == pytest.approx(df["requests"].iloc[i - 60])


def test_make_supervised_drops_tail(df: pd.DataFrame) -> None:
    h = 30
    sup = make_supervised(df, horizon=h)
    # 60 warm-up rows (lag_60) and h tail rows (target) are dropped
    assert len(sup) == len(df) - 60 - h


def test_feature_columns_excludes_raw() -> None:
    df = generate_workload(days=1, seed=2)
    cols = feature_columns(build_features(df))
    assert "requests" not in cols
    assert "timestamp" not in cols
    assert "profile" not in cols
    assert set(FEATURE_COLUMNS) <= set(cols)


def test_missing_value_column_raises() -> None:
    with pytest.raises(ValueError):
        build_features(pd.DataFrame({"timestamp": [], "other": []}))
