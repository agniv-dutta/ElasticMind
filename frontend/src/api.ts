const API_BASE = (import.meta.env && import.meta.env.VITE_API_BASE) || '/api';

async function get<T>(path: string): Promise<T> {
  const res = await fetch(API_BASE + path);
  if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
  return res.json();
}

async function post<T>(path: string, body?: any): Promise<T> {
  const res = await fetch(API_BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
  return res.json();
}

export const api = {
  health: function() { return get<any>('/health'); },
  capacity: function() { return get<any>('/capacity'); },
  forecast: function() { return get<any>('/forecast'); },
  metricsCurrent: function() { return get<any>('/metrics/current'); },
  metricsHistory: function() { return get<any>('/metrics/history'); },
  decisions: function() { return get<any>('/decisions'); },
  experiments: function() { return get<any>('/experiments'); },
  robustnessStatus: function() { return get<any>('/robustness/status'); },
  setPolicy: function(policy: string) { return post<any>('/autoscaler/policy', { policy: policy }); },
  start: function() { return post<any>('/autoscaler/start'); },
  stop: function() { return post<any>('/autoscaler/stop'); },
  bias: function(bias_percent: number) { return post<any>('/faults/bias', { bias_percent: bias_percent, simulated: true }); },
  spike: function(magnitude: number, duration_minutes: number) {
    return post<any>('/faults/spike', { magnitude: magnitude, duration_minutes: duration_minutes, simulated: true });
  },
};