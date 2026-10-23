import { useEffect, useMemo, useState } from 'react';
import { api } from './api';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

/* ---------- formatting helpers ---------- */
function fmtNum(v: any, digits = 1): string {
  const n = Number(v);
  if (v == null || !isFinite(n)) return '-';
  return n.toFixed(digits);
}
function fmtPct(v: any): string {
  const n = Number(v);
  if (v == null || !isFinite(n)) return '-';
  return (n * 100).toFixed(1) + '%';
}
function fmtUsd(v: any): string {
  const n = Number(v);
  if (v == null || !isFinite(n)) return '-';
  return '$' + n.toFixed(4);
}
function fmtWh(kwh: any): string {
  const n = Number(kwh);
  if (kwh == null || !isFinite(n)) return '-';
  return (n * 1000).toFixed(3) + ' Wh';
}
function fmtTime(iso: any): string {
  if (!iso) return '-';
  const d = new Date(iso);
  return isNaN(d.getTime()) ? String(iso) : d.toLocaleTimeString();
}
function fmtClock(epochSeconds: any): string {
  const n = Number(epochSeconds);
  if (!epochSeconds || !isFinite(n)) return '';
  return new Date(n * 1000).toLocaleTimeString();
}

/* ---------- provenance badge (uses theme classes) ---------- */
function Provenance({ kind }: { kind?: string }) {
  const k = (kind || '').toLowerCase();
  if (k === 'measured') return <span className='badge-meas'>measured</span>;
  if (k === 'simulated') return <span className='badge-sim'>simulated</span>;
  if (k === 'estimated') return <span className='badge-sim'>estimated</span>;
  return null;
}

function DecisionBadge(props: any) {
  const r = (props.reason || '').toLowerCase();
  if (props.source === 'safety_net' || r.indexOf('safety') >= 0)
    return <span className='text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-danger/20 text-danger border border-danger/40'>safety net</span>;
  if (r.indexOf('fallback') >= 0 || r.indexOf('reactive') >= 0)
    return <span className='text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-warn/20 text-warn border border-warn/40'>fallback</span>;
  return <span className='text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-accent/20 text-accent border border-accent/40'>ML</span>;
}

/* ---------- status pill with dot ---------- */
function Pill({ label, value, tone = 'slate' }: { label: string; value: any; tone?: 'green' | 'amber' | 'red' | 'slate' | 'accent' }) {
  const dot =
    tone === 'green' ? 'bg-emerald-400' :
    tone === 'amber' ? 'bg-warn' :
    tone === 'red' ? 'bg-danger' :
    tone === 'accent' ? 'bg-accent' : 'bg-slate-500';
  return (
    <span className='inline-flex items-center gap-1.5 bg-panel/60 border border-slate-700/50 rounded-full px-2.5 py-1 text-xs'>
      <span className={'w-1.5 h-1.5 rounded-full ' + dot}></span>
      <span className='text-slate-400'>{label}</span>
      <span className='text-slate-100 font-medium'>{value}</span>
    </span>
  );
}

/* ---------- KPI stat card ---------- */
function Stat({ label, value, sub, kind, tone }: { label: string; value: any; sub?: any; kind?: string; tone?: string }) {
  return (
    <div className='card flex flex-col gap-1 min-w-0'>
      <div className='flex items-center justify-between gap-2'>
        <span className='text-[11px] uppercase tracking-wider text-slate-400'>{label}</span>
        {kind ? <Provenance kind={kind} /> : null}
      </div>
      <div className={'kpi-value truncate ' + (tone || 'text-white')}>{value}</div>
      {sub != null ? <div className='text-xs text-slate-400 truncate'>{sub}</div> : null}
    </div>
  );
}

const ACTION_TONE: Record<string, string> = {
  scale_up: 'text-emerald-400',
  scale_down: 'text-danger',
  no_change: 'text-slate-400',
};

