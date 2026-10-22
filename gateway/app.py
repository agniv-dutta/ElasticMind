"""HTTP gateway and lightweight CPU-burn replica pool."""

from __future__ import annotations

import asyncio
import math
import os
import statistics
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from backend.app.metrics.calculator import utilization


@dataclass
class Replica:
    replica_id: str
    running: bool = True
    in_flight: int = 0
    semaphore: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(1))


class ReplicaPool:
    def __init__(self, replicas: int = 1, concurrency: int = 1, queue_limit: int = 64,
                 cpu_burn_ms: float = 30.0, capacity_per_replica_rpm: float = 500.0):
        self.concurrency = max(1, concurrency)
        self.queue_limit = max(0, queue_limit)
        self.cpu_burn_ms = max(0.0, cpu_burn_ms)
        self.capacity_per_replica_rpm = max(1.0, capacity_per_replica_rpm)
        self._replicas: list[Replica] = []
        self._cursor = 0
        self._lock = asyncio.Lock()
        self.records: deque[dict[str, Any]] = deque(maxlen=10000)
        self.interval_latencies: list[float] = []
        self.interval_count = 0
        self.interval_errors = 0
        self.interval_started = time.monotonic()
        self.scale_to(replicas)

    @property
    def running(self) -> list[Replica]:
        return [replica for replica in self._replicas if replica.running]

    def scale_to(self, desired: int) -> list[dict[str, Any]]:
        desired = max(1, min(100, int(desired)))
        running = self.running
        if desired > len(running):
            next_id = max((int(r.replica_id.split("-")[-1]) for r in self._replicas), default=0) + 1
            for idx in range(next_id, next_id + desired - len(running)):
                self._replicas.append(Replica(f"replica-{idx}", semaphore=asyncio.Semaphore(self.concurrency)))
        elif desired < len(running):
            for replica in reversed(running[desired:]):
                replica.running = False
        return self.list_replicas()

    def list_replicas(self) -> list[dict[str, Any]]:
        return [{"replica_id": r.replica_id, "status": "RUNNING" if r.running else "STOPPED",
                 "in_flight": r.in_flight} for r in self._replicas]

    async def _reserve(self) -> Replica | None:
        async with self._lock:
            replicas = self.running
            if not replicas:
                return None
            for offset in range(len(replicas)):
                idx = (self._cursor + offset) % len(replicas)
                replica = replicas[idx]
                if replica.in_flight < self.concurrency + self.queue_limit:
                    replica.in_flight += 1
                    self._cursor = (idx + 1) % len(replicas)
                    return replica
            return None

    async def handle(self, request_id: str | None = None) -> tuple[dict[str, Any], int]:
        started = time.perf_counter()
        replica = await self._reserve()
        if replica is None:
            latency = (time.perf_counter() - started) * 1000
            self._record(request_id, None, 503, latency)
            return {"status": "saturated", "replica_id": None, "latency_ms": latency}, 503
        status = 200
        try:
            async with replica.semaphore:
                # The configured CPU-burn duration models service time without
                # blocking the gateway event loop, so independent replicas run concurrently.
                await asyncio.sleep(self.cpu_burn_ms / 1000.0)
        except Exception:
            status = 500
        finally:
            async with self._lock:
                replica.in_flight -= 1
        latency = (time.perf_counter() - started) * 1000
        result = {"status": "ok" if status == 200 else "error", "replica_id": replica.replica_id,
                  "latency_ms": round(latency, 2)}
        self._record(request_id, replica.replica_id, status, latency)
        return result, status

    def _record(self, request_id: str | None, replica_id: str | None, status: int, latency: float) -> None:
        self.records.append({"request_id": request_id, "replica_id": replica_id,
                             "status": status, "latency_ms": round(latency, 2),
                             "timestamp": time.time()})
        self.interval_count += 1
        self.interval_errors += int(status >= 400)
        self.interval_latencies.append(latency)

    async def report_interval(self, backend_url: str | None, interval_s: float) -> dict[str, Any]:
        now = time.monotonic()
        duration = max(now - self.interval_started, 1e-6)
        count, errors, latencies = self.interval_count, self.interval_errors, self.interval_latencies
        replica_count = len(self.running)
        report = {
            "requests_total": count,
            "served_requests": count - errors,
            "duration_s": duration,
            "error_rate": errors / max(count, 1),
            "success_rate": (count - errors) / max(count, 1),
            "latency_p50_ms": statistics.median(latencies) if latencies else 0.0,
            "latency_p95_ms": sorted(latencies)[max(0, math.ceil(0.95 * len(latencies)) - 1)] if latencies else 0.0,
            "utilization": utilization((count - errors) * 60.0 / duration, replica_count, self.capacity_per_replica_rpm),
            "running_replicas": replica_count,
            "simulated": True,
        }
        self.interval_count = self.interval_errors = 0
        self.interval_latencies = []
        self.interval_started = now
        if backend_url:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    await client.post(f"{backend_url.rstrip('/')}/metrics", json=report)
            except httpx.HTTPError:
                pass
        return report


pool = ReplicaPool(
    replicas=int(os.getenv("GATEWAY_INITIAL_REPLICAS", "1")),
    concurrency=int(os.getenv("GATEWAY_CONCURRENCY_PER_REPLICA", "1")),
    queue_limit=int(os.getenv("GATEWAY_QUEUE_LIMIT", "64")),
    cpu_burn_ms=float(os.getenv("GATEWAY_CPU_BURN_MS", "30")),
    capacity_per_replica_rpm=float(os.getenv("GATEWAY_CAPACITY_PER_REPLICA_RPM", "500")),
)
BACKEND_URL = os.getenv("GATEWAY_BACKEND_URL", "")
METRICS_INTERVAL_S = float(os.getenv("GATEWAY_METRICS_INTERVAL_S", "5"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    async def publisher() -> None:
        while True:
            await asyncio.sleep(METRICS_INTERVAL_S)
            await pool.report_interval(BACKEND_URL, METRICS_INTERVAL_S)

    task = asyncio.create_task(publisher())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="ElasticMind Gateway", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "running_replicas": len(pool.running)}


@app.get("/replicas")
def replicas():
    return pool.list_replicas()


@app.put("/replicas")
def scale_replicas(body: dict[str, int]):
    if "desired" not in body:
        raise HTTPException(422, "desired replica count is required")
    return {"replicas": pool.scale_to(body["desired"])}


@app.get("/requests")
def request_records():
    return list(pool.records)


@app.get("/metrics/interval")
async def metrics_interval():
    return await pool.report_interval(None, METRICS_INTERVAL_S)


@app.get("/work")
async def work(request: Request):
    result, status = await pool.handle(request.headers.get("x-request-id"))
    return JSONResponse(result, status_code=status)
