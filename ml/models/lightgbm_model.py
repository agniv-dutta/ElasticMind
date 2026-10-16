"""LightGBM multi-horizon forecaster with quantile outputs (P50, P90).

One model is trained per ``(horizon, quantile)`` pair using LightGBM's
``quantile`` objective. Features come from :mod:`ml.features.engineering`;
splits are strictly chronological to avoid leakage.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from ml.features.engineering import build_features, make_supervised
from ml.models.base import DEFAULT_HORIZONS, ForecastResult, Predictor

try:
    import lightgbm as lgb
except ImportError as exc:  # pragma: no cover
    lgb = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc

QUANTILES: tuple[float, ...] = (0.5, 0.9)


def _default_params(quantile: float, seed: int = 42) -> dict[str, Any]:
    return {
        "objective": "quantile",
        "alpha": quantile,
        "metric": "quantile",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_data_in_leaf": 30,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.9,
        "bagging_freq": 1,
        "verbose": -1,
        "seed": seed,
        "n_jobs": -1,
    }


class LightGBMMultiHorizon(Predictor):
    """Quantile LightGBM models for horizons 5/15/30 min (P50 + P90)."""

    name = "lightgbm"

    def __init__(
        self,
        horizons: tuple[int, ...] = DEFAULT_HORIZONS,
        params: dict[str, Any] | None = None,
        n_estimators: int = 400,
        val_fraction: float = 0.15,
        seed: int = 42,
    ) -> None:
        super().__init__(horizons)
        self.params = dict(params or {})
        self.n_estimators = n_estimators
        self.val_fraction = val_fraction
        self.seed = seed
        self.models_: dict[tuple[int, float], Any] = {}
        self.feature_names_: list[str] = []

    # ------------------------------------------------------------------ train
    def fit(self, history: pd.DataFrame) -> LightGBMMultiHorizon:
        if lgb is None:  # pragma: no cover
            raise ImportError(f"lightgbm required: {_IMPORT_ERROR}")
        d = self._frame(history)
        self.feature_names_ = None  # type: ignore[assignment]

        for h in self.horizons:
            sup = make_supervised(d, horizon=h)
            if len(sup) < 200:
                raise ValueError(f"not enough rows ({len(sup)}) to train horizon {h}")
            split = int(len(sup) * (1.0 - self.val_fraction))
            train, val = sup.iloc[:split], sup.iloc[split:]
            feats = [c for c in sup.columns if c not in {"timestamp", "target"}]
            self.feature_names_ = feats

            for q in QUANTILES:
                model = lgb.LGBMRegressor(
                    n_estimators=self.n_estimators,
                    **_default_params(q, self.seed),
                )
                model.fit(
                    train[feats],
                    train["target"],
                    eval_set=[(val[feats], val["target"])],
                    eval_metric="quantile",
                    callbacks=[lgb.early_stopping(30, verbose=False)],
                )
                self.models_[(h, q)] = model

        self.fitted_ = True
        return self

    # ---------------------------------------------------------------- predict
    def predict(self, history: pd.DataFrame) -> ForecastResult:
        self._require_fitted()
        d = self._frame(history)
        feat = build_features(d)
        if self.feature_names_ is None:  # pragma: no cover
            raise RuntimeError("feature names unavailable")
        missing = [c for c in self.feature_names_ if c not in feat.columns]
        if missing:
            raise ValueError(f"missing features: {missing}")
        last = feat.iloc[[-1]][self.feature_names_]
        last_ts = d["timestamp"].iloc[-1]

        rows = []
        for h in self.horizons:
            p50 = float(self.models_[(h, 0.5)].predict(last)[0])
            p90 = float(self.models_[(h, 0.9)].predict(last)[0])
            rows.append(
                {
                    "timestamp": last_ts + pd.Timedelta(minutes=h),
                    "horizon_min": h,
                    "p50": max(p50, 0.0),
                    "p90": max(p90, p50, 0.0),
                }
            )
        return ForecastResult(pd.DataFrame(rows), model=self.name)

    def explain(self, history: pd.DataFrame, horizon: int, top_k: int = 8) -> list[dict]:
        """Top feature importances for a horizon's P90 model (for E5)."""
        self._require_fitted()
        model = self.models_[(horizon, 0.9)]
        imp = model.feature_importances_
        pairs = sorted(
            zip(self.feature_names_, map(float, imp), strict=False), key=lambda x: x[1], reverse=True
        )
        return [{"feature": f, "importance": i} for f, i in pairs[:top_k]]

    # ------------------------------------------------------------ persistence
    def save(self, path: str | Path, metrics: dict | None = None) -> tuple[Path, Path]:
        """Save models with joblib + a metadata JSON alongside."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "name": self.name,
                "horizons": self.horizons,
                "models": self.models_,
                "feature_names": self.feature_names_,
                "params": self.params,
                "n_estimators": self.n_estimators,
                "quantiles": QUANTILES,
            },
            path,
        )
        meta = {
            "model": self.name,
            "horizons": list(self.horizons),
            "quantiles": list(QUANTILES),
            "features": list(self.feature_names_ or []),
            "n_estimators": self.n_estimators,
            "params": self.params,
            "metrics": metrics or {},
            "training_date": datetime.now(UTC).isoformat(),
            "artifact": path.name,
        }
        meta_path = path.with_suffix(".meta.json")
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return path, meta_path

    @classmethod
    def load(cls, path: str | Path) -> LightGBMMultiHorizon:
        blob = joblib.load(path)
        obj = cls(
            horizons=tuple(blob["horizons"]),
            params=blob.get("params") or {},
            n_estimators=blob.get("n_estimators", 400),
        )
        obj.models_ = blob["models"]
        obj.feature_names_ = blob["feature_names"]
        obj.fitted_ = True
        return obj


def load_metadata(path: str | Path) -> dict:
    """Read the metadata JSON written next to a joblib artifact."""
    return json.loads(Path(path).with_suffix(".meta.json").read_text(encoding="utf-8"))
