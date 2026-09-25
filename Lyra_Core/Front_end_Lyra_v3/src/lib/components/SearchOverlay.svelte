<script lang="ts">
	import { api } from '$lib/api';

	let { fechar }: { fechar: () => void } = $props();

	let q = $state('');
	let resultados = $state<{ id: string; titulo: string; categoria: string; trecho: string }[]>([]);
	let buscando = $state(false);
	let input: HTMLInputElement | undefined = $state();

	let debounceId: ReturnType<typeof setTimeout>;

	$effect(() => {
		clearTimeout(debounceId);
		const termo = q.trim();
		if (!termo) {
			resultados = [];
			return;
		}
		debounceId = setTimeout(async () => {
			buscando = true;
			try {
				resultados = (await api.buscar(termo)).resultados;
			} catch {
				resultados = [];
			} finally {
				buscando = false;
			}
		}, 350);
		return () => clearTimeout(debounceId);
	});

	$effect(() => {
		input?.focus();
	});
</script>

<div
	class="fundo"
	onclick={fechar}
	onkeydown={(e) => e.key === 'Escape' && fechar()}
	role="button"
	tabindex="0"
	aria-label="Fechar busca"
>
	<div class="painel" onclick={(e) => e.stopPropagation()} role="presentation">
		<input
			bind:this={input}
			bind:value={q}
			placeholder="Buscar na memória..."
			onkeydown={(e) => e.key === 'Escape' && fechar()}
		/>
		{#if buscando}
			<p class="vazio">Buscando...</p>
		{:else if q.trim() && resultados.length === 0}
			<p class="vazio">Sem resultados.</p>
		{/if}
		{#each resultados as r}
			<div class="resultado">
				<div class="resultado-titulo">{r.titulo || r.categoria || 'sem título'}</div>
				<div class="resultado-trecho">{r.trecho}</div>
			</div>
		{/each}
	</div>
</div>

<style>
	.fundo {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.5);
		display: flex;
		align-items: flex-start;
		justify-content: center;
		padding-top: 12vh;
		z-index: 10;
	}

	.painel {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		box-shadow: var(--shadow);
		width: 100%;
		max-width: 520px;
		max-height: 60vh;
		overflow-y: auto;
		padding: 12px;
	}

	input {
		width: 100%;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		color: var(--text);
		padding: 10px 12px;
		outline: none;
		font-size: 0.95rem;
	}

	input:focus {
		border-color: var(--accent);
	}

	.vazio {
		color: var(--text-dim);
		font-size: 0.85rem;
		padding: 12px 4px 4px;
		margin: 0;
	}

	.resultado {
		padding: 10px 6px;
		border-bottom: 1px solid var(--border);
	}

	.resultado:last-child {
		border-bottom: none;
	}

	.resultado-titulo {
		font-size: 0.85rem;
		color: var(--text);
		margin-bottom: 2px;
	}

	.resultado-trecho {
		font-size: 0.78rem;
		color: var(--text-dim);
		overflow: hidden;
		text-overflow: ellipsis;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
	}
</style>
