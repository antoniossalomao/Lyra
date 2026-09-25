<script lang="ts">
	import { api, type Sessao } from '$lib/api';

	let {
		sessoes,
		colapsada = $bindable(false),
		onSelect,
		onNovaSessao,
		onAtualizar,
		onAbrirBusca,
		onAbrirConfig
	}: {
		sessoes: Sessao[];
		colapsada: boolean;
		onSelect: (id: string) => void;
		onNovaSessao: () => void;
		/** Recarrega a lista de sessões sem criar/ativar nada — usado depois de
		 * favoritar/renomear/excluir, que mudam dados mas não a sessão ativa. */
		onAtualizar: () => void;
		onAbrirBusca: () => void;
		onAbrirConfig: () => void;
	} = $props();

	let renomeando = $state<string | null>(null);
	let rascunho = $state('');

	// Agrupamento por data (paridade v2): Hoje / Ontem / Essa semana / Mais antigas.
	// 'legado' (sem data real) sempre cai em "Mais antigas".
	function agruparPorData(lista: Sessao[]): [string, Sessao[]][] {
		const hoje = new Date();
		hoje.setHours(0, 0, 0, 0);
		const ontem = new Date(hoje);
		ontem.setDate(ontem.getDate() - 1);
		const semana = new Date(hoje);
		semana.setDate(semana.getDate() - 7);

		const grupos: Record<string, Sessao[]> = {
			Hoje: [],
			Ontem: [],
			'Essa semana': [],
			'Mais antigas': []
		};
		for (const s of lista) {
			if (s.sessao_id === 'legado') {
				grupos['Mais antigas'].push(s);
				continue;
			}
			const d = new Date(s.criada);
			if (d >= hoje) grupos['Hoje'].push(s);
			else if (d >= ontem) grupos['Ontem'].push(s);
			else if (d >= semana) grupos['Essa semana'].push(s);
			else grupos['Mais antigas'].push(s);
		}
		return Object.entries(grupos).filter(([, v]) => v.length > 0);
	}

	let sessoesOrdenadas = $derived(
		[...sessoes].sort((a, b) => Number(b.favorita ?? false) - Number(a.favorita ?? false))
	);
	let grupos = $derived(agruparPorData(sessoesOrdenadas));

	async function alternarFavorita(s: Sessao, e: MouseEvent) {
		e.stopPropagation();
		await api.sessaoFavoritar(s.sessao_id, !s.favorita);
		onAtualizar();
	}

	function iniciarRename(s: Sessao, e: MouseEvent) {
		e.stopPropagation();
		rascunho = s.titulo;
		renomeando = s.sessao_id;
	}

	async function confirmarRename(id: string) {
		const titulo = rascunho.trim();
		renomeando = null;
		if (!titulo) return;
		await api.sessaoRenomear(id, titulo);
		onAtualizar();
	}

	async function excluir(s: Sessao, e: MouseEvent) {
		e.stopPropagation();
		if (!confirm(`Excluir "${s.titulo}"?`)) return;
		await api.sessaoDeletar(s.sessao_id);
		onAtualizar();
	}
</script>

