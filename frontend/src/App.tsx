import { useEffect, useMemo, useState } from 'react';
import { api } from './api';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

function Badge(props: any) {
  var kind = props.kind;
  var cls = kind === 'measured' ? 'bg-emerald-700' : kind === 'simulated' ? 'bg-amber-700' : 'bg-slate-600';
  return <span className={'text-xs px-1.5 py-0.5 rounded text-white ' + cls}>{kind}</span>;
}

function DecisionBadge(props: any) {
  var r = (props.reason || '').toLowerCase();
  if (r.indexOf('safety_net') >= 0) return <span className='text-xs px-1.5 py-0.5 rounded bg-red-700 text-white'>safety net</span>;
  if (r.indexOf('fallback') >= 0 || r.indexOf('reactive') >= 0) return <span className='text-xs px-1.5 py-0.5 rounded bg-orange-700 text-white'>fallback</span>;
  return <span className='text-xs px-1.5 py-0.5 rounded bg-blue-700 text-white'>ML</span>;
}

export default function App() {
  const [health, setHealth] = useState<any>(null);
  const [config, setConfig] = useState<any>(null);
  const [cap, setCap] = useState<any>(null);
  const [fc, setFc] = useState<any>(null);
  const [mc, setMc] = useState<any>(null);
  const [decisions, setDecisions] = useState<any[]>([]);
  const [rob, setRob] = useState<any>(null);
  const [policy, setPolicy] = useState('ml_predictive');
  const [bias, setBias] = useState(0);
  const [spike, setSpike] = useState(2);

  const poll = async function() {
    try {
      const h = await api.health().catch(function(){ return null; });
      const cfg = await api.config().catch(function(){ return null; });
      const c = await api.capacity().catch(function(){ return null; });
      const f = await api.forecast().catch(function(){ return null; });
      const m = await api.metricsCurrent().catch(function(){ return null; });
      const d = await api.decisions().catch(function(){ return []; });
      const r = await api.robustnessStatus().catch(function(){ return null; });
      setHealth(h); setConfig(cfg); setCap(c); setFc(f); setMc(m); setDecisions(Array.isArray(d)?d:[]); setRob(r);
    } catch(e) {}
  };

  useEffect(function(){ poll(); var id = setInterval(poll, 5000); return function(){ clearInterval(id); }; }, []);

  const forecastData = useMemo(function(){
    var history = (fc && fc.history) ? fc.history.map(function(p:any){return {timestamp:p.timestamp, actual:p.actual};}) : [];
    var pts = (fc && fc.forecast) ? fc.forecast : [];
    var now = Date.now();
    var shifted = pts.map(function(p:any){ return {timestamp:new Date(now + Number(p.horizon_min)*60000).toISOString(), p50:p.p50, p90:p.p90}; });
    return history.concat(shifted).sort(function(a:any,b:any){return Date.parse(a.timestamp)-Date.parse(b.timestamp);});
  }, [fc]);

  const replicaData = useMemo(function(){
    var desired = cap ? (cap.desired_instances != null ? cap.desired_instances : cap.desired) : 0;
    var running = cap ? (cap.current_instances != null ? cap.current_instances : cap.running) : 0;
    var starting = cap ? (cap.pending_start != null ? cap.pending_start : 0) : 0;
    var draining = cap ? (cap.draining != null ? cap.draining : 0) : 0;
    return [{name:'replicas', desired:desired||0, running:running||0, starting:starting||0, draining:draining||0}];
  }, [cap]);

  return (
    <div className='min-h-screen bg-slate-950 text-slate-100 p-4'>
      <header className='mb-4'>
        <h1 className='text-2xl font-bold'>ElasticMind Dashboard</h1>
        <div className='text-sm text-slate-400 flex flex-wrap gap-3'>
          <span>profile: {config?.profile || '?'}</span>
          <span>TIME_SCALE: {config?.time_scale ?? '?'}</span>
          <span>ACTUATOR: {config?.actuator || '?'}</span>
          <span>model version: {config?.model_version || '?'}</span>
        </div>
      </header>
      <section className='mb-4 bg-slate-900 rounded p-3 flex flex-wrap gap-5 text-sm'>
        <span>System status</span><span>Autoscaler: {config?.autoscaler_running ? 'running' : 'stopped'}</span>
        <span>Last tick: {config?.last_tick_time || 'waiting for first tick'}</span>
        <span>Traffic source: {config?.traffic_source === 'gateway_connected' ? 'gateway connected' : 'gateway not connected'}</span>
        <span>Policy: {config?.current_policy || '?'}</span>
      </section>
      <section className='mb-4 bg-slate-900 rounded p-3 flex flex-wrap gap-2 items-center'>
        <span className='text-sm'>Policy</span>
        <select value={policy} onChange={function(e:any){setPolicy(e.target.value);}} className='bg-slate-800 rounded px-2 py-1'>
          <option value='static'>static</option>
          <option value='reactive'>reactive</option>
          <option value='ml_predictive'>ML</option>
        </select>
        <button onClick={function(){api.setPolicy(policy);}} className='px-2 py-1 bg-blue-700 rounded'>Apply</button>
        <button onClick={function(){api.start();}} className='px-2 py-1 bg-emerald-700 rounded'>Start</button>
        <button onClick={function(){api.stop();}} className='px-2 py-1 bg-rose-700 rounded'>Stop</button>
        <span className='text-sm ml-4'>Bias %</span>
        <input type='number' value={bias} onChange={function(e:any){setBias(Number(e.target.value));}} className='w-20 bg-slate-800 rounded px-2 py-1' />
        <button onClick={function(){api.bias(bias);}} className='px-2 py-1 bg-amber-700 rounded'>Inject bias</button>
        <span className='text-sm'>Spike x</span>
        <input type='number' value={spike} onChange={function(e:any){setSpike(Number(e.target.value));}} className='w-16 bg-slate-800 rounded px-2 py-1' />
        <button onClick={function(){api.spike(spike, 5);}} className='px-2 py-1 bg-orange-700 rounded'>Inject spike</button>
      </section>
      <section className='grid grid-cols-1 md:grid-cols-2 gap-4 mb-4'>
        <div className='bg-slate-900 rounded p-3'>
          <h2 className='mb-2'>Replicas: desired vs running vs starting vs draining</h2>
          <ResponsiveContainer width='100%' height={220}>
            <BarChart data={replicaData}>
              <CartesianGrid strokeDasharray='3 3' />
              <XAxis dataKey='name' />
              <YAxis />
              <Tooltip />
              <Legend />
              <Bar dataKey='desired' stackId='a' fill='#60a5fa' />
              <Bar dataKey='running' stackId='a' fill='#22c55e' />
              <Bar dataKey='starting' stackId='a' fill='#f59e0b' />
              <Bar dataKey='draining' stackId='a' fill='#f43f5e' />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className='bg-slate-900 rounded p-3'>
          <h2 className='mb-2'>Forecast P50/P90 vs actual (horizon shift applied)</h2>
          <ResponsiveContainer width='100%' height={220}>
            <AreaChart data={forecastData}>
              <CartesianGrid strokeDasharray='3 3' />
              <XAxis dataKey='timestamp' tickFormatter={function(v:any){return new Date(v).toLocaleTimeString();}} />
              <YAxis />
              <Tooltip />
              <Legend />
              <Area type='monotone' dataKey='p90' stroke='#f59e0b' fill='#f59e0b33' />
              <Area type='monotone' dataKey='p50' stroke='#60a5fa' fill='#60a5fa33' />
              <Line type='monotone' dataKey='actual' stroke='#22c55e' />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </section>
      <section className='grid grid-cols-2 md:grid-cols-6 gap-3 mb-4'>
        <div className='bg-slate-900 rounded p-2'>Util <Badge kind='simulated' /> {(mc && (mc.current_utilization!=null?mc.current_utilization:'-'))}</div>
        <div className='bg-slate-900 rounded p-2'>Latency p50/p95 <Badge kind='measured' /> {(mc && (mc.latency_p50_ms!=null?mc.latency_p50_ms:mc.latency_ms)) || '-'} / {(mc && mc.latency_p95_ms) || '-'}</div>
        <div className='bg-slate-900 rounded p-2'>SLA <Badge kind='simulated' /> {(mc && (mc.sla_count!=null?mc.sla_count:mc.sla_violations)) || 0}</div>
        <div className='bg-slate-900 rounded p-2'>Cost <Badge kind='estimated' /> {(mc && mc.cost_usd) || '-'}</div>
        <div className='bg-slate-900 rounded p-2'>Energy <Badge kind='simulated' /> {(mc && mc.energy_kwh) || '-'}</div>
        <div className='bg-slate-900 rounded p-2'>Robust <span className='text-xs'>{(rob && rob.active_mode) || '-'}</span></div>
      </section>
      <section className='bg-slate-900 rounded p-3'>
        <h2 className='mb-2'>Decisions (source badge)</h2>
        <div className='overflow-x-auto'>
          <table className='w-full text-sm'>
            <thead>
              <tr className='text-left text-slate-400'>
                <th className='py-1'>time</th><th>source</th><th>action</th><th>desired/current</th><th>reason</th>
              </tr>
            </thead>
            <tbody>
              {(decisions||[]).slice(0,50).map(function(d:any,i:number){
                return <tr key={i} className='border-t border-slate-800'>
                  <td className='py-1'>{d.timestamp||d.ts||'-'}</td>
                  <td><DecisionBadge reason={d.reason||''} /></td>
                  <td>{d.action||'-'}</td>
                  <td>{d.desired}/{d.current}</td>
                  <td className='truncate max-w-[500px]'>{d.reason}</td>
                </tr>;
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
