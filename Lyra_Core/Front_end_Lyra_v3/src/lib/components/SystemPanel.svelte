<script lang="ts">
	// SystemPanel — monitor de sistema/logs (LYRA_NUCLEO.md §5.4).
	// Só a parte "monitor" por enquanto — viewer de log de arquivo
	// (maestro.log) fica pra depois, exige um endpoint novo de leitura de
	// arquivo que ainda não existe no backend.
	import { api } from '$lib/api';

	let { fechar }: { fechar: () => void } = $props();

	let health = $state<Record<string, any> | null>(null);
	let metrics = $state<Record<string, any> | null>(null);
	let ferramentas = $state<{ nome: string; descricao: string; habilitada: boolean }[]>([]);
	let mostrarFerramentas = $state(false);
	let mostrarLogs = $state(false);
	let logs = $state<string[]>([]);
	let erro = $state('');

	async function alternarLogs() {
		mostrarLogs = !mostrarLogs;
		if (mostrarLogs) {
			try {
				logs = (await api.logs('log', 100)).linhas;
			} catch {
				logs = [];
			}
		}
	}

	async function atualizar() {
		try {
			[health, metrics] = await Promise.all([api.health(), api.metrics()]);
			erro = '';
		} catch (e) {
			erro = e instanceof Error ? e.message : 'Falha ao consultar o backend.';
		}
	}

	async function carregarFerramentas() {
		try {
			ferramentas = (await api.tools()).ferramentas;
		} catch {
			// backend fora do ar — painel de ferramentas fica vazio, resto do painel segue
		}
	}
	carregarFerramentas();

	async function alternarFerramenta(nome: string) {
		try {
			await api.toolToggle(nome);
			await carregarFerramentas();
		} catch {
			// falha silenciosa — lista simplesmente não muda, usuário pode tentar de novo
		}
	}

	$effect(() => {
		atualizar();
		const id = setInterval(atualizar, 4000);
		return () => clearInterval(id);
	});
</script>

<div
	class="fundo"
	onclick={fechar}
	onkeydown={(e) => e.key === 'Escape' && fechar()}
	role="button"
	tabindex="0"
	aria-label="Fechar monitor de sistema"
>
	<div class="painel" onclick={(e) => e.stopPropagation()} role="presentation">
		<header>
			<h2>Sistema</h2>
			<button onclick={fechar}>Fechar</button>
		</header>

		{#if erro}
			<p class="erro">{erro}</p>
		{/if}

		{#if metrics}
			<div class="grade">
				<div class="metrica"><span class="dim">CPU</span><span>{metrics.cpu_pct ?? '—'}%</span></div>
				<div class="metrica"><span class="dim">RAM</span><span>{metrics.ram_pct ?? '—'}%</span></div>
				<div class="metrica"><span class="dim">GPU</span><span>{metrics.gpu_pct ?? '—'}%</span></div>
				<div class="metrica"><span class="dim">VRAM</span><span>{metrics.vram_pct ?? '—'}%</span></div>
				<div class="metrica"><span class="dim">Latência último chat</span><span>{metrics.latencia_ms ?? '—'} ms</span></div>
			</div>
		{/if}

		{#if health}
			<ul class="servicos">
				{#each Object.entries(health) as [nome, info]}
					{#if info && typeof info === 'object' && 'ok' in info}
						<li>
							<span class="ponto" class:ok={info.ok}></span>
							{nome}
							{#if info.latencia_ms != null}<span class="dim">({info.latencia_ms}ms)</span>{/if}
						</li>
					{/if}
				{/each}
			</ul>
		{/if}

		{#if ferramentas.length}
			<button class="toggle-ferramentas" onclick={() => (mostrarFerramentas = !mostrarFerramentas)}>
				{mostrarFerramentas ? '▾' : '▸'} Ferramentas ({ferramentas.length})
			</button>
			{#if mostrarFerramentas}
				<ul class="ferramentas">
					{#each ferramentas as f}
						<li>
							<button
								class="ferramenta-toggle"
								class:desligada={!f.habilitada}
								title={f.descricao}
								onclick={() => alternarFerramenta(f.nome)}
							>
								{f.nome}
							</button>
						</li>
					{/each}
				</ul>
			{/if}
		{/if}

		<button class="toggle-ferramentas" onclick={alternarLogs}>
			{mostrarLogs ? '▾' : '▸'} Logs (maestro.log)
		</button>
		{#if mostrarLogs}
			<pre class="logs">{logs.join('\n') || '(vazio)'}</pre>
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
		max-width: 360px;
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

	.grade {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 10px;
		margin-bottom: 14px;
	}

	.metrica {
		display: flex;
		flex-direction: column;
		gap: 2px;
		font-size: 0.9rem;
	}

	.dim {
		color: var(--text-dim);
		font-size: 0.75rem;
	}

	.servicos {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 6px;
		font-size: 0.85rem;
	}

	.ponto {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--danger);
		margin-right: 6px;
	}

	.ponto.ok {
		background: var(--accent);
	}

	.erro {
		color: var(--danger);
		font-size: 0.85rem;
	}

	.toggle-ferramentas {
		background: transparent;
		border: none;
		color: var(--text-dim);
		font-size: 0.8rem;
		cursor: pointer;
		padding: 8px 0 0;
		margin-top: 10px;
		border-top: 1px solid var(--border);
		width: 100%;
		text-align: left;
	}

	.ferramentas {
		list-style: none;
		margin: 8px 0 0;
		padding: 0;
		max-height: 160px;
		overflow-y: auto;
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 4px;
		font-size: 0.75rem;
	}

	.ferramenta-toggle {
		width: 100%;
		text-align: left;
		background: transparent;
		border: none;
		color: var(--text);
		cursor: pointer;
		font-size: 0.75rem;
		padding: 2px 0;
	}

	.ferramenta-toggle.desligada {
		color: var(--text-dim);
		text-decoration: line-through;
	}

	.logs {
		margin: 8px 0 0;
		max-height: 220px;
		overflow: auto;
		font-size: 0.7rem;
		color: var(--text-dim);
		background: var(--bg);
		border-radius: var(--radius);
		padding: 8px;
		white-space: pre-wrap;
		word-break: break-all;
	}
</style>
