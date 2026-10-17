"""Chaos test utilities and safe fallbacks (simulated)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChaosFlags:
    backend_restart: bool = False
    model_load_failure: bool = False
    stale_metrics: bool = False


def safe_fallback(reason: str = "fallback") -> dict:
    return {"status": "fallback", "reason": reason, "simulated": True}