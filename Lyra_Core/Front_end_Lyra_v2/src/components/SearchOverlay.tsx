import { useEffect, useState } from 'react';
import { buscar, type ResultadoBusca } from '../api';

interface SearchOverlayProps {
  onClose: () => void;
}

export default function SearchOverlay({ onClose }: SearchOverlayProps) {
  const [q, setQ] = useState('');
  const [resultados, setResultados] = useState<ResultadoBusca[]>([]);
  const [buscando, setBuscando] = useState(false);

  useEffect(() => {
    if (!q.trim()) {
      setResultados([]);
      return;
    }
    const id = setTimeout(async () => {
      setBuscando(true);
      try {
        setResultados(await buscar(q.trim()));
      } finally {
        setBuscando(false);
      }
    }, 350);
    return () => clearTimeout(id);
  }, [q]);

  return (
    <div className="search-overlay" onClick={onClose}>
      <div className="search-panel" onClick={(e) => e.stopPropagation()}>
        <input
          autoFocus
          placeholder="Search memory…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Escape') onClose(); }}
        />
        {buscando && <div className="search-empty">Searching…</div>}
        {!buscando && q.trim() && resultados.length === 0 && (
          <div className="search-empty">No results.</div>
        )}
        {resultados.map((r) => (
          <div className="search-result" key={r.id}>
            <div className="search-result-title">{r.titulo || r.categoria || 'untitled'}</div>
            <div className="search-result-trecho">{r.trecho}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
