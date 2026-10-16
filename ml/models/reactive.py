"""Reactive baseline predictor: persistence (last value) with a naive band."""

from __future__ import annotations

import pandas as pd

from ml.models.base import DEFAULT_HORIZONS, ForecastResult, Predictor


class ReactiveBaseline(Predictor):
    """Predicts ``requests[t + h] = requests[t]`` for every horizon.

    The P90 band widens linearly with the horizon to reflect that uncertainty
    grows further out (``p90 = p50 * (1 + band_slope * sqrt(horizon))``).
    """

    name = "reactive_baseline"

    def __init__(
        self,
        horizons: tuple[int, ...] = DEFAULT_HORIZONS,
        band_slope: float = 0.12,
    ) -> None:
        super().__init__(horizons)
        self.band_slope = band_slope

    def fit(self, history: pd.DataFrame) -> ReactiveBaseline:
        self._frame(history)  # validate shape
        self.fitted_ = True
        return self

    def predict(self, history: pd.DataFrame) -> ForecastResult:
        self._require_fitted()
        d = self._frame(history)
        last_ts = d["timestamp"].iloc[-1]
        last = float(d["requests"].iloc[-1])

        rows = []
        for h in self.horizons:
            rows.append(
                {
                    "timestamp": last_ts + pd.Timedelta(minutes=h),
                    "horizon_min": h,
                    "p50": last,
                    "p90": last * (1.0 + self.band_slope * (h**0.5)),
                }
            )
        return ForecastResult(pd.DataFrame(rows), model=self.name)
