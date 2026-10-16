"""Tests for predictors, persistence and evaluation metrics."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.data.generate import generate_workload
from ml.evaluation import compute_metrics, rolling_backtest
from ml.models.base import quantile_loss
from ml.models.holt_winters import HoltWintersPredictor
from ml.models.lightgbm_model import LightGBMMultiHorizon, load_metadata
from ml.models.reactive import ReactiveBaseline
from ml.models.registry import available_models, build_model, load_predictor, save_predictor

HORIZONS = (5, 15, 30)


@pytest.fixture(scope="module")
def hist() -> pd.DataFrame:
    return generate_workload(profile="diurnal", days=3, seed=42)


@pytest.fixture(scope="module")
def fitted_baseline(hist: pd.DataFrame) -> ReactiveBaseline:
    return ReactiveBaseline(horizons=HORIZONS).fit(hist)


def test_registry_lists_models() -> None:
    names = available_models()
    assert {"reactive_baseline", "holt_winters", "lightgbm"} <= set(names)


def test_baseline_shape_and_quantiles(fitted_baseline: ReactiveBaseline, hist: pd.DataFrame) -> None:
    fc = fitted_baseline.predict(hist)
    assert len(fc.frame) == len(HORIZONS)
    assert set(fc.frame["horizon_min"]) == set(HORIZONS)
    assert (fc.frame["p90"] >= fc.frame["p50"]).all()
    # persistence: p50 equals last observed value
    assert fc.latest(15)[0] == pytest.approx(hist["requests"].iloc[-1])


def test_baseline_requires_fit(hist: pd.DataFrame) -> None:
    with pytest.raises(RuntimeError):
        ReactiveBaseline().predict(hist)


def test_holt_winters_forecast(hist: pd.DataFrame) -> None:
    model = HoltWintersPredictor(horizons=HORIZONS).fit(hist)
    fc = model.predict(hist)
    assert len(fc.frame) == 3
    assert (fc.frame["p50"] >= 0).all()
    assert (fc.frame["p90"] >= fc.frame["p50"]).all()
    # sane magnitude: non-negative and within the observed range
    assert (fc.frame["p50"] >= 0).all()
    assert fc.frame["p50"].max() <= hist["requests"].max() * 1.5


def test_holt_winters_needs_enough_history() -> None:
    tiny = generate_workload(days=1, seed=1)
    with pytest.raises(ValueError):
        HoltWintersPredictor().fit(tiny)


def test_lightgbm_train_predict_roundtrip(hist: pd.DataFrame, tmp_path: Path) -> None:
    model = LightGBMMultiHorizon(horizons=HORIZONS, n_estimators=60).fit(hist)
    fc = model.predict(hist)
    assert len(fc.frame) == 3
    assert (fc.frame["p90"] >= fc.frame["p50"]).all()
    assert (fc.frame["p50"] >= 0).all()

    path = tmp_path / "lgb.joblib"
    save_predictor(model, path, metrics={"15": {"mape": 5.0}})
    meta = load_metadata(path)
    assert meta["horizons"] == list(HORIZONS)
    assert meta["features"]
    assert meta["metrics"]["15"]["mape"] == 5.0
    assert meta["training_date"]

    reloaded = load_predictor(path)
    fc2 = reloaded.predict(hist)
    np.testing.assert_allclose(fc.frame["p50"], fc2.frame["p50"])


def test_lightgbm_explain(hist: pd.DataFrame) -> None:
    model = LightGBMMultiHorizon(horizons=HORIZONS, n_estimators=40).fit(hist)
    top = model.explain(hist, horizon=15, top_k=5)
    assert len(top) == 5
    assert top[0]["importance"] >= top[-1]["importance"]


def test_metrics_perfect_prediction() -> None:
    y = np.array([10.0, 20.0, 30.0])
    m = compute_metrics(y, y)
    assert m.mae == 0.0 and m.rmse == 0.0 and m.mape == 0.0
    assert m.under_pred_rate == 0.0
    assert m.n == 3


def test_metrics_under_prediction_rate() -> None:
    y = np.array([10.0, 10.0, 10.0])
    p = np.array([5.0, 5.0, 10.0])
    m = compute_metrics(y, p)
    assert m.under_pred_rate == pytest.approx(2 / 3)
    assert m.mae == pytest.approx((5 + 5 + 0) / 3)


def test_metrics_rejects_empty() -> None:
    with pytest.raises(ValueError):
        compute_metrics(np.array([]), np.array([]))


def test_quantile_loss_non_negative() -> None:
    y = np.array([1.0, 2.0, 3.0])
    q = np.array([2.0, 2.0, 2.0])
    assert quantile_loss(y, q, 0.9) >= 0


def test_rolling_backtest_no_future_leakage(hist: pd.DataFrame) -> None:
    """Baseline p50 at origin i must equal requests[i] (uses only the past)."""
    bt = rolling_backtest(hist, ReactiveBaseline(horizons=HORIZONS).fit(hist).predict,
                          horizons=HORIZONS, stride=120, max_points=5)
    assert not bt.empty
    idx = {ts: i for i, ts in enumerate(hist["timestamp"])}
    for _, row in bt.iterrows():
        i = idx[row["origin"]]
        assert row["y_pred_p50"] == pytest.approx(hist["requests"].iloc[i])
        assert row["y_true"] == pytest.approx(hist["requests"].iloc[i + int(row["horizon_min"])])


def test_build_model_unknown() -> None:
    with pytest.raises(KeyError):
        build_model("nope")
