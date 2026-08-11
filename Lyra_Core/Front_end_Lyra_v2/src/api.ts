const API_BASE = 'http://127.0.0.1:8000';

export interface HistMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp?: string;
}

export interface Sessao {
  sessao_id: string;
  titulo: string;
  criada: string;
  ativa: boolean;
  somente_leitura?: boolean;
}

export interface Metrics {
  latencia_ms: number | null;
  cpu_pct: number;
  ram_pct: number;
  gpu_pct: number | null;
  vram_pct: number | null;
}

export interface StatsTier {
  usos: number;
  falhas: number;
  latencia_media_ms: number | null;
  taxa_sucesso: number | null;
}

export interface Stats {
  total_chats: number;
  iniciado_em: string | null;
  tiers: Record<string, StatsTier>;
  distribuicao_pct: Record<string, number>;
}

export async function getHistorico(sessao?: string): Promise<HistMessage[]> {
  const url = sessao ? `${API_BASE}/historico?sessao=${encodeURIComponent(sessao)}` : `${API_BASE}/historico`;
  const res = await fetch(url);
  const data = await res.json();
  return data.mensagens ?? [];
}

export async function limparHistorico(): Promise<void> {
  await fetch(`${API_BASE}/historico`, { method: 'DELETE' });
}

export async function getSessoes(): Promise<{ sessoes: Sessao[]; ativa: string }> {
  const res = await fetch(`${API_BASE}/sessoes`);
  return res.json();
}

export async function novaSessao(): Promise<void> {
  await fetch(`${API_BASE}/sessoes`, { method: 'POST' });
}

export async function ativarSessao(sessaoId: string): Promise<void> {
  await fetch(`${API_BASE}/sessoes/ativar`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessao_id: sessaoId }),
  });
}

export async function renomearSessao(sessaoId: string, titulo: string): Promise<void> {
  await fetch(`${API_BASE}/sessoes/${encodeURIComponent(sessaoId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ titulo }),
  });
}

export async function deletarSessao(sessaoId: string): Promise<void> {
  await fetch(`${API_BASE}/sessoes/${encodeURIComponent(sessaoId)}`, { method: 'DELETE' });
}

export interface ResultadoBusca {
  id: string;
  titulo: string;
  categoria: string;
  trecho: string;
  score_final: number;
}

export async function buscar(q: string): Promise<ResultadoBusca[]> {
  const res = await fetch(`${API_BASE}/buscar?q=${encodeURIComponent(q)}&top_k=8`);
  const data = await res.json();
  return data.resultados ?? [];
}

export async function uploadArquivo(file: File): Promise<{ ok: boolean; path: string; nome: string }> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${API_BASE}/upload`, { method: 'POST', body: form });
  return res.json();
}

export async function getInfo(): Promise<{ servico: string; ativo: boolean; versao: string }> {
  const res = await fetch(`${API_BASE}/`);
  return res.json();
}

export interface Integracao { online: boolean; status: string }

export async function getIntegracoes(): Promise<Record<string, Integracao>> {
  const res = await fetch(`${API_BASE}/integracoes`);
  return res.json();
}

export async function exportarConversa(): Promise<{ markdown: string; total_msgs: number }> {
  const res = await fetch(`${API_BASE}/exportar`);
  return res.json();
}

export async function setTtsMudo(mudo: boolean): Promise<void> {
  await fetch(`${API_BASE}/tts/mudo`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mudo }),
  });
}

export async function getMetrics(): Promise<Metrics> {
  const res = await fetch(`${API_BASE}/metrics`);
  return res.json();
}

export async function getStats(): Promise<Stats> {
  const res = await fetch(`${API_BASE}/stats`);
  return res.json();
}

export interface ChatCallbacks {
  onTier?: (tier: string) => void;
  onText: (chunk: string) => void;
  onDone: () => void;
  onError?: (err: unknown) => void;
}

// Consome o SSE de POST /chat: cada linha "data: {...}\n\n" carrega
// {tier} (uma vez, ao trocar de andar da cascata) ou {text} (chunk de resposta).
// Termina em "data: [DONE]".
export async function enviarChat(
  texto: string,
  modelo: string,
  cb: ChatCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  try {
    const res = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ texto, modelo }),
      signal,
    });
    if (!res.body) throw new Error('resposta sem corpo');

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const linhas = buffer.split('\n\n');
      buffer = linhas.pop() ?? '';

      for (const linha of linhas) {
        if (!linha.startsWith('data: ')) continue;
        const payload = linha.slice(6);
        if (payload === '[DONE]') {
          cb.onDone();
          return;
        }
        const obj = JSON.parse(payload);
        if (obj.tier) cb.onTier?.(obj.tier);
        if (obj.text) cb.onText(obj.text);
      }
    }
    cb.onDone();
  } catch (err) {
    cb.onError?.(err);
  }
}
