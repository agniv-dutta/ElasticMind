"""Unit tests for workload data generation and loading."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.data.generate import (
    WorkloadEvent,
    WorkloadProfile,
    default_events,
    generate_workload,
)
from ml.data.loader import load_trace_csv, resample_to_1min, trace_summary


def test_shape_days_to_minutes() -> None:
    df = generate_workload(profile="diurnal", days=3, seed=1)
    assert len(df) == 3 * 1440
    assert list(df.columns) == ["timestamp", "requests", "cpu_pct", "profile"]
    assert df["timestamp"].is_monotonic_increasing
    assert (df["requests"] > 0).all()


def test_reproducible_seed() -> None:
    a = generate_workload(profile="spiky", days=2, seed=7)
    b = generate_workload(profile="spiky", days=2, seed=7)
    c = generate_workload(profile="spiky", days=2, seed=8)
    pd.testing.assert_frame_equal(a, b)
    assert not a["requests"].equals(c["requests"])


def test_diurnal_seasonality_daily_cycle() -> None:
    df = generate_workload(profile="diurnal", days=8, seed=3)
    # average demand per hour-of-day should vary substantially (seasonality)
    hod = df.groupby(df["timestamp"].dt.hour)["requests"].mean()
    assert hod.max() / hod.min() > 1.5
    # day-of-week effect exists (weekend dip) across a full week
    dow = df.groupby(df["timestamp"].dt.dayofweek)["requests"].mean()
    assert dow.max() / dow.min() > 1.05


def test_steady_is_flat() -> None:
    df = generate_workload(profile="steady", days=2, seed=5, noise_frac=0.0)
    assert np.allclose(df["requests"].values, df["requests"].values[0])


def test_flash_spike_event_increases_demand() -> None:
    clean = generate_workload(profile="steady", days=1, seed=11, noise_frac=0.0)
    spiked = generate_workload(
        profile="steady",
        days=1,
        seed=11,
        noise_frac=0.0,
        events=[WorkloadEvent("flash_spike", start_minute=600, duration_minutes=10, magnitude=4.0)],
    )
    assert spiked["requests"].iloc[605] == pytest.approx(clean["requests"].iloc[605] * 4.0)


def test_regime_shift_persists() -> None:
    df = generate_workload(
        profile="steady",
        days=2,
        seed=11,
        noise_frac=0.0,
        events=[WorkloadEvent("regime_shift", start_minute=720, magnitude=1.5)],
    )
    assert df["requests"].iloc[1000] == pytest.approx(df["requests"].iloc[0] * 1.5)


def test_sudden_drop_event() -> None:
    df = generate_workload(
        profile="steady",
        days=1,
        seed=11,
        noise_frac=0.0,
        events=[WorkloadEvent("sudden_drop", start_minute=100, duration_minutes=20, magnitude=2.0)],
    )
    # demand collapses to the generator's floor of 1 req/min
    assert df["requests"].iloc[110] == pytest.approx(1.0, abs=1e-6)
    assert df["requests"].iloc[110] < 0.02 * df["requests"].iloc[0]


def test_default_events_only_for_spiky() -> None:
    assert default_events(WorkloadProfile.SPICY, 14) != []
    assert default_events(WorkloadProfile.DIURNAL, 14) == []


def test_cli_writes_parquet(tmp_path: Path) -> None:
    from ml.data.generate import main

    out = tmp_path / "spiky.parquet"
    main(["--profile", "spiky", "--days", "2", "--out", str(out)])
    assert out.exists()
    df = pd.read_parquet(out)
    assert len(df) == 2 * 1440


def test_loader_resamples_to_1min(tmp_path: Path) -> None:
    ts = pd.date_range("2024-01-01", periods=10, freq="30s", tz="UTC")
    raw = pd.DataFrame({"timestamp": ts, "count": np.arange(10, dtype=float)})
    p = tmp_path / "trace.csv"
    raw.to_csv(p, index=False)

    df = load_trace_csv(p, value_col="count", unit="per_min")
    assert len(df) == 5  # 300 s / 60 s
    assert df["requests"].iloc[0] == 1.0  # 0 + 1
    assert df["timestamp"].diff().dropna().eq(pd.Timedelta(minutes=1)).all()


def test_loader_unit_per_sec(tmp_path: Path) -> None:
    ts = pd.date_range("2024-01-01", periods=3, freq="min", tz="UTC")
    raw = pd.DataFrame({"timestamp": ts, "rps": [1.0, 2.0, 3.0]})
    p = tmp_path / "rps.csv"
    raw.to_csv(p, index=False)
    df = load_trace_csv(p, value_col="rps", unit="per_sec")
    assert df["requests"].tolist() == [60.0, 120.0, 180.0]


def test_resample_requires_timestamp() -> None:
    with pytest.raises(ValueError):
        resample_to_1min(pd.DataFrame({"a": [1, 2]}))


def test_trace_summary_keys() -> None:
    df = generate_workload(days=1, seed=2)
    s = trace_summary(df)
    assert {"rows", "mean_requests", "p90_requests", "p99_requests"} <= set(s)
    assert s["rows"] == 1440
