import { useEffect, useState } from 'react'
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  api,
  Capacity,
  Decision,
  ExperimentRow,
  ForecastPoint,
  Metrics,
} from './api'

const POLL_MS = 5000

function SimBadge({ simulated }: { simulated: boolean }) {
  return simulated ? (
    <span className="badge-sim">simulated</span>
  ) : (
    <span className="badge-meas">measured</span>
  )
}

function KpiCard({
  label,
  value,
  unit,
  simulated = true,
}: {
  label: string
  value: string | number
  unit?: string
  simulated?: boolean
}) {
  return (
    <div className="card">
      <div className="flex items-center justify-between">
        <span className="text-xs uppercase tracking-wider text-slate-400">{label}</span>
        <SimBadge simulated={simulated} />
      </div>
      <div className="kpi-value mt-2">
        {value}
        {unit && <span className="text-sm text-slate-400 ml-1">{unit}</span>}
      </div>
    </div>
  )
}

export default function App() {
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [capacity, setCapacity] = useState<Capacity | null>(null)
  const [forecast, setForecast] = useState<ForecastPoint[]>([])
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [experiments, setExperiments] = useState<ExperimentRow[]>([])
  const [policy, setPolicy] = useState<string>('ml')
  const [page, setPage] = useState<'dashboard' | 'experiments'>('dashboard')
  const [bias, setBias] = useState(0)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const [m, c, f, d, e] = await Promise.all([
          api.metrics(),
          api.capacity(),
          api.forecast(),
          api.decisions(),
          api.experiments(),
        ])
        if (!alive) return
        setMetrics(m)
        setCapacity(c)
        setForecast(f.forecast)
        setDecisions(d)
        setExperiments(e)
        setErr(null)
      } catch (e) {
        if (alive) setErr(String(e))
      }
    }
    tick()
    const id = setInterval(tick, POLL_MS)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [])

  const chartData = forecast.map((f) => ({
    t: new Date(f.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    p50: f.p50,
    p90: f.p90,
    band: f.p90 - f.p50,
  }))

  return (
    <div className="min-h-screen p-4 md:p-6 space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-white">ElasticMind</h1>
          <p className="text-xs text-slate-400">ML-driven cloud resource manager</p>
        </div>
        <nav className="flex gap-2">
          <button
            className={`px-3 py-1.5 rounded text-sm ${page === 'dashboard' ? 'bg-accent text-ink' : 'bg-panel text-slate-300'}`}
            onClick={() => setPage('dashboard')}
          >
            Dashboard
          </button>
          <button
            className={`px-3 py-1.5 rounded text-sm ${page === 'experiments' ? 'bg-accent text-ink' : 'bg-panel text-slate-300'}`}
            onClick={() => setPage('experiments')}
          >
            Compare experiments
          </button>
        </nav>
      </header>

      {err && (
        <div className="card border-danger/50 text-danger text-sm">backend unreachable: {err}</div>
      )}

      {page === 'dashboard' ? (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KpiCard
              label="utilization"
              value={metrics ? (metrics.current_utilization * 100).toFixed(0) : '–'}
              unit="%"
            />
            <KpiCard label="latency" value={metrics ? metrics.latency_ms.toFixed(1) : '–'} unit="ms" />
            <KpiCard label="running cost" value={metrics ? metrics.cost_usd.toFixed(3) : '–'} unit="USD" />
            <KpiCard label="energy" value={metrics ? metrics.energy_kwh.toFixed(2) : '–'} unit="kWh" />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            <div className="card lg:col-span-2">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-white">
                  Actual vs predicted load (P50/P90 band)
                </h2>
                <SimBadge simulated />
              </div>
              <div className="h-56 mt-2">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                    <XAxis dataKey="t" tick={{ fill: '#94a3b8', fontSize: 10 }} />
                    <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} />
                    <Tooltip />
                    <Area type="monotone" dataKey="p90" stroke="#fbbf24" fill="#fbbf2433" fillOpacity={0.3} />
                    <Line type="monotone" dataKey="p50" stroke="#5eead4" dot={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="card">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-white">Capacity</h2>
                <SimBadge simulated />
              </div>
              <div className="h-56 mt-2">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart
                    data={[
                      { name: 'current', v: capacity?.current_instances ?? 0 },
                      { name: 'desired', v: capacity?.desired_instances ?? 0 },
                    ]}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                    <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 10 }} />
                    <YAxis allowDecimals={false} tick={{ fill: '#94a3b8', fontSize: 10 }} />
                    <Tooltip />
                    <Bar dataKey="v" fill="#5eead4" />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
              <p className="text-xs text-slate-400 mt-1">
                SLA violations: <span className="text-danger">{metrics?.sla_count ?? 0}</span>
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            <div className="card">
              <h2 className="text-sm font-semibold text-white mb-2">Controls</h2>
              <div className="flex gap-2 mb-3">
                {['static', 'reactive', 'ml'].map((p) => (
                  <button
                    key={p}
                    className={`px-2.5 py-1 rounded text-xs ${policy === p ? 'bg-accent text-ink' : 'bg-slate-700 text-slate-200'}`}
                    onClick={async () => {
                      setPolicy(p)
                      await api.policy(p)
                    }}
                  >
                    {p}
                  </button>
                ))}
              </div>
              <div className="flex gap-2">
                <button className="px-3 py-1.5 rounded bg-accent text-ink text-sm" onClick={() => api.start()}>
                  Start
                </button>
                <button className="px-3 py-1.5 rounded bg-danger text-ink text-sm" onClick={() => api.stop()}>
                  Stop
                </button>
              </div>
            </div>

            <div className="card">
              <h2 className="text-sm font-semibold text-white mb-2">Fault injection</h2>
              <label className="text-xs text-slate-400">Forecast bias</label>
              <div className="flex items-center gap-2 mt-1 mb-3">
                <input
                  type="range"
                  min={-50}
                  max={50}
                  value={bias}
                  onChange={(e) => setBias(Number(e.target.value))}
                  className="flex-1"
                />
                <span className="text-xs w-12 text-right">{bias > 0 ? `+${bias}` : bias}%</span>
                <button
                  className="px-2 py-1 rounded bg-warn text-ink text-xs"
                  onClick={() => api.bias(bias)}
                >
                  Apply
                </button>
              </div>
              <button
                className="px-3 py-1.5 rounded bg-warn text-ink text-sm"
                onClick={() => api.spike(3.0, 5)}
              >
                Inject spike (3x, 5 min)
              </button>
            </div>

            <div className="card">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-white">Decision log</h2>
                <SimBadge simulated />
              </div>
              <div className="max-h-40 overflow-y-auto mt-2 text-xs">
                <table className="w-full">
                  <thead className="text-slate-500">
                    <tr>
                      <th className="text-left">t</th>
                      <th className="text-left">act</th>
                      <th className="text-left">c→d</th>
                      <th className="text-left">reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {decisions.slice(0, 20).map((d) => (
                      <tr key={d.id} className="border-t border-slate-800">
                        <td className="py-0.5">{new Date(d.timestamp).toLocaleTimeString()}</td>
                        <td className={d.action === 'scale_up' ? 'text-accent' : d.action === 'scale_down' ? 'text-warn' : 'text-slate-500'}>
                          {d.action}
                        </td>
                        <td>
                          {d.current}→{d.desired}
                        </td>
                        <td className="truncate max-w-[140px] text-slate-400">{d.reason}</td>
                      </tr>
                    ))}
                    {decisions.length === 0 && (
                      <tr>
                        <td colSpan={4} className="text-slate-500 py-2">
                          no decisions yet
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </>
      ) : (
        <div className="card">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-white">Compare experiments (simulated)</h2>
            <SimBadge simulated />
          </div>
          <div className="overflow-x-auto mt-3">
            <table className="w-full text-xs">
              <thead className="text-slate-500">
                <tr>
                  <th className="text-left p-1">policy</th>
                  <th className="text-left p-1">avg util %</th>
                  <th className="text-left p-1">SLA viol</th>
                  <th className="text-left p-1">avg lat (ms)</th>
                  <th className="text-left p-1">cost (USD)</th>
                  <th className="text-left p-1">energy (kWh)</th>
                </tr>
              </thead>
              <tbody>
                {experiments.map((e, i) => (
                  <tr key={i} className="border-t border-slate-800">
                    <td className="p-1 text-accent">{e.policy}</td>
                    <td className="p-1">{((e.avg_utilization as number) * 100).toFixed(1)}</td>
                    <td className="p-1 text-danger">{e.sla_violations_total}</td>
                    <td className="p-1">{(e.avg_latency_ms as number).toFixed(2)}</td>
                    <td className="p-1">{(e.total_cost_usd as number).toFixed(3)}</td>
                    <td className="p-1">{(e.total_energy_kwh as number).toFixed(3)}</td>
                  </tr>
                ))}
                {experiments.length === 0 && (
                  <tr>
                    <td colSpan={6} className="text-slate-500 p-2">
                      no experiment rows in backend; run experiments/run_eval.py
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
