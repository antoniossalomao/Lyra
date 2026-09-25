<script lang="ts">
	import { api } from '$lib/api';
	import { settings, type TamanhoFonte } from '$lib/settings.svelte';

	let { fechar }: { fechar: () => void } = $props();

	const ABAS = [
		'Perfil',
		'Aparência',
		'Modelo e voz',
		'Apps conectados',
		'Controle de dados',
		'Atalhos',
		'Sobre'
	] as const;
	type Aba = (typeof ABAS)[number];

	const MODELOS = [
		{ valor: 'auto', rotulo: 'Auto (cascata)' },
		{ valor: 'groq', rotulo: 'Groq' },
		{ valor: 'gemini', rotulo: 'Gemini' },
		{ valor: 'claude', rotulo: 'Claude' },
		{ valor: 'local', rotulo: 'Local' }
	];

	const NOME_INTEGRACAO: Record<string, string> = {
		telegram: 'Bot do Telegram',
		voz_live: 'Voz live (Gemini)',
		mic: 'Mic (wake-word)',
		tts: 'Texto-pra-voz',
		enxame: 'Agentes em enxame',
		upload: 'Upload de arquivo'
	};

	let aba = $state<Aba>('Modelo e voz');
	let info = $state<{ ativo: boolean; versao: string } | null>(null);
	let integracoes = $state<Record<string, { online: boolean; status: string }> | null>(null);
	let integracoesErro = $state(false);
	let integracoesCarregando = $state(false);
	let nomeRascunho = $state(settings.nome);

	$effect(() => {
		api.info().then((r) => (info = r)).catch(() => {});
	});

	$effect(() => {
		if (aba === 'Apps conectados' && !integracoes && !integracoesCarregando) {
			integracoesCarregando = true;
			api
				.integracoes()
				.then((r) => {
					integracoes = r;
					integracoesErro = false;
				})
				.catch(() => {
					integracoesErro = true;
				})
				.finally(() => {
					integracoesCarregando = false;
				});
		}
	});

	async function exportar() {
		try {
			const { markdown } = await api.exportarConversa();
			const blob = new Blob([markdown], { type: 'text/markdown' });
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = `lyra-conversa-${new Date().toISOString().slice(0, 10)}.md`;
			a.click();
			URL.revokeObjectURL(url);
		} catch {
			// backend fora do ar
		}
	}

	async function limpar() {
		if (!confirm('Limpar o histórico desta conversa (em memória)? A memória de longo prazo não é afetada.'))
			return;
		await api.historicoLimpar();
		location.reload();
	}
</script>

<div
	class="fundo"
	onclick={fechar}
	onkeydown={(e) => e.key === 'Escape' && fechar()}
	role="button"
	tabindex="0"
	aria-label="Fechar configurações"