export default function App() {
  const [config, setConfig] = useState<any>(null);
  const [systemStatus, setSystemStatus] = useState<any>(null);
  const [fc, setFc] = useState<any>(null);
  const [mc, setMc] = useState<any>(null);
  const [decisions, setDecisions] = useState<any[]>([]);
  const [rob, setRob] = useState<any>(null);
  const [policy, setPolicy] = useState('ml');
  const [bias, setBias] = useState(0);
  const [spike, setSpike] = useState(2);
  const [flash, setFlash] = useState<string | null>(null);

  const poll = async function () {
    try {
      const cfg = await api.config().catch(function () { return null; });
      const status = await api.status().catch(function () { return null; });
      const f = await api.forecast().catch(function () { return null; });
      const m = await api.metricsCurrent().catch(function () { return null; });
      const d = await api.decisions().catch(function () { return []; });
      const r = await api.robustnessStatus().catch(function () { return null; });
      setConfig(cfg); setSystemStatus(status); setFc(f); setMc(m);
      setDecisions(Array.isArray(d) ? d : []); setRob(r);
    } catch (e) {}
  };

  useEffect(function () { poll(); const id = setInterval(poll, 5000); return function () { clearInterval(id); }; }, []);

  // keep the policy dropdown in sync with the backend's actual policy
  useEffect(function () {
    if (config?.current_policy) setPolicy(config.current_policy);
  }, [config?.current_policy]);

  function notify(msg: string) {
    setFlash(msg);
    setTimeout(function () { setFlash(null); }, 4000);
  }

  /* ---------- forecast series (history + horizon, with confidence band) ---------- */
  const forecastData = useMemo(function () {
    const history = (fc && fc.history)
      ? fc.history.map(function (p: any) { return { timestamp: p.timestamp, actual: p.actual, range: null }; })
      : [];
    const now = Date.now();
    const pts = (fc && fc.forecast) ? fc.forecast : [];
    const shifted = pts.map(function (p: any) {
      const lower = p.p90_lower != null ? p.p90_lower : null;
      const upper = p.p90_upper != null ? p.p90_upper : null;
      return {
        timestamp: new Date(now + Number(p.horizon_min) * 60000).toISOString(),
        p50: p.p50, p90: p.p90,
        range: lower != null && upper != null ? [lower, upper] : null,
      };
    });
    return history.concat(shifted).sort(function (a: any, b: any) { return Date.parse(a.timestamp) - Date.parse(b.timestamp); });
  }, [fc]);

  /* ---------- replica series from decisions ---------- */
  const replicaData = useMemo(function () {
    return (decisions || [])
      .filter(function (d: any) { return Date.now() - Date.parse(d.timestamp) <= 30 * 60 * 1000; })
      .slice().reverse()
      .map(function (d: any) {
        return {
          timestamp: d.timestamp,
          desired: d.desired ?? d.final_desired ?? 0,
          running: d.running_replicas ?? d.current ?? 0,
          starting: d.starting_replicas ?? 0,
          draining: d.draining_replicas ?? 0,
        };
      });
  }, [decisions]);

  const replicaFallback = [{ timestamp: new Date().toISOString(), desired: config?.MIN_REPLICAS || 1, running: 1, starting: 0, draining: 0 }];

  /* ---------- history readiness ---------- */
  const hp = fc?.history_points || 0;
  const need = fc?.min_history_points || config?.min_history_points || 60;
  const ready = hp >= need;
  const etaMin = fc?.history_eta_seconds != null
    ? Math.ceil(fc.history_eta_seconds / 60)
    : Math.max(0, Math.ceil((need - hp) * (fc?.sample_interval_s || config?.sample_interval_s || 5) / 60));

  /* ---------- active faults (for banner + button states) ---------- */
  const biasPct = Number(config?.forecast_bias_percent || 0);
  const spikeInfo = config?.load_spike;
  const spikeActive = spikeInfo && Number(spikeInfo.until) * 1000 > Date.now();

  const axisTick = { fontSize: 10, fill: '#94a3b8' };
  const tooltipStyle = { backgroundColor: '#141a2e', border: '1px solid #334155', borderRadius: 8, fontSize: 12 };

  return (
    <div className='min-h-screen text-slate-200 p-4 md:p-6'>
      {/* header */}
      <header className='mb-5'>
        <div className='flex items-center gap-3'>
          <div className='w-9 h-9 rounded-lg bg-accent/20 border border-accent/40 grid place-items-center'>
            <span className='text-accent font-bold text-lg'>EM</span>
          </div>
          <div>
            <h1 className='text-2xl font-bold text-white tracking-tight'>ElasticMind</h1>
            <p className='text-xs text-slate-400'>ML cloud autoscaler &middot; live control loop</p>
          </div>
        </div>
        <div className='mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400'>
          <span>profile <span className='text-slate-200'>{config?.profile || '?'}</span></span>
          <span>TIME_SCALE <span className='text-slate-200'>{config?.time_scale ?? '?'}</span></span>
          <span>ACTUATOR <span className='text-slate-200'>{config?.actuator || '?'}</span></span>
          <span>model <span className='text-slate-200'>{String(config?.model_version || '?').split('/').pop()}</span></span>
          <span>capacity/replica <span className='text-slate-200'>{config?.CAPACITY_PER_REPLICA_RPM ?? '?'} rpm</span></span>
          <span>scale-up threshold <span className='text-warn'>{config?.scale_up_threshold_rpm ?? '?'} rpm</span></span>
        </div>
      </header>

      {/* fault confirmation banner */}
      {flash && (
        <div className='mb-4 card border-accent/40 bg-accent/10 text-accent text-sm'>{flash}</div>
      )}
      {(biasPct !== 0 || spikeActive) && (
        <div className='mb-4 card border-warn/40 bg-warn/10 text-sm flex flex-wrap gap-x-6 gap-y-1'>
          <span className='text-warn font-medium'>Active faults (simulated):</span>
          {biasPct !== 0 && <span>forecast bias <span className='text-white font-medium'>{biasPct > 0 ? '+' : ''}{biasPct}%</span></span>}
          {spikeActive && <span>load spike <span className='text-white font-medium'>x{spikeInfo.magnitude}</span> until {fmtClock(spikeInfo.until)}</span>}
        </div>
      )}

      {/* status strip */}
      <section className='mb-4 flex flex-wrap gap-2 text-xs'>
        <Pill label='autoscaler' value={config?.loop_paused ? 'paused' : (config?.autoscaler_running ? 'running' : 'stopped')} tone={config?.loop_paused ? 'amber' : (config?.autoscaler_running ? 'green' : 'red')} />
        <Pill label='gateway' value={systemStatus?.gateway_connected ? 'connected' : 'offline'} tone={systemStatus?.gateway_connected ? 'green' : 'red'} />
        <Pill label='policy' value={config?.current_policy || '?'} tone='accent' />
        <Pill label='load' value={(fmtNum(systemStatus?.current_rpm, 1)) + ' rpm'} />
        <Pill label='forecast src' value={systemStatus?.forecast_source || fc?.decision_source || 'none'} tone={fc?.decision_source === 'ml' ? 'accent' : 'amber'} />
        <Pill label='actuator' value={systemStatus?.actuator_status || 'unknown'} tone={systemStatus?.actuator_status === 'healthy' ? 'green' : 'amber'} />
        <Pill label='telemetry' value={(systemStatus?.telemetry_source || 'none') + ' (' + (systemStatus?.telemetry_status || 'waiting') + ')'} />
        <Pill label='history' value={hp + '/' + need + (ready ? ' ready' : ' · ETA ' + etaMin + 'm')} tone={ready ? 'green' : 'amber'} />
        <Pill label='last tick' value={fmtTime(config?.last_tick_time)} />
      </section>

      {/* control bar */}
      <section className='mb-5 card flex flex-wrap items-center gap-3'>
        <span className='text-xs uppercase tracking-wider text-slate-400'>Policy</span>
        <select value={policy} onChange={function (e: any) { setPolicy(e.target.value); }} className='bg-ink border border-slate-700 rounded-lg px-3 py-1.5 text-sm'>
          <option value='static'>static</option>
          <option value='reactive'>reactive</option>
          <option value='ml'>ML</option>
        </select>
        <button onClick={function () { api.setPolicy(policy); notify('Policy set to ' + policy); }} className='px-3 py-1.5 rounded-lg bg-accent/20 text-accent border border-accent/40 hover:bg-accent/30 text-sm'>Apply</button>
        <div className='w-px h-6 bg-slate-700/60 mx-1'></div>
        <button onClick={function () { api.start(); notify('Autoscaler started'); }} disabled={!config?.loop_paused && config?.autoscaler_running} className='px-3 py-1.5 rounded-lg bg-emerald-600/20 text-emerald-400 border border-emerald-500/40 hover:bg-emerald-600/30 text-sm disabled:opacity-40 disabled:cursor-not-allowed'>Start</button>
        <button onClick={function () { api.stop(); notify('Autoscaler paused'); }} disabled={!!config?.loop_paused} className='px-3 py-1.5 rounded-lg bg-danger/20 text-danger border border-danger/40 hover:bg-danger/30 text-sm disabled:opacity-40 disabled:cursor-not-allowed'>Stop</button>
        <div className='w-px h-6 bg-slate-700/60 mx-1'></div>
        <span className='text-xs uppercase tracking-wider text-slate-400'>Bias %</span>
        <input type='number' value={bias} onChange={function (e: any) { setBias(Number(e.target.value)); }} className='w-16 bg-ink border border-slate-700 rounded-lg px-2 py-1.5 text-sm' />
        <button onClick={function () { api.bias(bias); notify('Injected forecast bias ' + bias + '%'); }} className={'px-3 py-1.5 rounded-lg text-sm border ' + (biasPct !== 0 ? 'bg-warn/30 text-warn border-warn/50' : 'bg-warn/10 text-warn border-warn/30 hover:bg-warn/20')}>Inject bias</button>
        <span className='text-xs uppercase tracking-wider text-slate-400'>Spike x</span>
        <input type='number' value={spike} onChange={function (e: any) { setSpike(Number(e.target.value)); }} className='w-16 bg-ink border border-slate-700 rounded-lg px-2 py-1.5 text-sm' />
        <button onClick={function () { api.spike(spike, 5); notify('Injected load spike x' + spike + ' for 5 min'); }} className={'px-3 py-1.5 rounded-lg text-sm border ' + (spikeActive ? 'bg-danger/30 text-danger border-danger/50' : 'bg-danger/10 text-danger border-danger/30 hover:bg-danger/20')}>Inject spike</button>
      </section>

      {/* charts */}
      <section className='grid grid-cols-1 lg:grid-cols-2 gap-4 mb-5'>
        <div className='card'>
          <div className='flex items-center justify-between mb-2'>
            <h2 className='text-sm font-semibold text-white'>Replicas (last 30 min)</h2>
            <span className='text-[10px] uppercase tracking-wider text-slate-500'>desired / running / starting / draining</span>
          </div>
          <ResponsiveContainer width='100%' height={220}>
            <LineChart data={replicaData.length > 0 ? replicaData : replicaFallback}>
              <CartesianGrid strokeDasharray='3 3' stroke='#1e293b' />
              <XAxis dataKey='timestamp' tickFormatter={fmtTime} tick={axisTick} stroke='#334155' />
              <YAxis allowDecimals={false} tick={axisTick} stroke='#334155' width={28} />
              <Tooltip contentStyle={tooltipStyle} labelFormatter={function (v: any) { return fmtTime(v); }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line type='stepAfter' dataKey='desired' stroke='#60a5fa' strokeWidth={2} dot={false} />
              <Line type='stepAfter' dataKey='running' stroke='#34d399' strokeWidth={2} dot={false} />
              <Line type='stepAfter' dataKey='starting' stroke='#fbbf24' strokeWidth={1.5} strokeDasharray='4 3' dot={false} />
              <Line type='stepAfter' dataKey='draining' stroke='#f87171' strokeWidth={1.5} strokeDasharray='4 3' dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className='card'>
          <div className='flex items-center justify-between mb-2'>
            <h2 className='text-sm font-semibold text-white'>Load forecast (rpm)</h2>
            <span className='text-[10px] uppercase tracking-wider text-slate-500'>actual · P50 · P90 · 90% band</span>
          </div>
          {fc?.decision_source === 'fallback' && (
            <p className='text-xs text-warn mb-1'>Reactive fallback while history builds ({hp}/{need} samples).</p>
          )}
          <ResponsiveContainer width='100%' height={220}>
            <ComposedChart data={forecastData}>
              <CartesianGrid strokeDasharray='3 3' stroke='#1e293b' />
              <XAxis dataKey='timestamp' tickFormatter={fmtTime} tick={axisTick} stroke='#334155' />
              <YAxis tick={axisTick} stroke='#334155' width={32} />
              <Tooltip contentStyle={tooltipStyle} labelFormatter={function (v: any) { return fmtTime(v); }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Area dataKey='range' name='90% band' stroke='none' fill='#fbbf24' fillOpacity={0.12} connectNulls isAnimationActive={false} />
              <Line type='monotone' dataKey='p90' name='P90' stroke='#fbbf24' strokeWidth={1.5} strokeDasharray='5 3' dot={false} connectNulls isAnimationActive={false} />
              <Line type='monotone' dataKey='p50' name='P50' stroke='#60a5fa' strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
              <Line type='monotone' dataKey='actual' name='actual' stroke='#34d399' strokeWidth={2} dot={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* KPI cards */}
      <section className='grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 mb-5'>
        <Stat label='utilization' value={fmtPct(mc?.current_utilization)} kind={mc?.provenance?.utilization} sub={'target ' + fmtPct(config?.TARGET_UTILIZATION ?? config?.target_utilization)} />
        <Stat
          label='latency p50/p95'
          value={fmtNum(mc?.latency_p50_ms ?? mc?.latency_ms, 0)}
          sub={mc?.latency_p95_ms != null ? 'p95 ' + fmtNum(mc.latency_p95_ms, 0) + ' ms' : 'p95 n/a'}
          kind='measured'
        />
        <Stat label='SLA violations' value={String(mc?.sla_count ?? 0)} kind='simulated' sub={fmtNum(mc?.sla_violation_minutes, 2) + ' min'} />
        <Stat label='cost' value={fmtUsd(mc?.cost_usd)} kind='estimated' sub='per interval' />
        <Stat label='energy' value={fmtWh(mc?.energy_kwh)} kind='simulated' sub='estimated' />
        <Stat label='robust mode' value={String(rob?.active_mode || '-')} sub={rob?.drift_alarm ? 'drift alarm' : 'stable'} tone={rob?.drift_alarm ? 'text-danger' : 'text-white'} />
      </section>

      {/* decisions table */}
      <section className='card'>
        <div className='flex items-center justify-between mb-2'>
          <h2 className='text-sm font-semibold text-white'>Decisions</h2>
          <span className='text-[10px] uppercase tracking-wider text-slate-500'>last {Math.min(decisions.length, 50)}</span>
        </div>
        <div className='overflow-x-auto'>
          <table className='w-full text-sm'>
            <thead>
              <tr className='text-left text-slate-400 text-xs uppercase tracking-wider'>
                <th className='py-2 pr-3'>time</th>
                <th className='py-2 pr-3'>source</th>
                <th className='py-2 pr-3'>action</th>
                <th className='py-2 pr-3'>current → desired</th>
                <th className='py-2 pr-3'>observed</th>
                <th className='py-2'>reason</th>
              </tr>
            </thead>
            <tbody>
              {(decisions || []).slice(0, 50).map(function (d: any, i: number) {
                const action = d.action || 'no_change';
                return (
                  <tr key={i} className={'border-t border-slate-800/80 hover:bg-panel/40 ' + (i % 2 ? 'bg-panel/20' : '')}>
                    <td className='py-1.5 pr-3 text-slate-300 whitespace-nowrap'>{fmtTime(d.timestamp || d.ts)}</td>
                    <td className='py-1.5 pr-3'><DecisionBadge source={d.decision_source} reason={d.reason || ''} /></td>
                    <td className={'py-1.5 pr-3 ' + (ACTION_TONE[action] || 'text-slate-400')}>{action}</td>
                    <td className='py-1.5 pr-3 whitespace-nowrap'>
                      <span className='text-slate-300'>{d.current ?? '-'}</span>
                      <span className='text-slate-600 mx-1'>→</span>
                      <span className='text-white font-medium'>{d.desired ?? d.final_desired ?? '-'}</span>
                    </td>
                    <td className='py-1.5 pr-3 text-slate-300 whitespace-nowrap'>{fmtNum(d.observed_load, 1)} rpm</td>
                    <td className='py-1.5 text-slate-400 max-w-[420px] truncate'>{d.reason}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <footer className='mt-6 text-center text-[11px] text-slate-600'>
        All cost/energy/SLA figures are model estimates (simulated) unless labeled measured. ElasticMind student project.
      </footer>
    </div>
  );
}
