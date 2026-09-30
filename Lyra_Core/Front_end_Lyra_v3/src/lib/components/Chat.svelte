<script lang="ts">
	import { api, streamChat, type Sessao, type Mensagem } from '$lib/api';
	import SystemPanel from './SystemPanel.svelte';
	import GraphPanel from './GraphPanel.svelte';
	import ModelHubPanel from './ModelHubPanel.svelte';
	import MessageContent from './MessageContent.svelte';
	import Sidebar from './Sidebar.svelte';
	import SearchOverlay from './SearchOverlay.svelte';
	import SettingsModal from './SettingsModal.svelte';
	import Orb from './Orb.svelte';
	import PromptLibraryPanel from './PromptLibraryPanel.svelte';
	import { shell } from '$lib/shell';
	import { settings } from '$lib/settings.svelte';
	import { VoiceLiveSession } from '$lib/voiceLive';
	import { onDestroy } from 'svelte';

	let sessoes = $state<Sessao[]>([]);
	let mensagens = $state<Mensagem[]>([]);
	let texto = $state('');

	const SUGESTOES = [
		'O que você lembra da nossa última conversa?',
		'Qual o status do sistema agora?',
		'Me dá um resumo do que discutimos essa semana.'
	];
	let enviando = $state(false);
	let tierAtual = $state('');
	let sidebarColapsada = $state(false);

	let painelSistemaAberto = $state(false);
	let painelGrafoAberto = $state(false);
	let painelModelosAberto = $state(false);
	let painelPromptsAberto = $state(false);
	let buscaAberta = $state(false);
	let configAberta = $state(false);

	let inputArquivo: HTMLInputElement | undefined = $state();
	let textareaEl: HTMLTextAreaElement | undefined = $state();
	let abortController: AbortController | null = null;

	let vozLiveAtiva = $state(false);
	let vozLiveErro = $state('');
	let vozLiveSessao: VoiceLiveSession | null = null;

	async function alternarVozLive() {
		if (vozLiveAtiva) {
			vozLiveSessao?.stop();
			return;
		}
		vozLiveErro = '';
		vozLiveSessao = new VoiceLiveSession();
		vozLiveSessao.onStatusChange = (ativo) => (vozLiveAtiva = ativo);
		vozLiveSessao.onText = (texto) => {
			const ultima = mensagens[mensagens.length - 1];
			if (ultima?.role === 'assistant' && vozLiveAtiva) {
				mensagens = [...mensagens.slice(0, -1), { ...ultima, content: ultima.content + texto }];
			} else {
				mensagens = [...mensagens, { role: 'assistant', content: texto }];
			}
		};
		vozLiveSessao.onDone = () => {
			mensagens = [...mensagens, { role: 'assistant', content: '' }];
		};
		vozLiveSessao.onError = (msg) => {
			vozLiveErro = msg;
			vozLiveAtiva = false;
		};
		try {
			await vozLiveSessao.start();
		} catch (e) {
			vozLiveErro = e instanceof Error ? e.message : 'Falha ao iniciar voz live.';
		}
	}

	onDestroy(() => vozLiveSessao?.stop());

	async function carregarSessoes() {
		try {
			const r = await api.sessoesListar();
			sessoes = r.sessoes;
		} catch {
			// backend sem SurrealDB/Qdrant no ar ainda — sidebar fica vazia, chat segue funcionando
		}
	}

	async function carregarHistorico() {
		try {
			const r = await api.historicoGet();
			mensagens = r.mensagens;
		} catch {
			mensagens = [];
		}
	}

	carregarSessoes();
	carregarHistorico();

	async function novaSessao() {
		await api.sessaoNova();
		mensagens = [];
		await carregarSessoes();
	}

	async function trocarSessao(sessao_id: string) {
		await api.sessaoAtivar(sessao_id);
		await carregarSessoes();
		await carregarHistorico();
	}

	function formatarHora(ts?: string): string {
		if (!ts) return '';
		const d = new Date(ts);
		if (Number.isNaN(d.getTime())) return '';
		return d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
	}

	async function exportar() {
		const r = await api.exportarConversa();
		const blob = new Blob([r.markdown], { type: 'text/markdown' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `conversa-lyra-${Date.now()}.md`;
		a.click();
		URL.revokeObjectURL(url);
	}

	// Atalhos globais (paridade v2): Ctrl+K busca memória, Ctrl+Shift+O nova
	// conversa, Esc fecha o painel/modal aberto (o mais recente tem prioridade).
	function atalhosGlobais(e: KeyboardEvent) {
		if (e.ctrlKey && !e.shiftKey && e.key.toLowerCase() === 'k') {
			e.preventDefault();
			buscaAberta = true;
		} else if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'o') {
			e.preventDefault();
			novaSessao();
		} else if (e.key === 'Escape') {
			if (buscaAberta) buscaAberta = false;
			else if (configAberta) configAberta = false;
			else if (painelSistemaAberto) painelSistemaAberto = false;
			else if (painelGrafoAberto) painelGrafoAberto = false;
			else if (painelModelosAberto) painelModelosAberto = false;
		}
	}

	// Botão "abrir IDE" (decisão 2026-08-11, LYRA_NUCLEO.md §5.6)
	// só faz sentido na casca Tauri — some das outras cascas de propósito.
	async function abrirIDE() {
		try {
			await shell.openIDE();
		} catch (e) {
			console.warn('openIDE indisponível nesta casca:', e);
		}
	}

	async function anexar(e: Event) {
		const arquivo = (e.target as HTMLInputElement).files?.[0];
		if (!arquivo) return;
		const { path } = await api.upload(arquivo);
		texto = texto ? `${texto}\n${path}` : path;
		if (inputArquivo) inputArquivo.value = '';
	}

	function autoCrescer() {
		if (!textareaEl) return;
		textareaEl.style.height = 'auto';
		textareaEl.style.height = `${Math.min(textareaEl.scrollHeight, 180)}px`;
	}

	async function streamResposta(pergunta: string) {
		enviando = true;
		tierAtual = '';
		abortController = new AbortController();

		try {
			for await (const chunk of streamChat(pergunta, settings.modelo, abortController.signal)) {
				if (chunk.tier) tierAtual = chunk.tier;
				if (chunk.text) {
					const ultima = mensagens[mensagens.length - 1];
					mensagens = [...mensagens.slice(0, -1), { ...ultima, content: ultima.content + chunk.text }];
				}
			}
			carregarSessoes(); // título da sessão pode ter sido gerado agora
		} catch (e) {
			if ((e as Error)?.name !== 'AbortError') {
				const ultima = mensagens[mensagens.length - 1];
				mensagens = [
					...mensagens.slice(0, -1),
					{ ...ultima, content: ultima.content + '\n\n_(erro de conexão)_' }
				];
			}
		} finally {
			enviando = false;
		}
	}

	function enviar() {
		const pergunta = texto.trim();
		if (!pergunta || enviando) return;
		texto = '';
		if (textareaEl) textareaEl.style.height = 'auto';
		mensagens = [...mensagens, { role: 'user', content: pergunta }, { role: 'assistant', content: '' }];
		streamResposta(pergunta);
	}

	function retentar() {
		if (enviando) return;
		const idx = mensagens.map((m) => m.role).lastIndexOf('user');
		if (idx === -1) return;
		const pergunta = mensagens[idx].content;
		mensagens = [...mensagens.slice(0, idx + 1), { role: 'assistant', content: '' }];
		streamResposta(pergunta);
	}

	function parar() {
		abortController?.abort();
		enviando = false;
	}

	let copiado = $state<number | null>(null);
	function copiar(texto: string, i: number) {
		navigator.clipboard.writeText(texto);
		copiado = i;
		setTimeout(() => (copiado = null), 1500);
	}

	const ultimoAssistantIdx = $derived(
		(() => {
			for (let i = mensagens.length - 1; i >= 0; i--) if (mensagens[i].role === 'assistant') return i;
			return -1;
		})()
	);
</script>

<svelte:window onkeydown={atalhosGlobais} />

<div class="layout">
	<Sidebar
		bind:colapsada={sidebarColapsada}
		{sessoes}
		onSelect={trocarSessao}
		onNovaSessao={novaSessao}
		onAtualizar={carregarSessoes}
		onAbrirBusca={() => (buscaAberta = true)}
		onAbrirConfig={() => (configAberta = true)}
	/>

	<section class="chat">
		<div class="toolbar">
			<select class="seletor-modelo" bind:value={settings.modelo} onchange={() => settings.setModelo(settings.modelo)}>
				<option value="auto">Auto</option>
				<option value="groq">Groq</option>
				<option value="gemini">Gemini</option>
				<option value="claude">Claude</option>
				<option value="local">Local</option>
			</select>
			<button
				class="icone"
				onclick={async () => {
					settings.setTtsMudo(!settings.ttsMudo);
					await api.ttsMudo(settings.ttsMudo);
				}}
				title={settings.ttsMudo ? 'Ativar voz' : 'Mutar voz'}
			>
				{settings.ttsMudo ? 'Voz: mudo' : 'Voz: ativa'}
			</button>
			<button
				class="icone"
				class:ativa={vozLiveAtiva}
				onclick={alternarVozLive}
				title="Conversa por voz em tempo real (Gemini Live)"
			>
				{vozLiveAtiva ? 'Voz live: ON' : 'Voz live'}
			</button>
			<button class="icone" onclick={exportar} title="Exportar conversa">Exportar</button>
			<button class="icone" onclick={() => (painelSistemaAberto = true)} title="Monitor de sistema">
				Sistema
			</button>
			<button class="icone" onclick={() => (painelGrafoAberto = true)} title="Grafo de memória">
				Grafo
			</button>
			<button class="icone" onclick={() => (painelModelosAberto = true)} title="Modelos Ollama">
				Modelos
			</button>
			<button class="icone" onclick={() => (painelPromptsAberto = true)} title="Prompts salvos">
				Prompts
			</button>
			{#if shell.kind === 'tauri'}
				<button class="icone" onclick={abrirIDE} title="Abrir a IDE da Lyra (Theia)">
					Abrir IDE
				</button>
			{/if}
		</div>

		{#if painelSistemaAberto}
			<SystemPanel fechar={() => (painelSistemaAberto = false)} />
		{/if}

		{#if painelGrafoAberto}
			<GraphPanel fechar={() => (painelGrafoAberto = false)} />
		{/if}

		{#if painelModelosAberto}
			<ModelHubPanel fechar={() => (painelModelosAberto = false)} />
		{/if}

		{#if painelPromptsAberto}
			<PromptLibraryPanel
				fechar={() => (painelPromptsAberto = false)}
				onInserir={(conteudo) => {
					texto = texto ? `${texto}\n${conteudo}` : conteudo;
					textareaEl?.focus();
					autoCrescer();
				}}
			/>
		{/if}

		{#if buscaAberta}
			<SearchOverlay fechar={() => (buscaAberta = false)} />
		{/if}

		{#if configAberta}
			<SettingsModal fechar={() => (configAberta = false)} />
		{/if}

		{#if vozLiveErro}
			<p class="voz-erro">{vozLiveErro}</p>
		{/if}

		{#if mensagens.length === 0}
			<div class="foco">
				<Orb size={180} variant="centerpiece" />
				<p class="foco-hint">Pronta quando você estiver.</p>
				<div class="sugestoes">
					{#each SUGESTOES as s}
						<button
							class="chip"
							onclick={() => {
								texto = s;
								enviar();
							}}
						>
							{s}
						</button>
					{/each}
				</div>
			</div>
		{:else}
		<div class="mensagens">
			{#each mensagens as m, i}
				<div class="msg {m.role}">
					{#if m.role === 'assistant'}
						<MessageContent content={m.content} />
					{:else}
						{m.content}
					{/if}
					{#if m.content}
						<div class="msg-acoes">
							<button class="mini-acao" onclick={() => copiar(m.content, i)}>
								{copiado === i ? 'Copiado' : 'Copiar'}
							</button>
							{#if m.role === 'assistant' && i === ultimoAssistantIdx && !enviando}
								<button class="mini-acao" onclick={retentar}>↻ Tentar de novo</button>
							{/if}
							{#if m.timestamp}
								<span class="msg-hora">{formatarHora(m.timestamp)}</span>
							{/if}
						</div>
					{/if}
				</div>
			{/each}
			{#if tierAtual && enviando}
				<div class="tier dim">via {tierAtual}</div>
			{/if}
		</div>
		{/if}

		<form
			class="input-bar"
			onsubmit={(e) => {
				e.preventDefault();
				enviar();
			}}
		>
			<input type="file" bind:this={inputArquivo} onchange={anexar} hidden />
			<button type="button" class="icone" onclick={() => inputArquivo?.click()} title="Anexar arquivo">
				Anexar
			</button>
			<textarea
				bind:this={textareaEl}
				bind:value={texto}
				rows="1"
				placeholder="Fale com a Lyra... (Shift+Enter pra nova linha)"
				disabled={enviando}
				oninput={autoCrescer}
				onkeydown={(e) => {
					if (e.key === 'Enter' && !e.shiftKey) {
						e.preventDefault();
						enviar();
					}
				}}
			></textarea>
			{#if enviando}
				<button type="button" class="parar" onclick={parar}>■</button>
			{:else}
				<button type="submit" disabled={!texto.trim()}>Enviar</button>
			{/if}
		</form>
	</section>
</div>

<style>
	.layout {
		display: flex;
		height: 100vh;
	}

	.chat {
		display: flex;
		flex-direction: column;
		height: 100vh;
		flex: 1;
		min-width: 0;
	}

	.foco {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 22px;
		padding: 24px;
	}

	.foco :global(canvas) {
		filter: drop-shadow(0 0 28px var(--accent-dim));
	}

	.foco-hint {
		color: var(--text-dim);
		font-size: 0.88rem;
		letter-spacing: 0.01em;
		margin: 0;
	}

	.sugestoes {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		justify-content: center;
		max-width: 460px;
	}

	.chip {
		background: transparent;
		border: 1px solid var(--border);
		color: var(--text-dim);
		border-radius: 999px;
		padding: 7px 15px;
		font-size: 0.78rem;
		cursor: pointer;
		transition: color 0.15s var(--ease), border-color 0.15s var(--ease);
	}

	.chip:hover {
		color: var(--accent);
		border-color: var(--accent);
	}

	.toolbar {
		display: flex;
		justify-content: flex-end;
		align-items: center;
		gap: 6px;
		padding: 10px 20px;
		border-bottom: 1px solid var(--border);
	}

	.seletor-modelo {
		appearance: none;
		background: transparent
			url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%238f8f99' stroke-width='1.3' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E")
			no-repeat right 10px center;
		border: 1px solid var(--border);
		color: var(--text-dim);
		border-radius: var(--radius);
		padding: 6px 26px 6px 10px;
		font-size: 0.8rem;
		height: 30px;
		margin-right: auto;
		cursor: pointer;
		transition: border-color 0.15s var(--ease);
	}

	.seletor-modelo:hover,
	.seletor-modelo:focus {
		border-color: var(--accent);
		outline: none;
	}

	.icone {
		background: transparent;
		border: 1px solid var(--border);
		color: var(--text-dim);
		border-radius: var(--radius);
		padding: 6px 10px;
		font-size: 0.8rem;
		cursor: pointer;
		transition: color 0.15s var(--ease), border-color 0.15s var(--ease);
	}

	.toolbar .icone,
	.toolbar .seletor-modelo {
		height: 30px;
	}

	.icone:hover {
		color: var(--text);
		border-color: var(--accent);
	}

	.icone.ativa {
		color: var(--accent);
		border-color: var(--accent);
	}

	.voz-erro {
		color: var(--danger);
		font-size: 0.8rem;
		padding: 6px 24px 0;
		margin: 0;
	}

	.mensagens {
		flex: 1;
		overflow-y: auto;
		padding: 24px;
		display: flex;
		flex-direction: column;
		gap: 14px;
	}

	.msg {
		max-width: 70ch;
		white-space: pre-wrap;
		padding: 10px 14px;
		border-radius: var(--radius);
		font-size: var(--chat-font-size, 0.92rem);
	}

	.msg.user {
		align-self: flex-end;
		background: var(--surface-2);
	}

	.msg.assistant {
		align-self: flex-start;
		background: var(--surface);
		border: 1px solid var(--border);
	}

	.msg-acoes {
		display: flex;
		align-items: center;
		gap: 12px;
		margin-top: 6px;
		opacity: 0;
		transition: opacity 0.15s var(--ease);
	}

	.msg:hover .msg-acoes,
	.msg:focus-within .msg-acoes {
		opacity: 1;
	}

	.mini-acao {
		background: transparent;
		border: none;
		color: var(--text-dim);
		font-size: 0.72rem;
		cursor: pointer;
		padding: 0;
		transition: color 0.15s var(--ease);
	}

	.mini-acao:hover {
		color: var(--accent);
	}

	.msg-hora {
		font-size: 0.7rem;
		color: var(--text-dim);
		margin-left: auto;
	}

	.tier {
		font-size: 0.75rem;
		align-self: flex-start;
	}

	.dim {
		color: var(--text-dim);
	}

	.input-bar {
		display: flex;
		align-items: flex-end;
		gap: 10px;
		padding: 16px 24px;
		border-top: 1px solid var(--border);
	}

	.input-bar textarea {
		flex: 1;
		resize: none;
		min-height: 42px;
		max-height: 180px;
		box-sizing: border-box;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		color: var(--text);
		padding: 10px 12px;
		outline: none;
		font-family: inherit;
		font-size: inherit;
		line-height: 1.4;
		transition: border-color 0.15s var(--ease);
	}

	.input-bar textarea:focus {
		border-color: var(--accent);
	}

	.input-bar .icone,
	.input-bar button[type='submit'],
	.input-bar .parar {
		height: 42px;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.input-bar button[type='submit'],
	.input-bar .parar {
		background: var(--accent-dim);
		border: 1px solid var(--accent);
		color: var(--accent);
		border-radius: var(--radius);
		padding: 0 18px;
		cursor: pointer;
		transition: background 0.15s var(--ease);
	}

	.input-bar button[type='submit']:hover:not(:disabled) {
		background: var(--accent);
		color: var(--bg);
	}

	.input-bar button:disabled {
		opacity: 0.5;
		cursor: default;
	}
</style>
