<script lang="ts">
	// MessageContent — separa texto de blocos de código ```lang ... ``` numa
	// mensagem, e dá preview sandboxado (iframe) pra HTML/SVG. É o "painel de
	// artifacts" da seção 9 item 2 do plano — versão mínima: preview inline
	// por bloco, não um painel lateral separado (LibreChat faz painel lateral;
	// aqui um botão "Preview" abaixo do bloco já resolve o mesmo problema com
	// bem menos código, sem layout novo pra manter).
	let { content }: { content: string } = $props();

	interface Bloco {
		tipo: 'texto' | 'codigo';
		conteudo: string;
		lang?: string;
	}

	function dividirBlocos(texto: string): Bloco[] {
		const blocos: Bloco[] = [];
		const regex = /```(\w*)\n([\s\S]*?)```/g;
		let ultimo = 0;
		let m: RegExpExecArray | null;
		while ((m = regex.exec(texto))) {
			if (m.index > ultimo) blocos.push({ tipo: 'texto', conteudo: texto.slice(ultimo, m.index) });
			blocos.push({ tipo: 'codigo', lang: m[1] || '', conteudo: m[2] });
			ultimo = regex.lastIndex;
		}
		if (ultimo < texto.length) blocos.push({ tipo: 'texto', conteudo: texto.slice(ultimo) });
		return blocos;
	}

	const PREVIEWAVEL = new Set(['html', 'svg']);

	let blocos = $derived(dividirBlocos(content));
	let previewAberto = $state<Record<number, boolean>>({});
</script>

{#each blocos as bloco, i}
	{#if bloco.tipo === 'texto'}
		<span class="texto">{bloco.conteudo}</span>
	{:else}
		<div class="bloco-codigo">
			<div class="cabecalho-codigo">
				<span class="lang">{bloco.lang || 'código'}</span>
				{#if PREVIEWAVEL.has(bloco.lang ?? '')}
					<button onclick={() => (previewAberto[i] = !previewAberto[i])}>
						{previewAberto[i] ? 'Código' : 'Preview'}
					</button>
				{/if}
			</div>
			{#if previewAberto[i]}
				<iframe title="preview" class="preview" sandbox="allow-scripts" srcdoc={bloco.conteudo}></iframe>
			{:else}
				<pre><code>{bloco.conteudo}</code></pre>
			{/if}
		</div>
	{/if}
{/each}

<style>
	.texto {
		white-space: pre-wrap;
	}

	.bloco-codigo {
		margin: 8px 0;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		overflow: hidden;
	}

	.cabecalho-codigo {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 6px 10px;
		background: var(--surface-2);
		font-size: 0.75rem;
		color: var(--text-dim);
	}

	.cabecalho-codigo button {
		background: transparent;
		border: 1px solid var(--border);
		color: var(--accent);
		border-radius: 6px;
		padding: 2px 8px;
		cursor: pointer;
		font-size: 0.7rem;
	}

	pre {
		margin: 0;
		padding: 10px 14px;
		overflow-x: auto;
		font-size: 0.8rem;
	}

	.preview {
		width: 100%;
		height: 300px;
		border: none;
		background: white;
	}
</style>
