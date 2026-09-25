<script lang="ts">
	// PromptLibraryPanel — biblioteca de prompts salvos (item novo, auditoria
	// de paridade com Open WebUI 2026-08-12). Clicar num prompt insere o
	// conteúdo no composer e fecha o painel — sem autocomplete de slash-command
	// ainda (o Open WebUI tem "/comando" digitado direto no campo; aqui é só
	// clique, mais simples, mesmo valor pro caso de uso "guardar pergunta que
	// eu repito bastante").
	import { api } from '$lib/api';

	let { fechar, onInserir }: { fechar: () => void; onInserir: (conteudo: string) => void } = $props();

	interface Prompt {
		id: string;
		titulo: string;
		comando: string;
		conteudo: string;
	}

	let prompts = $state<Prompt[]>([]);
	let erro = $state('');
	let editando = $state<Prompt | null>(null);
	let criandoNovo = $state(false);

	let rascunhoTitulo = $state('');
	let rascunhoComando = $state('');
	let rascunhoConteudo = $state('');

	async function carregar() {
		try {
			prompts = (await api.promptsListar()).prompts;
			erro = '';
		} catch {
			erro = 'Não foi possível falar com o backend (cerebro_maestro :8000).';
		}
	}
	carregar();

	function iniciarNovo() {
		rascunhoTitulo = '';
		rascunhoComando = '';
		rascunhoConteudo = '';
		criandoNovo = true;
		editando = null;
	}

	function iniciarEdicao(p: Prompt) {
		rascunhoTitulo = p.titulo;
		rascunhoComando = p.comando;
		rascunhoConteudo = p.conteudo;
		editando = p;
		criandoNovo = false;
	}

	function cancelarEdicao() {
		editando = null;
		criandoNovo = false;
	}

	async function salvar() {
		const titulo = rascunhoTitulo.trim();
		const conteudo = rascunhoConteudo.trim();
		if (!titulo || !conteudo) return;
		const comando = rascunhoComando.trim();
		if (editando) {
			await api.promptEditar(editando.id, titulo, comando, conteudo);
		} else {
			await api.promptCriar(titulo, comando, conteudo);
		}
		cancelarEdicao();
		await carregar();
	}

	async function excluir(p: Prompt) {
		if (!confirm(`Excluir o prompt "${p.titulo}"?`)) return;
		await api.promptDeletar(p.id);
		await carregar();
	}

	function usar(p: Prompt) {
		onInserir(p.conteudo);
		fechar();
	}
</script>

<div
	class="fundo"
	onclick={fechar}
	onkeydown={(e) => e.key === 'Escape' && fechar()}
	role="button"
	tabindex="0"
	aria-label="Fechar biblioteca de prompts"
