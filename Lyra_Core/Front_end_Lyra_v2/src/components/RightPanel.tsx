import { useEffect, useState } from 'react';
import { getMetrics, getStats, type Metrics, type Stats } from '../api';

const POLL_MS = 4000;

export default function RightPanel() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const [m, s] = await Promise.all([getMetrics(), getStats()]);
        if (!cancelled) {
          setMetrics(m);
          setStats(s);
        }
      } catch {
        // backend fora do ar — mantém o último valor conhecido
      }
    }
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const system = metrics
    ? [
        { label: 'CPU', value: `${metrics.cpu_pct}%`, pct: metrics.cpu_pct },
        { label: 'RAM', value: `${metrics.ram_pct}%`, pct: metrics.ram_pct },
        { label: 'GPU', value: metrics.gpu_pct != null ? `${metrics.gpu_pct}%` : '—', pct: metrics.gpu_pct ?? 0 },
      ]
    : [];

  const cascade = stats
    ? Object.entries(stats.distribuicao_pct)
    : [];

  return (
    <aside className="rp">
      <div className="rp-label">System</div>
      {system.map((m) => (
        <div key={m.label}>
          <div className="rp-row"><span>{m.label}</span><span>{m.value}</span></div>
          <div className="rp-bar"><i style={{ width: `${m.pct}%` }} /></div>
        </div>
      ))}
      <div className="rp-label">Cascade</div>
      {cascade.map(([nome, pct]) => (
        <div className="rp-row" key={nome}><span>{nome}</span><span>{pct}%</span></div>
      ))}
    </aside>
  );
}
