// shell.ts — contrato fino entre o frontend Svelte e a casca nativa que o
// hospeda (Theia/Electron OU Tauri/Rust). Ver LYRA_NUCLEO.md §5.6:
// "o Svelte só chama a interface, nunca a implementação" — sem isso, cada
// componente teria que saber em qual casca está rodando.
//
// Hoje só existe a implementação `browser` (fallback quando não há casca
// nenhuma — ex: `npm run dev` puro, ou embutido no /ui do backend sem
// Electron/Tauri por perto). As implementações reais (Theia via IPC do
// Electron, Tauri via `invoke`) entram na Fase 5, quando essas cascas
// existirem de verdade — este arquivo é o contrato que as duas vão cumprir.

export interface LyraShell {
	/** Nome da casca atual — só pra log/debug, componentes não devem ramificar nisso. */
	readonly kind: 'browser' | 'theia' | 'tauri';

	/** Lê um segredo (API key etc.) guardado fora do webview/localStorage.
	 * Casca browser não tem onde guardar com segurança — sempre retorna null. */
	getSecret(id: string): Promise<string | null>;

	/** Persiste uma configuração no lado nativo, não no frontend. */
	setSetting(key: string, value: unknown): Promise<void>;

	/** Garante que o backend (cerebro_maestro) está de pé; casca browser
	 * assume que alguém já subiu o processo por fora. */
	startBackend(): Promise<void>;

	/** Abre a IDE da Lyra (Theia) — botão da casca Tauri (decisão 2026-08-11,
	 * ver LYRA_NUCLEO.md §5.6). Se já estiver aberta, foca a janela.
	 * Casca browser não tem como abrir outro processo — lança erro. */
	openIDE(): Promise<void>;
}

class BrowserShell implements LyraShell {
	readonly kind = 'browser' as const;

	async getSecret(): Promise<string | null> {
		return null;
	}

	async setSetting(): Promise<void> {
		// sem lado nativo — no-op deliberado, não há onde persistir com segurança
	}

	async startBackend(): Promise<void> {
		// sem lado nativo — assume que o backend já está rodando (dev/`/ui`)
	}

	async openIDE(): Promise<void> {
		throw new Error('openIDE() só existe nas cascas nativas (Theia/Tauri).');
	}
}

/**
 * Casca Theia — detectada via `?shell=theia` na URL (posto pelo
 * `lyra-chat-widget.ts` do Lyra_IDE, que carrega este app num iframe).
 * Sem bridge IPC real ainda: o Theia hoje não tem secret store nem gerência
 * de settings própria pra esse painel — implementar isso é trabalho futuro
 * do lado do widget Theia, não deste arquivo. `openIDE()` é no-op porque
 * rodando DENTRO do Theia não faz sentido "abrir a IDE" (o botão é da
 * casca Tauri, ver `TauriShell` quando existir).
 */
class TheiaShell implements LyraShell {
	readonly kind = 'theia' as const;

	async getSecret(): Promise<string | null> {
		console.warn('TheiaShell.getSecret: bridge IPC com o Theia ainda não existe.');
		return null;
	}

	async setSetting(): Promise<void> {
		console.warn('TheiaShell.setSetting: bridge IPC com o Theia ainda não existe.');
	}

	async startBackend(): Promise<void> {
		// Theia já é responsável por subir o backend antes de montar o widget.
	}

	async openIDE(): Promise<void> {
		// já está dentro da IDE — no-op deliberado
	}
}

/**
 * Casca Tauri — detectada por `window.__TAURI_INTERNALS__`, injetado
 * automaticamente pelo runtime Tauri em toda janela (não precisa de query
 * param como o Theia). Chama os comandos Rust via `invoke` — implementação
 * do lado Rust em `src-tauri/src/main.rs` (ver seção 5 do
 * LYRA_NUCLEO.md §5.8 pra status: os comandos
 * Rust existem como código-fonte mas NÃO foram compilados/testados —
 * toolchain Rust não instalado nesta máquina).
 */
class TauriShell implements LyraShell {
	readonly kind = 'tauri' as const;

	async getSecret(id: string): Promise<string | null> {
		const { invoke } = await import('@tauri-apps/api/core');
		return invoke<string | null>('get_secret', { id });
	}

	async setSetting(key: string, value: unknown): Promise<void> {
		const { invoke } = await import('@tauri-apps/api/core');
		await invoke('set_setting', { key, value });
	}

	async startBackend(): Promise<void> {
		const { invoke } = await import('@tauri-apps/api/core');
		await invoke('start_backend');
	}

	async openIDE(): Promise<void> {
		const { invoke } = await import('@tauri-apps/api/core');
		await invoke('open_ide');
	}
}

/** Detecta a casca atual e devolve a implementação certa.
 * `browser` é o fallback (dev puro, ou `/ui` aberto direto sem casca por
 * perto). */
function detectarCasca(): LyraShell {
	if (typeof window !== 'undefined') {
		if ('__TAURI_INTERNALS__' in window) return new TauriShell();
		const params = new URLSearchParams(window.location.search);
		if (params.get('shell') === 'theia') return new TheiaShell();
	}
	return new BrowserShell();
}

export const shell: LyraShell = detectarCasca();
