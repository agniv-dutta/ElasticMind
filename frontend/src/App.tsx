import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type ForecastPoint = { timestamp: string; horizon_min: number; p50: number; p90: number };

function Badge({ kind }: { kind: "measured" | "simulated" | "estimated" }) {
  const cls =
    kind === "measured"
      ? "bg-emerald-700"
      : kind === "simulated"
      ? "bg-amber-700"
      : "bg-slate-600";
  return <span className={`text-xs px-1.5 py-0.5 rounded text-white ${cls}`}>{kind}</span>;
}

function DecisionBadge({ reason }: { reason: string }) {
  const r = (reason || "").toLowerCase();
  if (r.includes("safety_net")) return <span className="text-xs px-1.5 py-0.5 rounded bg-red-700 text-white">safety net</span>;
  if (r.includes("fallback") || r.includes("reactive")) return <span className="text-xs px-1.5 py-0.5 rounded bg-orange-700 text-white">fallback</span>;
  return <span className="text-xs px-1.5 py-0.5 rounded bg-blue-700 text-white">ML</span>;
}

export default function App() {
  const [health, setHealth] = useState<any>(null);
  const [cap, setCap] = useState<any>(null);
  const [fc, setFc] = useState<any>(null);
  const [mc, setMc] = useState<any>(null);
  const [decisions, setDecisions] = useState<any[]>([]);
  const [rob, setRob] = useState<any>(null);
  const [policy, setPolicy] = useState("ml_predictive");
  const [bias, setBias] = useState(0);
  const [spike, setSpike] = useState(2);

  const poll = async () => {
    try {
      const [h, c, f, m, d, r] = await Promise.all([
        api.health().catch(() => null),
        api.capacity().catch(() => null),
        api.forecast().catch(() => null),
        api.metricsCurrent().catch(() => null),
        api.decisions().catch(() => []),
        api.robustnessStatus().catch(() => null),
      ]);
      setHealth(h);
      setCap(c);
      setFc(f);
      setMc(m);
      setDecisions(Array.isArray(d) ? d : []);
      setRob(r);
    } catch (e) {
      // ignore
    }
  };

  useEffect(() => {
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, []);

  const forecastData = useMemo(() => {
    const pts: ForecastPoint[] = fc?.forecast || [];
    return pts.map((p) => ({ ...p, horizon_min: p.horizon_min }));
  }, [fc]);

  const replicaData = useMemo(() => {
    const desired = cap?.desired_instances ?? cap?.desired ?? 0;
    const running = cap?.current_instances ?? cap?.running ?? 0;
    const starting = cap?.pending_start ?? 0;
    const draining = cap?.draining ?? 0;
    return [{ name: "replicas", desired, running, starting, draining }];
  }, [cap]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-4">
      <header className="mb-4">
        <h1 className="text-2xl font-bold">ElasticMind Dashboard</h1>
        <div className="text-sm text-slate-400 flex flex-wrap gap-3">
          <span>profile: {health?.profile || health?.env || "?"}</span>
          <span>TIME_SCALE: {health?.time_scale ?? "?"}</span>
          <span>ACTUATOR: {health?.actuator || "local"}</span>
          <span>model version: {fc?.model || cap?.model_version || rob?.model_version || "?"}</span>
        </div>
      </header>

      <section className="mb-4 bg-slate-900 rounded p-3 flex flex-wrap gap-2 items-center">
        <span className="text-sm">Policy</span>
        <select value={policy} onChange={(e) => setPolicy(e.target.value)} className="bg-slate-800 rounded px-2 py-1">
          <option value="static">static</option>
          <option value="reactive">reactive</option>
          <option value="ml_predictive">ML</option>
        </select>
        <button onClick={() => api.setPolicy(policy)} className="px-2 py-1 bg-blue-700 rounded">Apply</button>
        <button onClick={() => api.start()} className="px-2 py-1 bg-emerald-700 rounded">Start</button>
        <button onClick={() => api.stop()} className="px-2 py-1 bg-rose-700 rounded">Stop</button>
        <span className="text-sm ml-4">Bias %</span>
        <input type="number" value={bias} onChange={(e) => setBias(Number(e.target.value))} className="w-20 bg-slate-800 rounded px-2 py-1" />
        <button onClick={() => api.bias(bias)} className="px-2 py-1 bg-amber-700 rounded">Inject bias</button>
        <span className="text-sm">Spike x</span>
        <input type="number" value={spike} onChange={(e) => setSpike(Number(e.target.value))} className="w-16 bg-slate-800 rounded px-2 py-1" />
        <button onClick={() => api.spike(spike, 5)} className="px-2 py-1 bg-orange-700 rounded">Inject spike</button>
      </section>

      <section className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <div className="bg-slate-900 rounded p-3">
          <h2 className="mb-2">Replicas: desired vs running vs starting vs draining</h2>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={replicaData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis />
              <Tooltip />
              <Legend />
              <Bar dataKey="desired" stackId="a" fill="#60a5fa" />
              <Bar dataKey="running" stackId="a" fill="#22c55e" />
              <Bar dataKey="starting" stackId="a" fill="#f59e0b" />
              <Bar dataKey="draining" stackId="a" fill="#f43f5e" />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="bg-slate-900 rounded p-3">
          <h2 className="mb-2">Forecast P50/P90 vs actual (horizon shift applied)</h2>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={forecastData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="horizon_min" />
              <YAxis />
              <Tooltip />
              <Legend />
              <Area type="monotone" dataKey="p90" stackId="1" stroke="#f59e0b" fill="#f59e0b33" />
              <Area type="monotone" dataKey="p50" stackId="2" stroke="#60a5fa" fill="#60a5fa33" />
              <Line type="monotone" dataKey="actual" stroke="#22c55e" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="grid grid-cols-2 md:grid-cols-6 gap-3 mb-4">
        <div className="bg-slate-900 rounded p-2">Util <Badge kind="simulated" /> {mc?.current_utilization ?? "-"}</div>
        <div className="bg-slate-900 rounded p-2">Latency p50/p95 <Badge kind="measured" /> {mc?.latency_p50_ms ?? mc?.latency_ms ?? "-"} / {mc?.latency_p95_ms ?? "-"}</div>
        <div className="bg-slate-900 rounded p-2">SLA <Badge kind="simulated" /> {mc?.sla_count ?? mc?.sla_violations ?? 0}</div>
        <div className="bg-slate-900 rounded p-2">Cost <Badge kind="estimated" /> {mc?.cost_usd ?? "-"}</div>
        <div className="bg-slate-900 rounded p-2">Energy <Badge kind="simulated" /> {mc?.energy_kwh ?? "-"}</div>
        <div className="bg-slate-900 rounded p-2">Robust <span className="text-xs">{rob?.active_mode || "-"}</span></div>
      </section>

      <section className="bg-slate-900 rounded p-3">
        <h2 className="mb-2">Decisions (source badge)</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-400">
                <th className="py-1">time</th>
                <th>source</th>
                <th>action</th>
                <th>desired/current</th>
                <th>reason</th>
              </tr>
            </thead>
            <tbody>
              {decisions.slice(0, 50).map((d, i) => (
                <tr key={i} className="border-t border-slate-800">
                  <td className="py-1">{d.timestamp || d.ts || "-"}</td>
                  <td><DecisionBadge reason={d.reason || ""} /></td>
                  <td>{d.action || "-"}</td>
                  <td>{d.desired}/{d.current}</td>
                  <td className="truncate max-w-[500px]">{d.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}