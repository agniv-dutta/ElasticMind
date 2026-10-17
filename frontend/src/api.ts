const BASE = import.meta.env.VITE_API_BASE ?? ''

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`)
  if (!r.ok) throw new Error(`${path} -> ${r.status}`)
  return r.json() as Promise<T>
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!r.ok) throw new Error(`${path} -> ${r.status}`)
  return r.json() as Promise<T>
}

export type ForecastPoint = {
  timestamp: string
  horizon_min: number
  p50: number
  p90: number
}

export type Metrics = {
  current_utilization: number
  latency_ms: number
  cost_usd: number
  energy_kwh: number
  sla_count: number
  timestamp: string
}

export type Capacity = {
  current_instances: number
  desired_instances: number | null
  capacity_per_instance: number
  target_utilization: number
}

export type Decision = {
  id: number
  timestamp: string
  desired: number
  current: number
  action: string
  reason: string
  p50: number
  p90: number
}

export type ExperimentRow = {
  policy: string
  trace: string
  total_minutes: number
  avg_utilization: number
  sla_violations_total: number
  avg_latency_ms: number
  total_cost_usd: number
  total_energy_kwh: number
  [k: string]: unknown
}

export type ModelMetric = {
  model: string
  horizon_min: number
  mape: number
  mae: number
  rmse: number
  under_pred_rate: number
}

export type ParetoPoint = {
  policy: string
  cost_sim: number
  sla_viol_sim: number
}

export const api = {
  forecast: () => get<{ model: string; forecast: ForecastPoint[] }>('/forecast'),
  metrics: () => get<Metrics>('/metrics'),
  capacity: () => get<Capacity>('/capacity'),
  decisions: () => get<Decision[]>('/decisions'),
  experiments: () => get<ExperimentRow[]>('/experiments'),
  modelComparison: () => get<ModelMetric[]>('/models/comparison'),
  pareto: () => get<ParetoPoint[]>('/policies/pareto'),
  start: () => post('/autoscaler/start'),
  stop: () => post('/autoscaler/stop'),
  policy: (policy: string) => post('/autoscaler/policy', { policy }),
  bias: (bias_percent: number) => post('/faults/bias', { bias_percent }),
  spike: (magnitude: number, duration_minutes: number) =>
    post('/faults/spike', { magnitude, duration_minutes }),
}
