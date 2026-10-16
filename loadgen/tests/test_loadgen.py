"""Tests for loadgen helpers."""

from __future__ import annotations

import pandas as pd
from loadgen.runner import _load_trace


def test_load_trace_from_file(tmp_path) -> None:
    df = pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=5, freq="min", tz="UTC"), "requests": [10, 20, 30, 40, 50]})
    p = tmp_path / "t.csv"
    df.to_csv(p, index=False)
    out = _load_trace(str(p), profile="diurnal", days=1)
    assert len(out) == 5


def test_load_trace_fallback(tmp_path) -> None:
    out = _load_trace(str(tmp_path / "missing.parquet"), profile="steady", days=1)
    assert len(out) == 1440
