"""SHAP-based explanations (optional dependency)."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

try:
    import shap
except ImportError:  # pragma: no cover
    shap = None  # type: ignore


def explain_lightgbm(model, X: pd.DataFrame, top_k: int = 10) -> list[dict[str, Any]]:
    if shap is None or model is None:
        return []
    try:
        explainer = shap.TreeExplainer(model.models_[(min(model.horizons), 0.5)]) if hasattr(model, "models_") else shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X.values)
        if isinstance(shap_values, list):
            sv = shap_values[0]
        else:
            sv = np.array(shap_values)
        mean_abs = np.abs(sv).mean(axis=0)
        pairs = sorted(zip(X.columns, mean_abs, strict=True), key=lambda x: x[1], reverse=True)
        return [{"feature": f, "importance": float(i)} for f, i in pairs[:top_k]]
    except Exception:
        return []