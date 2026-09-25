<script lang="ts">
	import favicon from '$lib/assets/favicon.svg';
	import '$lib/styles/tokens.css';
	import { settings } from '$lib/settings.svelte';

	let { children } = $props();

	// Aplica tamanho de fonte e "reduzir movimento" de verdade — antes esses
	// dois só persistiam em localStorage e não afetavam nada visualmente,
	// mesma falha que existia no v2 antes de ele setar --chat-font-size/
	// data-reduce-motion no documentElement.
	const TAMANHOS: Record<string, string> = { pequeno: '0.85rem', medio: '0.92rem', grande: '1.02rem' };

	$effect(() => {
		document.documentElement.style.setProperty('--chat-font-size', TAMANHOS[settings.tamanhoFonte]);
	});

	$effect(() => {
		document.documentElement.dataset.reduceMotion = settings.reduzirMovimento ? '1' : '0';
	});
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

{@render children()}