>
	<div class="painel" onclick={(e) => e.stopPropagation()} role="presentation">
		<nav>
			<h2>Configurações</h2>
			{#each ABAS as a}
				<button class:ativa={aba === a} onclick={() => (aba = a)}>{a}</button>
			{/each}
		</nav>

		<div class="corpo">
			{#if aba === 'Perfil'}
				<h3>Perfil</h3>
				<div class="linha">
					<span>Nome de exibição</span>
					<input
						bind:value={nomeRascunho}
						onblur={() => nomeRascunho.trim() && settings.setNome(nomeRascunho.trim())}
						onkeydown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
					/>
				</div>
				<div class="linha">
					<span>Assistente</span>
					<span class="valor-fixo">Lyra AI</span>
				</div>
			{:else if aba === 'Aparência'}
				<h3>Aparência</h3>
				<div class="linha">
					<span>Tema</span>
					<span class="dim">Escuro (fixo)</span>
				</div>
				<div class="linha">
					<span>Tamanho do texto</span>
					<div class="seletor-tamanho">
						{#each ['pequeno', 'medio', 'grande'] as const as t}
							<button
								class:ativa={settings.tamanhoFonte === t}
								onclick={() => settings.setTamanhoFonte(t as TamanhoFonte)}
								style="font-size: {t === 'pequeno' ? '0.72rem' : t === 'medio' ? '0.86rem' : '1.02rem'}"
							>
								Aa
							</button>
						{/each}
					</div>
				</div>
				<div class="linha">
					<div>
						<div>Reduzir movimento</div>
						<div class="descricao">Desliga animações de transição e fade.</div>
					</div>
					<button
						class="toggle"
						class:on={settings.reduzirMovimento}
						onclick={() => settings.setReduzirMovimento(!settings.reduzirMovimento)}
						aria-label="Reduzir movimento"
					><i></i></button>
				</div>
			{:else if aba === 'Modelo e voz'}
				<h3>Modelo e voz</h3>
				<div class="linha">
					<span>Respostas em voz (TTS)</span>
					<button
						class="toggle"
						class:on={!settings.ttsMudo}
						onclick={async () => {
							settings.setTtsMudo(!settings.ttsMudo);
							await api.ttsMudo(settings.ttsMudo);
						}}
						aria-label="Alternar TTS"
					><i></i></button>
				</div>
				<div class="linha">
					<span>Modelo padrão</span>
					<select bind:value={settings.modelo} onchange={() => settings.setModelo(settings.modelo)}>
						{#each MODELOS as m}
							<option value={m.valor}>{m.rotulo}</option>
						{/each}
					</select>
				</div>
			{:else if aba === 'Apps conectados'}
				<h3>Apps conectados</h3>
				{#if integracoesErro}
					<p class="descricao erro">Não foi possível falar com o backend (cerebro_maestro :8000).</p>
				{:else if !integracoes}
					<p class="descricao">Carregando...</p>
				{:else}
					{#each Object.entries(integracoes) as [id, i]}
						<div class="linha">
							<div class="integ">
								<span class="ponto" class:on={i.online}></span>
								<div>
									<div>{NOME_INTEGRACAO[id] ?? id}</div>
									<div class="descricao">{i.status}</div>
								</div>
							</div>
						</div>
					{/each}
				{/if}
			{:else if aba === 'Controle de dados'}
				<h3>Controle de dados</h3>
				<div class="linha">
					<div>
						<div>Exportar esta conversa</div>
						<div class="descricao">Baixa o chat atual como markdown.</div>
					</div>
					<button class="botao" onclick={exportar}>Exportar</button>
				</div>
				<div class="linha">
					<div>
						<div>Limpar esta conversa</div>
						<div class="descricao">
							Apaga só o histórico em memória — memória de longo prazo (SurrealDB/Qdrant) não é
							afetada.
						</div>
					</div>
					<button class="botao perigo" onclick={limpar}>Limpar</button>
				</div>
			{:else if aba === 'Atalhos'}
				<h3>Atalhos de teclado</h3>
				<div class="linha"><span>Enviar mensagem</span><span class="tecla">Enter</span></div>
				<div class="linha"><span>Nova linha</span><span class="tecla">Shift+Enter</span></div>
				<div class="linha"><span>Buscar memória</span><span class="tecla">Ctrl+K</span></div>
				<div class="linha"><span>Nova conversa</span><span class="tecla">Ctrl+Shift+O</span></div>
			{:else if aba === 'Sobre'}
				<h3>Sobre</h3>
				<div class="linha">
					<span>Cérebro Maestro</span>
					<span>{info ? `v${info.versao} · ${info.ativo ? 'online' : 'offline'}` : '—'}</span>
				</div>
				<div class="linha">
					<span>Dashboard do sistema</span>
					<a href="http://127.0.0.1:8000/dashboard" target="_blank" rel="noreferrer">Abrir ↗</a>
				</div>
			{/if}
		</div>

		<button class="fechar-x" onclick={fechar} aria-label="Fechar">✕</button>
	</div>
</div>

<style>
	.fundo {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.5);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 10;
	}

	.painel {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		box-shadow: var(--shadow);
		width: 100%;
		max-width: 640px;
		height: 480px;
		display: grid;
		grid-template-columns: 180px 1fr;
		position: relative;
		overflow: hidden;
	}

	nav {
		background: var(--surface-2);
		border-right: 1px solid var(--border);
		padding: 16px 10px;
		display: flex;
		flex-direction: column;
		gap: 2px;
		overflow-y: auto;
	}

	nav h2 {
		font-size: 0.95rem;
		font-weight: 500;
		margin: 0 6px 10px;
	}

	nav button {
		background: transparent;
		border: none;
		color: var(--text-dim);
		text-align: left;
		padding: 7px 8px;
		border-radius: var(--radius);
		cursor: pointer;
		font-size: 0.82rem;
	}

	nav button:hover {
		background: var(--surface);
	}

	nav button.ativa {
		background: var(--accent-dim);
		color: var(--accent);
	}

	.corpo {
		padding: 20px 24px;
		overflow-y: auto;
	}

	h3 {
		font-weight: 500;
		font-size: 1rem;
		margin: 0 0 14px;
	}

	.linha {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		padding: 10px 0;
		border-bottom: 1px solid var(--border);
		font-size: 0.85rem;
	}

	.linha:last-child {
		border-bottom: none;
	}

	.descricao {
		color: var(--text-dim);
		font-size: 0.75rem;
		margin-top: 2px;
	}

	.descricao.erro {
		color: var(--danger);
	}

	.dim {
		color: var(--text-dim);
	}

	.valor-fixo {
		color: var(--text);
	}

	input,
	select {
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 6px;
		color: var(--text);
		padding: 6px 8px;
		font-size: 0.82rem;
		font-family: inherit;
		outline: none;
	}

	input:focus,
	select:focus {
		border-color: var(--accent);
	}

	.seletor-tamanho {
		display: flex;
		gap: 4px;
	}

	.seletor-tamanho button {
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 6px;
		color: var(--text-dim);
		padding: 4px 10px;
		cursor: pointer;
	}

	.seletor-tamanho button.ativa {
		border-color: var(--accent);
		color: var(--accent);
	}

	.toggle {
		width: 34px;
		height: 20px;
		border-radius: 999px;
		background: var(--surface-2);
		border: 1px solid var(--border);
		position: relative;
		cursor: pointer;
		flex-shrink: 0;
	}

	.toggle i {
		position: absolute;
		top: 1px;
		left: 1px;
		width: 16px;
		height: 16px;
		border-radius: 50%;
		background: var(--text-dim);
		transition: transform 0.15s var(--ease);
	}

	.toggle.on {
		border-color: var(--accent);
	}

	.toggle.on i {
		background: var(--accent);
		transform: translateX(14px);
	}

	.botao {
		background: transparent;
		border: 1px solid var(--border);
		color: var(--accent);
		border-radius: var(--radius);
		padding: 6px 12px;
		cursor: pointer;
		font-size: 0.8rem;
	}

	.botao.perigo {
		color: var(--danger);
		border-color: var(--danger);
	}

	.integ {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.ponto {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: var(--danger);
		flex-shrink: 0;
	}

	.ponto.on {
		background: var(--accent);
	}

	.tecla {
		font-family: monospace;
		background: var(--surface-2);
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 1px 6px;
		font-size: 0.78rem;
	}

	.fechar-x {
		position: absolute;
		top: 14px;
		right: 16px;
		background: transparent;
		border: none;
		color: var(--text-dim);
		cursor: pointer;
		font-size: 0.9rem;
	}

	.fechar-x:hover {
		color: var(--text);
	}
</style>
