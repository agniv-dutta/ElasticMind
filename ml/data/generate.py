"""Synthetic workload generator with seasonality, trend, noise and events.

Every series produced here is **simulated** — no real cloud measurements.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import numpy as np
import pandas as pd


class WorkloadProfile(StrEnum):
    """Named workload shapes used across the project."""

    STEADY = "steady"
    DIURNAL = "diurnal"
    SPICY = "spiky"


@dataclass
class WorkloadEvent:
    """An injected anomaly. ``kind`` ∈ flash_spike | sudden_drop | regime_shift."""

    kind: str
    start_minute: int
    duration_minutes: int = 5
    magnitude: float = 2.0

    def apply(self, demand: np.ndarray) -> np.ndarray:
        out = demand.copy()
        s = max(0, self.start_minute)
        e = min(len(out), self.start_minute + self.duration_minutes)
        if s >= e:
            return out
        if self.kind == "flash_spike":
            out[s:e] *= self.magnitude
            out[e : min(len(out), e + 3)] *= 1.0 + (self.magnitude - 1.0) * np.array(
                [0.5, 0.25, 0.1]
            )[: max(0, min(3, len(out) - e))]
        elif self.kind == "sudden_drop":
            out[s:e] *= max(0.0, 2.0 - self.magnitude)
        elif self.kind == "regime_shift":
            out[s:] *= self.magnitude
        else:
            raise ValueError(f"unknown event kind: {self.kind}")
        return out


@dataclass
class GeneratorConfig:
    profile: WorkloadProfile = WorkloadProfile.DIURNAL
    days: int = 14
    seed: int = 42
    start: str = "2024-01-01T00:00:00Z"
    base_requests: float = 300.0
    noise_frac: float = 0.08
    events: list[WorkloadEvent] = field(default_factory=list)


def _profile_demand(profile: WorkloadProfile, n: int, cfg: GeneratorConfig) -> np.ndarray:
    t = np.arange(n)
    minutes_of_day = t % 1440
    day = t // 1440

    base = np.full(n, cfg.base_requests, dtype=float)

    if profile == WorkloadProfile.STEADY:
        demand = base

    elif profile == WorkloadProfile.DIURNAL:
        daily = 0.55 * np.sin(2 * np.pi * (minutes_of_day - 360) / 1440.0)
        daily = np.clip(daily + 0.45, 0.05, None)
        weekly = 1.0 - 0.25 * ((day % 7) >= 5).astype(float)  # weekend dip
        trend = 1.0 + 0.004 * day
        demand = base * daily * weekly * trend

    elif profile == WorkloadProfile.SPICY:
        daily = 0.5 * np.sin(2 * np.pi * (minutes_of_day - 300) / 1440.0)
        daily = np.clip(daily + 0.5, 0.05, None)
        trend = 1.0 + 0.006 * day
        # bursty micro-spikes
        rng = np.random.default_rng(cfg.seed + 7)
        burst = np.ones(n)
        burst_times = rng.choice(n, size=max(3, n // 400), replace=False)
        burst[burst_times] = rng.uniform(1.6, 3.0, size=len(burst_times))
        demand = base * daily * trend * burst
    else:  # pragma: no cover - guarded by Enum
        raise ValueError(f"unknown profile: {profile}")

    return demand


def generate_workload(
    profile: WorkloadProfile | str = WorkloadProfile.DIURNAL,
    days: int = 14,
    seed: int = 42,
    start: str = "2024-01-01T00:00:00Z",
    events: list[WorkloadEvent] | None = None,
    noise_frac: float = 0.08,
    base_requests: float = 300.0,
) -> pd.DataFrame:
    """Generate a 1-minute-resolution **simulated** workload trace.

    Returns a DataFrame with columns: ``timestamp``, ``requests`` (req/min),
    ``cpu_pct`` (0-100, a linear proxy of load), ``profile``.
    """
    if isinstance(profile, str):
        profile = WorkloadProfile(profile)
    cfg = GeneratorConfig(
        profile=profile,
        days=days,
        seed=seed,
        start=start,
        noise_frac=noise_frac,
        base_requests=base_requests,
        events=list(events or []),
    )

    n = int(days * 1440)
    rng = np.random.default_rng(seed)
    demand = _profile_demand(profile, n, cfg)

    for ev in cfg.events:
        demand = ev.apply(demand)

    noise = rng.normal(0.0, noise_frac, size=n)
    demand = np.maximum(1.0, demand * (1.0 + noise))

    ts = pd.date_range(start=start, periods=n, freq="min", tz="UTC")
    cpu_pct = np.clip(5.0 + 90.0 * demand / max(demand.max(), 1.0), 0.0, 100.0)

    return pd.DataFrame(
        {
            "timestamp": ts,
            "requests": np.round(demand, 2),
            "cpu_pct": np.round(cpu_pct, 2),
            "profile": profile.value,
        }
    )


def default_events(profile: WorkloadProfile, days: int) -> list[WorkloadEvent]:
    """Deterministic demo events for the ``spiky`` profile."""
    if profile != WorkloadProfile.SPICY:
        return []
    mid = days * 1440 // 2
    return [
        WorkloadEvent("flash_spike", start_minute=mid, duration_minutes=10, magnitude=3.0),
        WorkloadEvent("regime_shift", start_minute=mid + 1440, duration_minutes=1, magnitude=1.4),
    ]


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Generate a simulated workload trace")
    p.add_argument("--profile", choices=[e.value for e in WorkloadProfile], default="diurnal")
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=str, required=True, help="output path (.parquet or .csv)")
    p.add_argument("--start", type=str, default="2024-01-01T00:00:00Z")
    args = p.parse_args(argv)

    profile = WorkloadProfile(args.profile)
    df = generate_workload(
        profile=profile, days=args.days, seed=args.seed, start=args.start,
        events=default_events(profile, args.days),
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix == ".csv":
        df.to_csv(out, index=False)
    else:
        df.to_parquet(out, index=False)
    print(f"wrote {len(df)} rows ({profile.value}, {args.days}d) -> {out}  [simulated]")


if __name__ == "__main__":
    main()
