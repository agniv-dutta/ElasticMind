"""Target FastAPI app: lightweight service being scaled.

Endpoint /work burns configurable CPU (simulated delay) and reports
per-request latency in milliseconds.
"""

from __future__ import annotations

import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="ElasticMind Target App", version="0.1.0")

PORT = int(os.getenv("TARGET_APP_PORT", "8001"))
CPU_BURN_MS = int(os.getenv("TARGET_APP_CPU_BURN_MS", "40"))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/work")
async def work(req: Request):
    start = time.perf_counter()
    # Simulate CPU-bound work (busy wait)
    end_burn = start + CPU_BURN_MS / 1000.0
    while time.perf_counter() < end_burn:
        pass
    latency_ms = (time.perf_counter() - start) * 1000.0
    return JSONResponse(
        {
            "status": "ok",
            "latency_ms": round(latency_ms, 2),
            "simulated": True,
        }
    )
