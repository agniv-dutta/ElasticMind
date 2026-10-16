# frontend/ — React dashboard (replaces Grafana)

React + Vite + TypeScript + Tailwind + Recharts. Polls the backend every 5 s.

## Panels

- Actual vs predicted load with **P50/P90 band**
- Current vs desired capacity
- Utilization, latency (p50/p95), running cost, energy totals (simulated)
- SLA-violation counter
- Scaling decision log
- KPI cards
- **Controls**: policy switch (Static / Reactive / ML), start/stop
- **Fault injection**: forecast bias ±X %, inject spike
- **Compare experiments** page reading `/experiments`

Every simulated metric is badged `simulated`; measured values are badged
`measured`.

## Run

```bash
npm install
npm run dev        # http://localhost:5173 (proxies /api -> localhost:8000)
npm run build      # production build to dist/
npm run typecheck  # tsc --noEmit
```

Set `VITE_API_BASE` to point at a non-proxied backend (e.g. in Docker it is
`/api`, served by nginx).
