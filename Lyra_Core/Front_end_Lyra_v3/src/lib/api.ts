// api.ts — cliente HTTP mínimo pro backend (cerebro_maestro, :8000).
//
// Base vazia = same-origin (produção: app servido em /ui pelo próprio
// backend, exatamente como o Front_end_Lyra_v2/dist hoje). Em dev
// (`npm run dev`, :5173) isso só funciona se o backend rodar com
// allow_credentials=True pra essa origem — hoje NÃO roda (CORS restrito de
// propósito, ver comentário em cerebro_maestro.py sobre drive-by cookie
// read). Rodar `npm run build` e servir via /ui é o caminho de teste real
// até essa decisão de CORS ser revisitada.
const BASE = '';

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
	const resp = await fetch(`${BASE}${path}`, {
		credentials: 'include',
		headers: { 'Content-Type': 'application/json' },
		...options
	});
	const data = await resp.json().catch(() => null);
	if (!resp.ok) {
		const detail = data?.detail || `Erro ${resp.status}`;
		throw new Error(detail);
	}
	return data as T;
}

export interface AuthStatus {
	setup_necessario: boolean;
}

export interface AuthResult {
	ok: boolean;
	username: string;
}

export interface Sessao {
	sessao_id: string;
	titulo: string;
	criada: string;
	ativa: boolean;
	favorita?: boolean;
	somente_leitura?: boolean;
}

export interface Mensagem {
	role: 'user' | 'assistant';
	content: string;
	timestamp?: string;
}

export const api = {
	authStatus: () => request<AuthStatus>('/auth/status'),
	authSetup: (username: string, senha: string) =>
		request<AuthResult>('/auth/setup', { method: 'POST', body: JSON.stringify({ username, senha }) }),
	authLogin: (username: string, senha: string) =>
		request<AuthResult>('/auth/login', { method: 'POST', body: JSON.stringify({ username, senha }) }),
	authLogout: () => request<{ ok: boolean }>('/auth/logout', { method: 'POST' }),

	sessoesListar: () => request<{ sessoes: Sessao[]; ativa: string | null }>('/sessoes'),
	sessaoNova: () => request<{ sessao_id: string }>('/sessoes', { method: 'POST' }),
	sessaoAtivar: (sessao_id: string) =>
		request('/sessoes/ativar', { method: 'POST', body: JSON.stringify({ sessao_id }) }),
	sessaoFavoritar: (sessao_id: string, favorita: boolean) =>
		request(`/sessoes/${sessao_id}/favoritar`, { method: 'POST', body: JSON.stringify({ favorita }) }),
	sessaoRenomear: (sessao_id: string, titulo: string) =>
		request(`/sessoes/${sessao_id}`, { method: 'PATCH', body: JSON.stringify({ titulo }) }),
	sessaoDeletar: (sessao_id: string) => request(`/sessoes/${sessao_id}`, { method: 'DELETE' }),
	historicoGet: () => request<{ mensagens: Mensagem[] }>('/historico'),
	historicoLimpar: () => request<{ ok: boolean }>('/historico', { method: 'DELETE' }),

	promptsListar: () =>
		request<{ total: number; prompts: { id: string; titulo: string; comando: string; conteudo: string }[] }>(
			'/prompts'
		),
	promptCriar: (titulo: string, comando: string, conteudo: string) =>
		request<{ ok: boolean; id: string }>('/prompts', {
			method: 'POST',
			body: JSON.stringify({ titulo, comando, conteudo })
		}),
	promptEditar: (id: string, titulo: string, comando: string, conteudo: string) =>
		request(`/prompts/${id}`, { method: 'PATCH', body: JSON.stringify({ titulo, comando, conteudo }) }),
	promptDeletar: (id: string) => request(`/prompts/${id}`, { method: 'DELETE' }),

	info: () => request<{ servico: string; ativo: boolean; versao: string }>('/'),
	integracoes: () =>
		request<Record<string, { online: boolean; status: string }>>('/integracoes'),
	buscar: (q: string) =>
		request<{ resultados: { id: string; titulo: string; categoria: string; trecho: string }[] }>(
			`/buscar?q=${encodeURIComponent(q)}&top_k=8`
		),

	health: () => request<Record<string, unknown>>('/health'),
	tools: () =>
		request<{ total: number; ferramentas: { nome: string; descricao: string; habilitada: boolean }[] }>(
			'/tools'
		),
	toolToggle: (nome: string) =>
		request<{ ok: boolean; nome: string; habilitada: boolean }>(`/tools/${nome}/toggle`, {
			method: 'POST'
		}),
	logs: (fonte: 'log' | 'err' = 'log', linhas = 200) =>
		request<{ fonte: string; linhas: string[] }>(`/logs?fonte=${fonte}&linhas=${linhas}`),
	metrics: () => request<Record<string, unknown>>('/metrics'),
	stats: () => request<Record<string, unknown>>('/stats'),

	ttsMudo: (mudo: boolean) =>
		request<{ ok: boolean; tts_mudo: boolean }>('/tts/mudo', {
			method: 'POST',
			body: JSON.stringify({ mudo })
		}),
	exportarConversa: () => request<{ markdown: string }>('/exportar'),

	async upload(file: File): Promise<{ path: string; nome: string }> {
		const form = new FormData();
		form.append('file', file);
		const resp = await fetch(`${BASE}/upload`, { method: 'POST', credentials: 'include', body: form });
		const data = await resp.json();
		if (!resp.ok) throw new Error(data?.detail || `Erro ${resp.status}`);
		return data;
	}
};

/**
 * Faz streaming de POST /chat (Server-Sent Events sobre um POST — não dá pra
 * usar EventSource nativo, que só suporta GET). Lê o corpo como stream bruto,
 * separa por linhas `data: {...}` e produz cada chunk conforme chega.
 */
export async function* streamChat(
	texto: string,
	modelo = 'auto',
	signal?: AbortSignal
): AsyncGenerator<{ tier?: string; text?: string }> {
	const resp = await fetch(`${BASE}/chat`, {
		method: 'POST',
		credentials: 'include',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ texto, modelo }),
		signal
	});
	if (!resp.body) return;

	const reader = resp.body.getReader();
	const decoder = new TextDecoder();
	let buffer = '';

	while (true) {
		const { done, value } = await reader.read();
		if (done) break;
		buffer += decoder.decode(value, { stream: true });

		const linhas = buffer.split('\n\n');
		buffer = linhas.pop() ?? '';
		for (const linha of linhas) {
			const conteudo = linha.replace(/^data: /, '').trim();
			if (!conteudo || conteudo === '[DONE]') continue;
			try {
				yield JSON.parse(conteudo);
			} catch {
				// chunk incompleto/malformado — ignora, o próximo read() completa
			}
		}
	}
}
