"""Holt-Winters (triple exponential smoothing) predictor via statsmodels."""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from ml.models.base import DEFAULT_HORIZONS, ForecastResult, Predictor

try:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
except ImportError as exc:  # pragma: no cover
    ExponentialSmoothing = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc


class HoltWintersPredictor(Predictor):
    """Additive Holt-Winters with daily seasonality (period = 1440 min).

    P50 = point forecast; P90 = P50 + 1.2816 * in-sample residual std
    (one-sided Gaussian approximation, documented as an assumption).
    """

    name = "holt_winters"

    def __init__(
        self,
        horizons: tuple[int, ...] = DEFAULT_HORIZONS,
        seasonal_periods: int = 1440,
        train_window: int = 1440 * 7,
        z90: float = 1.2816,
    ) -> None:
        super().__init__(horizons)
        self.seasonal_periods = seasonal_periods
        self.train_window = train_window
        self.z90 = z90
        self._residual_std: float = 0.0

    def fit(self, history: pd.DataFrame) -> HoltWintersPredictor:
        if ExponentialSmoothing is None:  # pragma: no cover
            raise ImportError(f"statsmodels required for Holt-Winters: {_IMPORT_ERROR}")
        d = self._frame(history)
        if len(d) < self.seasonal_periods * 2:
            raise ValueError(
                f"Holt-Winters needs >= {self.seasonal_periods * 2} minutes of history"
            )
        y = d["requests"].astype(float).tail(self.train_window).reset_index(drop=True)
        self._fit_series(y, seasonal=True)
        self.fitted_ = True
        return self

    def _fit_series(self, y: pd.Series, seasonal: bool) -> None:
        model = ExponentialSmoothing(
            y,
            trend="add",
            seasonal="add" if seasonal else None,
            seasonal_periods=self.seasonal_periods if seasonal else None,
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fitted = model.fit(optimized=True, use_brute=False)
        self._fitted_model_ = fitted
        resid = np.asarray(y - fitted.fittedvalues, dtype=float)
        self._residual_std = float(np.std(resid, ddof=1)) if len(resid) > 1 else 0.0
        self._last_value_ = float(y.iloc[-1])

    def predict(self, history: pd.DataFrame) -> ForecastResult:
        self._require_fitted()
        d = self._frame(history)
        last_ts = d["timestamp"].iloc[-1]

        # Forecast from the end of the series used at fit() time. The backend
        # retrains periodically; predict stays O(1) for cheap online use.
        max_h = max(self.horizons)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fc = self._fitted_model_.forecast(max_h)
        fc = np.asarray(fc, dtype=float)

        rows = []
        for h in self.horizons:
            p50 = float(fc[h - 1])
            rows.append(
                {
                    "timestamp": last_ts + pd.Timedelta(minutes=h),
                    "horizon_min": h,
                    "p50": max(p50, 0.0),
                    "p90": max(p50 + self.z90 * self._residual_std, 0.0),
                }
            )
        return ForecastResult(pd.DataFrame(rows), model=self.name)
