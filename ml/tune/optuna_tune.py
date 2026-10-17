"""Optuna hyperparameter tuning for LightGBM multi-horizon (optional)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

try:
    import optuna
except ImportError:  # pragma: no cover
    optuna = None  # type: ignore


def tune(
    trace_path: str | Path | None = None,
    n_trials: int = 20,
    output: str | Path = "ml/tune/best_params.json",
    horizons: tuple[int, ...] = (5, 15, 30),
) -> dict[str, Any]:
    if optuna is None:
        raise ImportError("optuna is required for tuning")

    from ml.data.loader import load_trace
    from ml.evaluation import compute_metrics
    from ml.models.lightgbm_model import LightGBMMultiHorizon

    df = load_trace(trace_path) if trace_path else None
    if df is None:
        from ml.data.generate import generate_workload

        df = generate_workload(days=14, seed=42)

    max_h = max(horizons) if horizons else 30
    if len(df) < max_h + 300:
        raise ValueError("trace must contain at least 300 rows plus the maximum horizon")
    split = max(200, int(len(df) * 0.8))
    train = df.iloc[:split]
    validation = df.iloc[split - max_h - 1 :]

    def objective(trial: optuna.Trial) -> float:
        params = {
            "num_leaves": trial.suggest_int("num_leaves", 16, 128),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2),
            "max_depth": trial.suggest_int("max_depth", 3, 8),
            "n_estimators": trial.suggest_int("n_estimators", 100, 500),
            "min_child_samples": trial.suggest_int("min_child_samples", 10, 50),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        }
        model = LightGBMMultiHorizon(
            horizons=horizons, params=params, n_estimators=params["n_estimators"]
        ).fit(train)
        errors: list[float] = []
        step = max(1, len(validation) // 10)
        for cutoff in range(max_h + 1, len(validation), step):
            history = validation.iloc[:cutoff]
            fc = model.predict(history).frame
            actuals: list[float] = []
            predictions: list[float] = []
            for row in fc.itertuples():
                target = history["timestamp"].iloc[-1] + pd.Timedelta(minutes=row.horizon_min)
                match = df.loc[df["timestamp"] == target, "requests"]
                if not match.empty:
                    actuals.append(float(match.iloc[0]))
                    predictions.append(float(row.p50))
            if actuals:
                errors.append(float(compute_metrics(actuals, predictions)["mape"]))
        return float(sum(errors) / len(errors)) if errors else float("inf")

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials)
    best = study.best_params
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(best, indent=2))
    return best


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--trace", type=str)
    p.add_argument("--trials", type=int, default=10)
    p.add_argument("--out", type=str, default="ml/tune/best_params.json")
    args = p.parse_args()
    print(json.dumps(tune(args.trace, args.trials, args.out), indent=2))