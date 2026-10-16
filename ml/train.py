"""Training pipeline: fit predictors, backtest, export comparison + artifacts.

Usage::

    python -m ml.train --data ml/data/generated/diurnal.parquet
    python -m ml.train --data ... --models reactive_baseline holt_winters lightgbm
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from ml.evaluation import compute_metrics, rolling_backtest
from ml.models.base import DEFAULT_HORIZONS, Predictor
from ml.models.registry import build_model, save_predictor

RESULTS_CSV = Path("experiments/results/model_comparison.csv")
ARTIFACT_DIR = Path("ml/models/artifacts")


def load_history(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    if p.suffix == ".csv":
        df = pd.read_csv(p)
    else:
        df = pd.read_parquet(p)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)


def chronological_split(df: pd.DataFrame, train=0.70, val=0.15) -> tuple[pd.DataFrame, ...]:
    """No-shuffle time split: train | val | test."""
    n = len(df)
    i1, i2 = int(n * train), int(n * (train + val))
    return df.iloc[:i1], df.iloc[i1:i2], df.iloc[i2:]


def evaluate_model(
    model: Predictor,
    history: pd.DataFrame,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    stride: int = 30,
    max_points: int | None = 40,
) -> pd.DataFrame:
    """Backtest ``model`` on ``history`` (test window) and return per-horizon metrics."""
    bt = rolling_backtest(
        history,
        predict_fn=model.predict,
        horizons=horizons,
        stride=stride,
        max_points=max_points,
    )
    if bt.empty:
        return pd.DataFrame()
    rows = []
    for h, g in bt.groupby("horizon_min"):
        m = compute_metrics(g["y_true"].to_numpy(), g["y_pred_p50"].to_numpy(),
                            q90=g["y_pred_p90"].to_numpy())
        d = m.to_dict()
        d.update({"model": model.name, "horizon_min": int(h)})
        rows.append(d)
    out = pd.DataFrame(rows)
    return out[["model", "horizon_min", *compute_metrics([1.0], [1.0]).to_dict().keys()]]


def train_all(
    data_path: str | Path,
    models: list[str] | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    out_csv: Path = RESULTS_CSV,
    artifact_dir: Path = ARTIFACT_DIR,
    stride: int = 30,
    max_points: int | None = 40,
) -> pd.DataFrame:
    """Train + evaluate all requested models; write comparison CSV and artifacts."""
    df = load_history(data_path)
    train, val, test = chronological_split(df)
    # fit on train+val (standard), evaluate on test
    fit_df = pd.concat([train, val], ignore_index=True)
    names = models or ["reactive_baseline", "holt_winters", "lightgbm"]

    frames: list[pd.DataFrame] = []
    for name in names:
        t0 = time.time()
        model = build_model(name, horizons=horizons)
        model.fit(fit_df)
        metrics_df = evaluate_model(model, test, horizons=horizons, stride=stride,
                                    max_points=max_points)
        metrics_df["fit_seconds"] = round(time.time() - t0, 2)
        metrics_df["data"] = Path(data_path).name
        frames.append(metrics_df)

        artifact = artifact_dir / f"{name}.joblib"
        meta = {
            row["horizon_min"]: {
                "mae": row["mae"], "rmse": row["rmse"],
                "mape": row["mape"], "under_pred_rate": row["under_pred_rate"],
            }
            for _, row in metrics_df.iterrows()
        }
        save_predictor(model, artifact, metrics=meta)
        print(f"[train] {name}: {metrics_df['mape'].mean():.2f}% mean MAPE -> {artifact}")

    comparison = pd.concat(frames, ignore_index=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(out_csv, index=False)
    print(f"[train] wrote {out_csv}")
    return comparison


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Train ElasticMind predictors")
    p.add_argument("--data", default="ml/data/generated/diurnal.parquet")
    p.add_argument("--models", nargs="*", default=None)
    p.add_argument("--horizons", nargs="*", type=int, default=list(DEFAULT_HORIZONS))
    p.add_argument("--stride", type=int, default=30)
    p.add_argument("--max-points", type=int, default=40)
    p.add_argument("--out", default=str(RESULTS_CSV))
    args = p.parse_args(argv)
    train_all(
        args.data,
        models=args.models,
        horizons=tuple(args.horizons),
        out_csv=Path(args.out),
        stride=args.stride,
        max_points=args.max_points,
    )


if __name__ == "__main__":
    main()
