"""Train and evaluate the short-cycle local demo forecaster (simulated data)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ml.data.generate import generate_workload
from ml.evaluation import compute_metrics
from ml.models.lightgbm_model import LightGBMMultiHorizon

ARTIFACT = Path("ml/models/artifacts/lightgbm_local_demo.joblib")
RESULT = Path("experiments/results/demo_model.csv")
HORIZONS = (5, 15, 30)


def trace(seed: int, noise: float) -> pd.DataFrame:
    return generate_workload("local_demo", seed=seed, noise_frac=noise)[["timestamp", "requests"]]


def evaluate(model: LightGBMMultiHorizon, data: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for horizon in HORIZONS:
        actual, p50, p90 = [], [], []
        for origin in range(5, len(data) - horizon):
            forecast = model.predict(data.iloc[: origin + 1]).for_horizon(horizon)
            actual.append(float(data.requests.iloc[origin + horizon]))
            p50.append(float(forecast.p50.iloc[-1]))
            p90.append(float(forecast.p90.iloc[-1]))
        metrics = compute_metrics(np.asarray(actual), np.asarray(p50), np.asarray(p90))
        rows.append({
            "profile": "local_demo", "horizon_min": horizon,
            "mae": metrics.mae, "rmse": metrics.rmse, "mape": metrics.mape,
            "under_prediction_rate": metrics.under_pred_rate,
            "p90_coverage": float(np.mean(np.asarray(actual) <= np.asarray(p90))),
            "n": metrics.n, "held_out_seed": 2026, "label": "simulated",
        })
    return pd.DataFrame(rows)


def main() -> None:
    # Independent short traces are concatenated only after feature generation,
    # so no lag can leak across cycle boundaries.
    training = [trace(seed, noise) for seed in (11, 23, 37, 41, 59, 73)
                for noise in (0.02, 0.06, 0.10, 0.16, 0.22)]
    calibration = [trace(seed, noise) for seed in (87, 97, 101, 109, 127)
                   for noise in (0.02, 0.08, 0.16, 0.24)]
    held_out = trace(2026, 0.08)
    model = LightGBMMultiHorizon(
        horizons=HORIZONS, n_estimators=180, val_fraction=0.15, seed=42,
        lags=(1, 2, 3, 5), windows=(3, 5),
        params={"n_jobs": 1},
    ).fit_segments(training)

    # Calibrate the P90 tail on a separate seed, then report coverage only on
    # the held-out seed. This makes the nominal 90% coverage meaningful.
    for horizon in HORIZONS:
        residuals: list[float] = []
        for data in calibration:
            for origin in range(5, len(data) - horizon):
                fc = model.predict(data.iloc[: origin + 1]).for_horizon(horizon)
                residuals.append(float(data.requests.iloc[origin + horizon]) - float(fc.p90.iloc[-1]))
        model.p90_offsets[horizon] = float(np.quantile(residuals, 0.90))

    results = evaluate(model, held_out)
    results.to_csv(RESULT, index=False)
    model.save(ARTIFACT, metrics={"evaluation": results.to_dict(orient="records"), "label": "simulated"})
    print(results.to_string(index=False))
    print(f"Saved {ARTIFACT} and {RESULT}")


if __name__ == "__main__":
    main()