<aside class="sb" class:colapsada>
	<div class="sb-head">
		{#if !colapsada}<span class="brand">Lyra</span>{/if}
		<button class="icone" title={colapsada ? 'Expandir' : 'Recolher'} onclick={() => (colapsada = !colapsada)}>
			☰
		</button>
	</div>

	<button class="acao primaria" onclick={onNovaSessao}>+{!colapsada ? ' Nova conversa' : ''}</button>
	<button class="acao" onclick={onAbrirBusca}>⌕{!colapsada ? ' Buscar memória' : ''}</button>

	{#if !colapsada}
		<div class="lista">
			{#each grupos as [rotulo, itens]}
				<div class="grupo-rotulo">{rotulo}</div>
				{#each itens as s (s.sessao_id)}
					<div class="linha" class:ativa={s.ativa}>
						<button
							class="estrela"
							class:marcada={s.favorita}
							onclick={(e) => alternarFavorita(s, e)}
							title={s.favorita ? 'Desfavoritar' : 'Favoritar'}
						>
							{s.favorita ? '★' : '☆'}
						</button>
						{#if renomeando === s.sessao_id}
							<input
								class="rename-input"
								bind:value={rascunho}
								onclick={(e) => e.stopPropagation()}
								onkeydown={(e) => {
									if (e.key === 'Enter') confirmarRename(s.sessao_id);
									if (e.key === 'Escape') renomeando = null;
								}}
								onblur={() => (renomeando = null)}
							/>
						{:else}
							<button class="titulo" onclick={() => onSelect(s.sessao_id)}>{s.titulo}</button>
							{#if !s.somente_leitura}
								<span class="acoes-linha">
									<button class="mini" title="Renomear" onclick={(e) => iniciarRename(s, e)}>
										<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M11 2l3 3-8 8-3.5 1L3.5 11z" /></svg>
									</button>
									<button class="mini" title="Excluir" onclick={(e) => excluir(s, e)}>
										<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M3 4.5h10M6.5 4.5V3a1 1 0 0 1 1-1h1a1 1 0 0 1 1 1v1.5M4.5 4.5l.6 8.5a1 1 0 0 0 1 .9h3.8a1 1 0 0 0 1-.9l.6-8.5" /></svg>
									</button>
								</span>
							{/if}
						{/if}
					</div>
				{/each}
			{/each}
		</div>
	{/if}

	<div class="sb-foot">
		<button class="conta" onclick={onAbrirConfig}>
			<span class="avatar">A</span>
			{#if !colapsada}<span>Configurações</span>{/if}
		</button>
	</div>
</aside>

<style>
	.sb {
		width: 220px;
		background: var(--surface);
		border-right: 1px solid var(--border);
		padding: 16px 12px;
		display: flex;
		flex-direction: column;
		gap: 10px;
		overflow-y: auto;
		flex-shrink: 0;
	}

	.sb.colapsada {
		width: 56px;
		align-items: center;
		padding: 16px 8px;
	}

	.sb-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
	}

	.brand {
		font-weight: 500;
		font-size: 0.95rem;
	}

	.icone {
		background: transparent;
		border: none;
		color: var(--text-dim);
		cursor: pointer;
		font-size: 0.9rem;
		border-radius: 6px;
		padding: 4px 6px;
		transition: color 0.15s var(--ease), background 0.15s var(--ease);
	}

	.icone:hover {
		color: var(--text);
		background: var(--surface-2);
	}

	.acao {
		background: transparent;
		border: 1px solid var(--border);
		color: var(--text-dim);
		border-radius: var(--radius);
		padding: 8px 10px;
		cursor: pointer;
		text-align: left;
		font-size: 0.85rem;
		transition: color 0.15s var(--ease), border-color 0.15s var(--ease), background 0.15s var(--ease);
	}

	.acao:hover {
		color: var(--text);
		border-color: var(--accent);
	}

	.acao.primaria {
		background: var(--accent-dim);
		border-color: var(--accent);
		color: var(--accent);
	}

	.acao.primaria:hover {
		background: var(--accent);
		color: var(--bg);
	}

	.lista {
		flex: 1;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.grupo-rotulo {
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--text-dim);
		padding: 10px 4px 4px;
	}

	.linha {
		display: flex;
		align-items: center;
		gap: 2px;
		border-radius: var(--radius);
	}

	.linha:hover,
	.linha.ativa {
		background: var(--surface-2);
	}

	.linha button {
		background: transparent;
		border: none;
		color: var(--text-dim);
		cursor: pointer;
		font-size: 0.83rem;
	}

	.titulo {
		flex: 1;
		text-align: left;
		padding: 7px 4px 7px 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.linha.ativa .titulo {
		color: var(--text);
	}

	.estrela {
		flex-shrink: 0;
		padding: 7px 0 7px 8px;
		opacity: 0.5;
	}

	.estrela.marcada {
		opacity: 1;
		color: var(--accent);
	}

	.estrela:hover {
		opacity: 1;
	}

	.acoes-linha {
		display: flex;
		align-items: center;
		gap: 2px;
		flex-shrink: 0;
		padding-right: 6px;
		opacity: 0;
		transition: opacity 0.15s var(--ease);
	}

	.linha:hover .acoes-linha {
		opacity: 1;
	}

	.mini {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 4px;
		border-radius: 5px;
		transition: color 0.15s var(--ease), background 0.15s var(--ease);
	}

	.mini:hover {
		color: var(--text);
		background: var(--bg);
	}

	.rename-input {
		flex: 1;
		background: var(--bg);
		border: 1px solid var(--accent);
		border-radius: 5px;
		color: var(--text);
		font-size: 0.83rem;
		font-family: inherit;
		padding: 4px 6px;
		margin: 2px 4px 2px 0;
	}

	.sb-foot {
		border-top: 1px solid var(--border);
		padding-top: 10px;
	}

	.conta {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		background: transparent;
		border: none;
		color: var(--text-dim);
		cursor: pointer;
		padding: 6px 4px;
		font-size: 0.85rem;
	}

	.conta:hover {
		color: var(--text);
	}

	.avatar {
		width: 22px;
		height: 22px;
		border-radius: 50%;
		background: var(--accent-dim);
		color: var(--accent);
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 0.75rem;
		flex-shrink: 0;
	}
</style>
