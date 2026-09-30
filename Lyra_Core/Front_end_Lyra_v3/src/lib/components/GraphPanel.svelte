<script lang="ts">
	// GraphPanel — visualização do grafo de memória (LYRA_NUCLEO.md §5.4,
	// paridade v1/v2, "grafo 3D"). Implementado em 2D com Canvas nativo em vez
	// da lib 3d-force-graph do frontend antigo — mesma decisão já tomada pro
	// componente "esfera" (ver memória lyra_frontend_v2_plano: canvas 2D leve,
	// sem WebGL) aplicada aqui: sem dependência nova, simulação de força
	// escrita à mão (~80 linhas), leve o bastante pra algumas centenas de nós.
	import { onDestroy } from 'svelte';

	let { fechar }: { fechar: () => void } = $props();

	interface No {
		id: string;
		label: string;
		tipo: string;
		x: number;
		y: number;
		vx: number;
		vy: number;
	}
	interface Link {
		source: string;
		target: string;
	}

	let canvas: HTMLCanvasElement | undefined = $state();
	let carregando = $state(true);
	let erro = $state('');
	let noSelecionado = $state<No | null>(null);

	let nos: No[] = [];
	let links: Link[] = [];
	let animando = false;

	// Decaimento de "alpha" (padrão de todo layout de força — d3-force faz
	// igual): sem isso a simulação nunca esfria e fica tremendo pra sempre a
	// ~60fps, mesmo já estabilizada — foi exatamente o bug relatado pelo
	// usuário ("girando e tremendo tudo"). alpha começa em 1 e decai a cada
	// passo; quando fica baixo o suficiente o movimento vira imperceptível e
	// o loop para de vez (nem desenha mais) — layout final fica parado.
	let alpha = 1;
	const ALPHA_DECAY = 0.985;
	const ALPHA_MIN = 0.01;
	const VELOCIDADE_MAX = 8; // clamp por frame — evita "explosão" quando 2 nós ficam muito perto

	async function carregar() {
		try {
			const resp = await fetch('/grafo/completo?limite=200', { credentials: 'include' });
			const dados = await resp.json();
			if (dados.erro) throw new Error(dados.erro);

			const largura = canvas?.width ?? 600;
			const altura = canvas?.height ?? 400;
			nos = dados.nodes.map((n: { id: string; label: string; tipo: string }) => ({
				...n,
				x: largura / 2 + (Math.random() - 0.5) * 100,
				y: altura / 2 + (Math.random() - 0.5) * 100,
				vx: 0,
				vy: 0
			}));
			links = dados.links;
			carregando = false;
			iniciarSimulacao();
		} catch (e) {
			erro = e instanceof Error ? e.message : 'Falha ao carregar grafo.';
			carregando = false;
		}
	}

	// Simulação de força ingênua: nós se repelem entre si (Coulomb simplificado),
	// links puxam pra distância alvo (Hooke simplificado), damping evita explosão.
	function passoSimulacao() {
		const REPULSAO = 800;
		const DISTANCIA_LINK = 60;
		const RIGIDEZ_LINK = 0.02;
		const DAMPING = 0.85;
		const CENTRO = 0.01;

		for (const a of nos) {
			let fx = 0;
			let fy = 0;
			for (const b of nos) {
				if (a === b) continue;
				let dx = a.x - b.x;
				let dy = a.y - b.y;
				// Nós exatamente sobrepostos (dx=dy=0) têm vetor de direção nulo —
				// a magnitude da repulsão existe mas nunca é aplicada em direção
				// nenhuma, os dois ficam presos um em cima do outro pra sempre.
				// Nudge precisa ser ANTISSIMÉTRICO (sinal oposto pro par a→b vs
				// b→a) — um nudge igual pros dois lados os empurra JUNTOS na
				// mesma direção em vez de se separarem (bug pego pelo self-check).
				if (dx === 0 && dy === 0) {
					const sinal = a.id < b.id ? 1 : -1;
					dx = 0.01 * sinal;
					dy = 0.01 * sinal;
				}
				const distSq = Math.max(dx * dx + dy * dy, 1);
				const f = REPULSAO / distSq;
				fx += (dx / Math.sqrt(distSq)) * f;
				fy += (dy / Math.sqrt(distSq)) * f;
			}
			// puxa levemente pro centro pra não deriva o grafo pra fora da tela
			fx += (300 - a.x) * CENTRO;
			fy += (200 - a.y) * CENTRO;
			a.vx = (a.vx + fx) * DAMPING;
			a.vy = (a.vy + fy) * DAMPING;
		}

		const porId = new Map(nos.map((n) => [n.id, n]));
		for (const l of links) {
			const a = porId.get(l.source);
			const b = porId.get(l.target);
			if (!a || !b) continue;
			const dx = b.x - a.x;
			const dy = b.y - a.y;
			const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
			const forca = (dist - DISTANCIA_LINK) * RIGIDEZ_LINK;
			const fx = (dx / dist) * forca;
			const fy = (dy / dist) * forca;
			a.vx += fx;
			a.vy += fy;
			b.vx -= fx;
			b.vy -= fy;
		}

		for (const n of nos) {
			// Clamp de velocidade — sem isso, um par de nós muito próximo (distSq
			// perto do piso de 1) gera força de repulsão gigante num frame só,
			// manda os dois longe, e no frame seguinte a atração dos links puxa
			// de volta com força igual — esse "ping-pong" é o tremor que o
			// usuário via, não instabilidade sutil, era mesmo sem limite.
			const vel = Math.hypot(n.vx, n.vy);
			if (vel > VELOCIDADE_MAX) {
				n.vx = (n.vx / vel) * VELOCIDADE_MAX;
				n.vy = (n.vy / vel) * VELOCIDADE_MAX;
			}
			n.x += n.vx * alpha;
			n.y += n.vy * alpha;
		}

		alpha *= ALPHA_DECAY;
	}

	function desenhar() {
		if (!canvas) return;
		const ctx = canvas.getContext('2d');
		if (!ctx) return;
		const estilo = getComputedStyle(document.documentElement);
		const corBorda = estilo.getPropertyValue('--border').trim() || '#333';
		const corAccent = estilo.getPropertyValue('--accent').trim() || '#4fc3d9';
		const corTexto = estilo.getPropertyValue('--text-dim').trim() || '#888';

		ctx.clearRect(0, 0, canvas.width, canvas.height);

		ctx.strokeStyle = corBorda;
		const porId = new Map(nos.map((n) => [n.id, n]));
		for (const l of links) {
			const a = porId.get(l.source);
			const b = porId.get(l.target);
			if (!a || !b) continue;
			ctx.beginPath();
			ctx.moveTo(a.x, a.y);
			ctx.lineTo(b.x, b.y);
			ctx.stroke();
		}

		for (const n of nos) {
			ctx.fillStyle = n.tipo === 'topico' ? corAccent : corTexto;
			ctx.beginPath();
			ctx.arc(n.x, n.y, n.tipo === 'topico' ? 5 : 3, 0, Math.PI * 2);
			ctx.fill();
		}
	}

	function iniciarSimulacao() {
		animando = true;
		alpha = 1;
		const loop = () => {
			if (!animando) return;
			passoSimulacao();
			desenhar();
			if (alpha < ALPHA_MIN) {
				animando = false; // esfriou — layout final, para de desenhar de vez
				return;
			}
			requestAnimationFrame(loop);
		};
		requestAnimationFrame(loop);
	}

	function aoClicar(e: MouseEvent) {
		if (!canvas) return;
		const rect = canvas.getBoundingClientRect();
		const x = e.clientX - rect.left;
		const y = e.clientY - rect.top;
		noSelecionado =
			nos.find((n) => Math.hypot(n.x - x, n.y - y) < 10) ?? null;
	}

	$effect(() => {
		if (canvas) carregar();
	});

	onDestroy(() => (animando = false));
</script>

<div
	class="fundo"
	onclick={fechar}
	onkeydown={(e) => e.key === 'Escape' && fechar()}
	role="button"
	tabindex="0"
	aria-label="Fechar grafo de memória"
>
	<div class="painel" onclick={(e) => e.stopPropagation()} role="presentation">
		<header>
			<h2>Grafo de memória</h2>
			<button onclick={fechar}>Fechar</button>
		</header>

		{#if erro}
			<p class="erro">{erro}</p>
		{:else if carregando}
			<p class="dim">Carregando...</p>
		{/if}

		<canvas bind:this={canvas} width="600" height="400" onclick={aoClicar}></canvas>

		{#if noSelecionado}
			<p class="detalhe">
				<strong>{noSelecionado.tipo}</strong> — {noSelecionado.label}
			</p>
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

	canvas {
		background: var(--bg);
		border-radius: var(--radius);
		cursor: pointer;
	}

	.dim {
		color: var(--text-dim);
		font-size: 0.85rem;
	}

	.erro {
		color: var(--danger);
		font-size: 0.85rem;
	}

	.detalhe {
		margin: 8px 0 0;
		font-size: 0.8rem;
		color: var(--text-dim);
	}
</style>
