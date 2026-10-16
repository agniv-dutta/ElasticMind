"""Optional LSTM predictor (requires torch). Not installed by default.

Train a small GRU over recent history to forecast each horizon. Kept behind
an import guard so the core project never depends on torch.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from ml.features.engineering import build_features, feature_columns
from ml.models.base import DEFAULT_HORIZONS, ForecastResult, Predictor

try:
    import torch
    from torch import nn

    TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    TORCH_AVAILABLE = False


if TORCH_AVAILABLE:  # pragma: no cover - exercised only when torch installed

    class _GRUNet(nn.Module):
        def __init__(self, n_features: int, hidden: int = 32) -> None:
            super().__init__()
            self.gru = nn.GRU(n_features, hidden, batch_first=True)
            self.head = nn.Linear(hidden, 1)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            out, _ = self.gru(x)
            return self.head(out[:, -1, :]).squeeze(-1)


class LSTMPredictor(Predictor):  # pragma: no cover - optional dependency
    """Multi-horizon GRU forecaster. P90 = P50 + z * rolling residual std."""

    name = "lstm"

    def __init__(
        self,
        horizons: tuple[int, ...] = DEFAULT_HORIZONS,
        lookback: int = 120,
        epochs: int = 15,
        lr: float = 1e-3,
        seed: int = 42,
        z90: float = 1.2816,
    ) -> None:
        super().__init__(horizons)
        if not TORCH_AVAILABLE:
            raise ImportError("torch is required for LSTMPredictor (pip install torch)")
        self.lookback = lookback
        self.epochs = epochs
        self.lr = lr
        self.seed = seed
        self.z90 = z90
        self._nets: dict[int, _GRUNet] = {}
        self._resid_std: dict[int, float] = {}

    def _matrix(self, history: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
        feat = build_features(history)
        names = feature_columns(feat)
        return feat[names].to_numpy(dtype=np.float32), names

    def fit(self, history: pd.DataFrame) -> LSTMPredictor:
        torch.manual_seed(self.seed)
        X, names = self._matrix(history)
        y = history["requests"].to_numpy(dtype=np.float32)
        for h in self.horizons:
            net = _GRUNet(X.shape[1])
            opt = torch.optim.Adam(net.parameters(), lr=self.lr)
            lossf = nn.MSELoss()
            xs, ys = [], []
            for i in range(self.lookback, len(X) - h):
                xs.append(X[i - self.lookback : i])
                ys.append(y[i + h - 1])
            if len(xs) < 50:
                raise ValueError(f"not enough samples for horizon {h}")
            xt = torch.tensor(np.stack(xs))
            yt = torch.tensor(np.array(ys))
            net.train()
            for _ in range(self.epochs):
                opt.zero_grad()
                loss = lossf(net(xt), yt)
                loss.backward()
                opt.step()
            with torch.no_grad():
                resid = (net(xt) - yt).abs().numpy()
            self._resid_std[h] = float(np.std(resid, ddof=1)) if len(resid) > 1 else 0.0
            self._nets[h] = net
        self.feature_names_ = names  # type: ignore[attr-defined]
        self.fitted_ = True
        return self

    def predict(self, history: pd.DataFrame) -> ForecastResult:
        self._require_fitted()
        X, _ = self._matrix(history)
        tail = X[-self.lookback :][None, ...]
        last_ts = pd.to_datetime(history["timestamp"].iloc[-1], utc=True)
        rows = []
        with torch.no_grad():
            for h in self.horizons:
                p50 = float(self._nets[h](torch.tensor(tail)).item())
                rows.append(
                    {
                        "timestamp": last_ts + pd.Timedelta(minutes=h),
                        "horizon_min": h,
                        "p50": max(p50, 0.0),
                        "p90": max(p50 + self.z90 * self._resid_std[h], 0.0),
                    }
                )
        return ForecastResult(pd.DataFrame(rows), model=self.name)


def available() -> bool:
    return TORCH_AVAILABLE


def warn_if_unavailable() -> None:
    if not TORCH_AVAILABLE:  # pragma: no cover
        warnings.warn("torch not installed; LSTM predictor disabled", stacklevel=2)
