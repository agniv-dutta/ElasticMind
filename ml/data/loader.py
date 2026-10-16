"""Loader for public workload traces (CSV) resampled to 1-minute intervals.

Supported layouts:
- ``timestamp`` + one or more value columns (requests, cpu, etc.)
- A ``--value`` column chosen by the caller; defaults to the first numeric
  column that is not the timestamp.

Examples of public traces you can drop in (download manually):
- Alibaba cluster trace (task usage) aggregates
- Wikimedia / Azure Functions traces converted to CSV
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = ("timestamp", "requests")


def _find_timestamp_col(df: pd.DataFrame) -> str:
    for c in df.columns:
        if c.lower() in {"timestamp", "ts", "time", "datetime", "date", "datetime.utc"}:
            return c
    raise ValueError(f"no timestamp column found among {list(df.columns)}")


def load_trace_csv(
    path: str | Path,
    timestamp_col: str | None = None,
    value_col: str | None = None,
    unit: str = "auto",
) -> pd.DataFrame:
    """Load a CSV trace and normalise it to ``timestamp`` (UTC, 1-min) + ``requests``.

    Parameters
    ----------
    path:
        CSV file path.
    timestamp_col:
        Name of the timestamp column; auto-detected when omitted.
    value_col:
        Name of the demand column (request count / CPU). Defaults to the first
        numeric non-timestamp column.
    unit:
        ``auto`` | ``per_sec`` | ``per_min``. Values are converted to
        **requests per minute**.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    df = pd.read_csv(path)
    ts_col = timestamp_col or _find_timestamp_col(df)
    df[ts_col] = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
    df = df.dropna(subset=[ts_col]).rename(columns={ts_col: "timestamp"})

    if value_col is None:
        numeric = [c for c in df.select_dtypes("number").columns]
        if not numeric:
            raise ValueError("no numeric value column found in trace")
        value_col = numeric[0]
    if value_col not in df.columns:
        raise ValueError(f"value column {value_col!r} not in {list(df.columns)}")

    out = df[["timestamp", value_col]].rename(columns={value_col: "requests"})

    if unit == "per_sec":
        out["requests"] = out["requests"] * 60.0
    elif unit == "per_min":
        pass
    elif unit != "auto":
        raise ValueError(f"unknown unit: {unit}")

    return resample_to_1min(out)


def resample_to_1min(df: pd.DataFrame, agg: str = "sum") -> pd.DataFrame:
    """Resample to 1-minute buckets (UTC). Demand columns are summed,
    percentage columns would be passed through ``agg`` as given."""
    if "timestamp" not in df.columns:
        raise ValueError("DataFrame must contain a 'timestamp' column")
    d = df.copy()
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    d = d.set_index("timestamp").sort_index()

    numeric = d.select_dtypes("number").columns.tolist()
    if not numeric:
        raise DataFrameError("no numeric columns to resample")

    resampled = d[numeric].resample("1min").agg(agg)
    resampled = resampled.ffill().fillna(0.0).reset_index()
    return resampled


class DataFrameError(ValueError):
    pass


def trace_summary(df: pd.DataFrame) -> dict:
    """Basic EDA statistics for a workload trace."""
    req = df["requests"]
    return {
        "rows": len(df),
        "start": str(df["timestamp"].min()),
        "end": str(df["timestamp"].max()),
        "mean_requests": float(req.mean()),
        "std_requests": float(req.std(ddof=0)),
        "min_requests": float(req.min()),
        "max_requests": float(req.max()),
        "p90_requests": float(req.quantile(0.90)),
        "p99_requests": float(req.quantile(0.99)),
    }