>
	<div class="painel" onclick={(e) => e.stopPropagation()} role="presentation">
		<header>
			<h2>Prompts salvos</h2>
			<button class="fechar-x" onclick={fechar} aria-label="Fechar">✕</button>
		</header>

		{#if erro}
			<p class="erro">{erro}</p>
		{/if}

		{#if criandoNovo || editando}
			<form
				class="form-prompt"
				onsubmit={(e) => {
					e.preventDefault();
					salvar();
				}}
			>
				<input bind:value={rascunhoTitulo} placeholder="Título (ex: Resumo do dia)" />
				<input bind:value={rascunhoComando} placeholder="Rótulo curto opcional (ex: resumo)" />
				<textarea bind:value={rascunhoConteudo} rows="4" placeholder="Texto do prompt..."></textarea>
				<div class="form-acoes">
					<button type="submit" disabled={!rascunhoTitulo.trim() || !rascunhoConteudo.trim()}>
						{editando ? 'Salvar' : 'Criar'}
					</button>
					<button type="button" class="secundario" onclick={cancelarEdicao}>Cancelar</button>
				</div>
			</form>
		{:else}
			<button class="novo" onclick={iniciarNovo}>+ Novo prompt</button>
		{/if}

		<ul class="lista">
			{#each prompts as p}
				<li>
					<button class="item" onclick={() => usar(p)}>
						<span class="titulo">{p.titulo}</span>
						{#if p.comando}<span class="comando">{p.comando}</span>{/if}
					</button>
					<span class="acoes-item">
						<button class="mini" title="Editar" onclick={() => iniciarEdicao(p)}>
							<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M11 2l3 3-8 8-3.5 1L3.5 11z" /></svg>
						</button>
						<button class="mini" title="Excluir" onclick={() => excluir(p)}>
							<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M3 4.5h10M6.5 4.5V3a1 1 0 0 1 1-1h1a1 1 0 0 1 1 1v1.5M4.5 4.5l.6 8.5a1 1 0 0 0 1 .9h3.8a1 1 0 0 0 1-.9l.6-8.5" /></svg>
						</button>
					</span>
				</li>
			{/each}
			{#if !prompts.length && !erro}
				<li class="vazio">Nenhum prompt salvo ainda.</li>
			{/if}
		</ul>
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
		padding: 20px;
		width: 100%;
		max-width: 420px;
		max-height: 70vh;
		display: flex;
		flex-direction: column;
	}

	header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 12px;
	}

	h2 {
		font-weight: 400;
		font-size: 1.1rem;
		margin: 0;
	}

	.fechar-x {
		background: transparent;
		border: none;
		color: var(--text-dim);
		cursor: pointer;
		font-size: 0.9rem;
	}

	.erro {
		color: var(--danger);
		font-size: 0.85rem;
	}

	.novo {
		background: var(--accent-dim);
		border: 1px solid var(--accent);
		color: var(--accent);
		border-radius: var(--radius);
		padding: 8px 12px;
		cursor: pointer;
		font-size: 0.85rem;
		margin-bottom: 12px;
		text-align: left;
	}

	.form-prompt {
		display: flex;
		flex-direction: column;
		gap: 8px;
		margin-bottom: 14px;
		padding-bottom: 14px;
		border-bottom: 1px solid var(--border);
	}

	.form-prompt input,
	.form-prompt textarea {
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		color: var(--text);
		padding: 8px 10px;
		font-family: inherit;
		font-size: 0.85rem;
		outline: none;
		resize: vertical;
	}

	.form-prompt input:focus,
	.form-prompt textarea:focus {
		border-color: var(--accent);
	}

	.form-acoes {
		display: flex;
		gap: 8px;
	}

	.form-acoes button[type='submit'] {
		background: var(--accent-dim);
		border: 1px solid var(--accent);
		color: var(--accent);
		border-radius: var(--radius);
		padding: 7px 14px;
		cursor: pointer;
		font-size: 0.82rem;
	}

	.form-acoes button:disabled {
		opacity: 0.5;
		cursor: default;
	}

	.secundario {
		background: transparent;
		border: 1px solid var(--border);
		color: var(--text-dim);
		border-radius: var(--radius);
		padding: 7px 14px;
		cursor: pointer;
		font-size: 0.82rem;
	}

	.lista {
		list-style: none;
		margin: 0;
		padding: 0;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.lista li {
		display: flex;
		align-items: center;
		gap: 2px;
		border-radius: var(--radius);
	}

	.lista li:hover {
		background: var(--surface-2);
	}

	.lista li:hover .acoes-item {
		opacity: 1;
	}

	.item {
		flex: 1;
		display: flex;
		align-items: baseline;
		gap: 8px;
		background: transparent;
		border: none;
		color: var(--text);
		text-align: left;
		padding: 8px 10px;
		cursor: pointer;
		min-width: 0;
	}

	.item .titulo {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.item .comando {
		flex-shrink: 0;
		font-size: 0.7rem;
		color: var(--text-dim);
		font-family: monospace;
	}

	.acoes-item {
		display: flex;
		gap: 2px;
		flex-shrink: 0;
		padding-right: 8px;
		opacity: 0;
		transition: opacity 0.15s var(--ease);
	}

	.mini {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 4px;
		border-radius: 5px;
		background: transparent;
		border: none;
		color: var(--text-dim);
		cursor: pointer;
		transition: color 0.15s var(--ease), background 0.15s var(--ease);
	}

	.mini:hover {
		color: var(--text);
		background: var(--bg);
	}

	.vazio {
		color: var(--text-dim);
		font-size: 0.82rem;
		padding: 8px 10px;
	}
</style>
