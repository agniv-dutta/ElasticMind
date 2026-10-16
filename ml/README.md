# ml/ — Data, features, forecasting models, evaluation

**Simulated** workload generation and the LightGBM/Holt-Winters/baseline
forecasters used by the ElasticMind controller.

## Contents

```
ml/
├── data/        # generate.py (synthetic traces), loader.py (CSV traces)
├── features/    # engineering.py (lags, rolling stats, cyclical, roc)
├── models/      # base.py, reactive.py, holt_winters.py, lightgbm_model.py, lstm.py, registry.py
├── evaluation.py# MAE/RMSE/MAPE/under-prediction, rolling backtest
├── train.py     # training + comparison pipeline
└── tests/
```

## Quickstart

```bash
# synthetic trace
python -m ml.data.generate --profile spiky --days 14 --out ml/data/generated/spiky.parquet

# train + compare all models (chronological splits, no leakage)
python -m ml.train --data ml/data/generated/diurnal.parquet
# -> experiments/results/model_comparison.csv, ml/models/artifacts/*.joblib(.meta.json)
```

## Models

| Name | Output | Notes |
|---|---|---|
| `reactive_baseline` | P50/P90 | persistence (last value), widening band |
| `holt_winters` | P50/P90 | additive trend + daily seasonality (period 1440) |
| `lightgbm` | P50/P90 | one quantile model per (horizon, quantile) |
| `lstm` | P50/P90 | optional, requires `torch` (not installed by default) |

Horizons: **5 / 15 / 30 minutes**. Horizons and features are stored in the
metadata JSON next to each artifact (features, horizon, metrics, training date).

## Metrics

`mae`, `rmse`, `mape`, `under_pred_rate`, `pinball_90` per model/horizon —
written to `experiments/results/model_comparison.csv`.

## Labels

Every generated series and derived metric is **simulated**. Public traces can be
loaded with `ml.data.loader.load_trace_csv` and are then resampled to 1 min.
