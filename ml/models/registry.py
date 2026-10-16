"""Model registry: build, save and load predictors uniformly."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from ml.models.base import DEFAULT_HORIZONS, ForecastResult, Predictor
from ml.models.holt_winters import HoltWintersPredictor
from ml.models.lightgbm_model import LightGBMMultiHorizon, load_metadata
from ml.models.reactive import ReactiveBaseline

MODEL_CLASSES: dict[str, type[Predictor]] = {
    ReactiveBaseline.name: ReactiveBaseline,
    HoltWintersPredictor.name: HoltWintersPredictor,
    LightGBMMultiHorizon.name: LightGBMMultiHorizon,
}


def available_models() -> list[str]:
    names = list(MODEL_CLASSES)
    try:
        from ml.models.lstm import LSTMPredictor  # noqa: F401

        names.append("lstm")
    except (ImportError, RuntimeError):
        pass
    return names


def build_model(name: str, horizons: tuple[int, ...] = DEFAULT_HORIZONS, **kwargs: Any) -> Predictor:
    if name == "lstm":
        from ml.models.lstm import LSTMPredictor

        return LSTMPredictor(horizons=horizons, **kwargs)
    if name not in MODEL_CLASSES:
        raise KeyError(f"unknown model {name!r}; available: {available_models()}")
    return MODEL_CLASSES[name](horizons=horizons, **kwargs)


def save_predictor(model: Predictor, path: str | Path, metrics: dict | None = None) -> Path:
    """Persist any predictor with joblib + a metadata JSON sidecar."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(model, LightGBMMultiHorizon):
        model.save(path, metrics=metrics)
        return path

    joblib.dump(
        {"name": model.name, "horizons": model.horizons, "model": model,
         "quantiles": getattr(model, "supports_quantiles", True)},
        path,
    )
    meta = {
        "model": model.name,
        "horizons": list(model.horizons),
        "features": [],
        "metrics": metrics or {},
        "training_date": datetime.now(UTC).isoformat(),
        "artifact": path.name,
    }
    path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return path


def load_predictor(path: str | Path) -> Predictor:
    path = Path(path)
    blob = joblib.load(path)
    name = blob.get("name")
    if name == LightGBMMultiHorizon.name:
        return LightGBMMultiHorizon.load(path)
    model: Predictor = blob["model"]
    model.fitted_ = True
    return model


def predictor_metadata(path: str | Path) -> dict:
    return load_metadata(path)


def forecast_frame(model: Predictor, history: pd.DataFrame) -> ForecastResult:
    """Convenience wrapper used by the backend and experiments."""
    return model.predict(history)
