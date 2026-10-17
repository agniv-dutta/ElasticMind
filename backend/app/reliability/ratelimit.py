"""Simple in-memory rate limiter for actuator calls."""
from __future__ import annotations

import time


class RateLimiter:
    def __init__(self, rate_per_sec: float = 1.0) -> None:
        self.rate = max(1e-6, rate_per_sec)
        self._last = 0.0

    def allow(self, now: float | None = None) -> bool:
        now = now or time.time()
        if now - self._last >= 1.0 / self.rate:
            self._last = now
            return True
        return False