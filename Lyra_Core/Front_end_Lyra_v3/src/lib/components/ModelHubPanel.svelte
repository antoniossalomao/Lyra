<script lang="ts">
	// ModelHubPanel — hub de modelos Ollama (LYRA_NUCLEO.md §5.4).
	// Puxar modelo é download grande — por isso o fluxo exige
	// confirmação explícita ANTES de chamar o backend (mesmo padrão da Câmara
	// de Eco Heurística do próprio backend: nada de risco roda sem o usuário
	// confirmar de propósito).
	let { fechar }: { fechar: () => void } = $props();

	interface ModeloInstalado {
		nome: string;
		tamanho_bytes: number;
		modificado_em: string;
	}

	let modelos = $state<ModeloInstalado[]>([]);
	let erro = $state('');
	let nomeNovo = $state('');
	let confirmando = $state(false);
	let baixando = $state(false);
	let progresso = $state('');

	async function carregar() {
		try {
			const resp = await fetch('/ollama/models', { credentials: 'include' });
			const dados = await resp.json();
			if (dados.erro) throw new Error(dados.erro);
			modelos = dados.modelos;
			erro = '';
		} catch (e) {
			erro = e instanceof Error ? e.message : 'Falha ao listar modelos.';
		}
	}
	carregar();

	function formatarBytes(bytes: number): string {
		if (!bytes) return '—';
		const gb = bytes / 1024 ** 3;
		return gb >= 1 ? `${gb.toFixed(1)} GB` : `${(bytes / 1024 ** 2).toFixed(0)} MB`;
	}

	async function confirmarPull() {
		if (!nomeNovo.trim()) return;
		confirmando = false;
		baixando = true;
		progresso = 'Iniciando...';
		try {
			const resp = await fetch('/ollama/models/pull', {
				method: 'POST',
				credentials: 'include',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ nome: nomeNovo.trim() })
			});
			const reader = resp.body?.getReader();
			const decoder = new TextDecoder();
			let buffer = '';
			while (reader) {
				const { done, value } = await reader.read();
				if (done) break;
				buffer += decoder.decode(value, { stream: true });
				const linhas = buffer.split('\n\n');
				buffer = linhas.pop() ?? '';
				for (const linha of linhas) {
					const conteudo = linha.replace(/^data: /, '').trim();
					if (!conteudo || conteudo === '[DONE]') continue;
					const evento = JSON.parse(conteudo);
					if (evento.erro) {
						erro = evento.erro;
					} else if (evento.status) {
						progresso = evento.total
							? `${evento.status} (${Math.round(((evento.completed ?? 0) / evento.total) * 100)}%)`
							: evento.status;
					}
				}
			}
			nomeNovo = '';
			await carregar();
		} catch (e) {
			erro = e instanceof Error ? e.message : 'Falha ao baixar modelo.';
		} finally {
			baixando = false;
			progresso = '';
		}
	}
</script>

<div
	class="fundo"
	onclick={fechar}
	onkeydown={(e) => e.key === 'Escape' && fechar()}
	role="button"
	tabindex="0"
	aria-label="Fechar hub de modelos"
>
	<div class="painel" onclick={(e) => e.stopPropagation()} role="presentation">
		<header>
			<h2>Modelos (Ollama)</h2>
			<button onclick={fechar}>Fechar</button>
		</header>

		{#if erro}
			<p class="erro">{erro}</p>
		{/if}

		<ul class="modelos">
			{#each modelos as m}
				<li>
					<span>{m.nome}</span>
					<span class="dim">{formatarBytes(m.tamanho_bytes)}</span>
				</li>
			{/each}
			{#if !modelos.length && !erro}
				<li class="dim">Nenhum modelo instalado (ou Ollama fora do ar).</li>
			{/if}
		</ul>

		<div class="baixar">
			<input
				bind:value={nomeNovo}
				placeholder="nome:tag (ex: llama3.2:3b)"
				disabled={baixando}
			/>
			{#if !confirmando}
				<button onclick={() => (confirmando = true)} disabled={!nomeNovo.trim() || baixando}>
					Baixar
				</button>
			{/if}
		</div>

		{#if confirmando}
			<div class="confirmacao">
				<p>Baixar <strong>{nomeNovo}</strong>? Modelos costumam ter alguns GB — confirma?</p>
				<button onclick={confirmarPull}>Confirmar download</button>
				<button onclick={() => (confirmando = false)}>Cancelar</button>
			</div>
		{/if}

		{#if baixando}
			<p class="dim">{progresso}</p>
		{/if}
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
		max-width: 380px;
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

	header button {
		background: transparent;
		border: 1px solid var(--border);
		color: var(--text-dim);
		border-radius: var(--radius);
		padding: 4px 10px;
		cursor: pointer;
	}

	.modelos {
		list-style: none;
		margin: 0 0 14px;
		padding: 0;
		max-height: 200px;
		overflow-y: auto;
		font-size: 0.85rem;
	}

	.modelos li {
		display: flex;
		justify-content: space-between;
		padding: 4px 0;
	}

	.dim {
		color: var(--text-dim);
		font-size: 0.8rem;
	}

	.baixar {
		display: flex;
		gap: 8px;
	}

	.baixar input {
		flex: 1;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		color: var(--text);
		padding: 8px 10px;
		outline: none;
	}

	.baixar button,
	.confirmacao button {
		background: var(--accent-dim);
		border: 1px solid var(--accent);
		color: var(--accent);
		border-radius: var(--radius);
		padding: 8px 12px;
		cursor: pointer;
		font-size: 0.85rem;
	}

	.baixar button:disabled {
		opacity: 0.5;
		cursor: default;
	}

	.confirmacao {
		margin-top: 10px;
		padding-top: 10px;
		border-top: 1px solid var(--border);
		display: flex;
		flex-direction: column;
		gap: 8px;
		font-size: 0.85rem;
	}

	.erro {
		color: var(--danger);
		font-size: 0.85rem;
	}
</style>
