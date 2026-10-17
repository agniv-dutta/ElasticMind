"""Carbon intensity (static/time-of-day profile, simulated)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class CarbonConfig:
    intensity_gco2_kwh: float = 400.0  # simulated average
    peak_intensity_gco2_kwh: float = 600.0
    low_intensity_gco2_kwh: float = 250.0


def intensity_now(ts: datetime | None = None) -> float:
    ts = ts or datetime.now(UTC)
    h = ts.hour
    if 0 <= h < 6:
        return 250.0
    if 6 <= h < 9 or 17 <= h < 22:
        return 550.0
    return 400.0


def carbon_aware_window(
    start_hour: int,
    duration_hours: int,
    config: CarbonConfig | None = None,
) -> dict[str, float | int]:
    """Select a batch window and estimate emissions versus the baseline."""
    config = config or CarbonConfig()
    hours = [(start_hour + i) % 24 for i in range(max(1, duration_hours))]
    intensities = [intensity_now(datetime(2026, 1, 1, h, tzinfo=UTC)) for h in hours]
    average = sum(intensities) / len(intensities)
    saved = max(0.0, config.intensity_gco2_kwh - average)
    return {
        "start_hour": start_hour % 24,
        "duration_hours": len(hours),
        "average_intensity_gco2_kwh": average,
        "saved_gco2_per_kwh": saved,
    }