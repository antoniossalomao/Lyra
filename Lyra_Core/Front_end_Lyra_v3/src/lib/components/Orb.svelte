<script lang="ts">
	// Orb — esfera de identidade visual da Lyra. Canvas 2D leve (decisão já
	// tomada antes desta sessão, ver memória lyra_frontend_v2_plano): pontos
	// numa esfera de Fibonacci, rotação simples, sem WebGL/física contínua.
	// v2 do desenho (a v1 só com pontos soltos não lia como esfera — feedback
	// do usuário): liga cada ponto aos vizinhos mais próximos com linhas finas
	// ("constelação"), o que dá a forma 3D de verdade, e a cor esmaece pro
	// fundo com a profundidade em vez de só ficar transparente.
	import { settings } from '$lib/settings.svelte';

	let { size = 40, variant = 'inline' }: { size?: number; variant?: 'inline' | 'centerpiece' } =
		$props();

	let canvas: HTMLCanvasElement | undefined = $state();
	let rodando = false;

	const N_PONTOS = 64;
	const VIZINHOS_POR_PONTO = 3;

	function pontosFibonacci(n: number): [number, number, number][] {
		const pontos: [number, number, number][] = [];
		const golden = Math.PI * (3 - Math.sqrt(5)); // ângulo áureo
		for (let i = 0; i < n; i++) {
			const y = 1 - (i / (n - 1)) * 2; // de 1 a -1
			const raio = Math.sqrt(1 - y * y);
			const theta = golden * i;
			pontos.push([Math.cos(theta) * raio, y, Math.sin(theta) * raio]);
		}
		return pontos;
	}

	const pontos = pontosFibonacci(N_PONTOS);

	// Arestas pra cada ponto → seus N vizinhos mais próximos (por produto
	// escalar, maior = mais perto numa esfera unitária). Calculado 1x sobre
	// as posições fixas (não rotacionadas) — a rotação só afeta a projeção.
	function calcularArestas(): [number, number][] {
		const arestas = new Set<string>();
		for (let i = 0; i < pontos.length; i++) {
			const distancias: { j: number; dot: number }[] = [];
			for (let j = 0; j < pontos.length; j++) {
				if (i === j) continue;
				const [ax, ay, az] = pontos[i];
				const [bx, by, bz] = pontos[j];
				distancias.push({ j, dot: ax * bx + ay * by + az * bz });
			}
			distancias.sort((a, b) => b.dot - a.dot);
			for (const { j } of distancias.slice(0, VIZINHOS_POR_PONTO)) {
				const chave = i < j ? `${i}-${j}` : `${j}-${i}`;
				arestas.add(chave);
			}
		}
		return [...arestas].map((k) => k.split('-').map(Number) as [number, number]);
	}

	const arestas = calcularArestas();

	function corToken(nome: string, fallback: string): string {
		if (typeof getComputedStyle === 'undefined') return fallback;
		return getComputedStyle(document.documentElement).getPropertyValue(nome).trim() || fallback;
	}

	function hexParaRgb(hex: string): [number, number, number] {
		const m = hex.replace('#', '');
		const n = parseInt(m.length === 3 ? m.split('').map((c) => c + c).join('') : m, 16);
		return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
	}

	function misturar(a: [number, number, number], b: [number, number, number], t: number) {
		return `rgb(${a[0] + (b[0] - a[0]) * t}, ${a[1] + (b[1] - a[1]) * t}, ${a[2] + (b[2] - a[2]) * t})`;
	}

	function desenhar(anguloY: number, anguloX: number) {
		if (!canvas) return;
		const ctx = canvas.getContext('2d');
		if (!ctx) return;
		const dpr = window.devicePixelRatio || 1;
		const w = size;
		const h = size;
		canvas.width = w * dpr;
		canvas.height = h * dpr;
		ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		ctx.clearRect(0, 0, w, h);

		const cx = w / 2;
		const cy = h / 2;
		const raioEsfera = w * 0.36;
		const accentHex = corToken('--accent', '#4fc3d9');
		const bgHex = corToken('--bg', '#0b0b0d');
		const accentRgb = hexParaRgb(accentHex);
		const bgRgb = hexParaRgb(bgHex);

		if (variant === 'centerpiece') {
			const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, w * 0.55);
			glow.addColorStop(0, accentHex + '2a');
			glow.addColorStop(1, accentHex + '00');
			ctx.fillStyle = glow;
			ctx.fillRect(0, 0, w, h);
		}

		const cosY = Math.cos(anguloY);
		const sinY = Math.sin(anguloY);
		const cosX = Math.cos(anguloX);
		const sinX = Math.sin(anguloX);

		const projetados = pontos.map(([x, y, z]) => {
			const x1 = x * cosY - z * sinY;
			const z1 = x * sinY + z * cosY;
			const y1 = y * cosX - z1 * sinX;
			const z2 = y * sinX + z1 * cosX;
			return { x: x1, y: y1, z: z2 };
		});

		const escalaDe = (z: number) => (z + 1) / 2; // 0 (fundo) .. 1 (frente)

		// Linhas primeiro (sempre atrás dos pontos), esmaecendo com a
		// profundidade média dos dois extremos — vizinhos do lado escondido
		// da esfera quase somem, reforçando a sensação de volume 3D.
		for (const [i, j] of arestas) {
			const a = projetados[i];
			const b = projetados[j];
			const prof = (escalaDe(a.z) + escalaDe(b.z)) / 2;
			ctx.strokeStyle = misturar(bgRgb, accentRgb, 0.15 + prof * 0.45);
			ctx.globalAlpha = 0.15 + prof * 0.35;
			ctx.lineWidth = 0.6;
			ctx.beginPath();
			ctx.moveTo(cx + a.x * raioEsfera, cy + a.y * raioEsfera);
			ctx.lineTo(cx + b.x * raioEsfera, cy + b.y * raioEsfera);
			ctx.stroke();
		}

		const ordemDesenho = projetados
			.map((p, idx) => ({ ...p, idx }))
			.sort((a, b) => a.z - b.z);

		for (const p of ordemDesenho) {
			const prof = escalaDe(p.z);
			const px = cx + p.x * raioEsfera;
			const py = cy + p.y * raioEsfera;
			const raioPonto = Math.max(0.5, 0.4 + prof * (w * 0.028));
			ctx.globalAlpha = 0.35 + prof * 0.65;
			ctx.fillStyle = misturar(bgRgb, accentRgb, 0.35 + prof * 0.65);
			ctx.beginPath();
			ctx.arc(px, py, raioPonto, 0, Math.PI * 2);
			ctx.fill();
		}
		ctx.globalAlpha = 1;
	}

	$effect(() => {
		rodando = true;
		let anguloY = 0;
		const anguloX = 0.35; // inclinação fixa, só Y gira

		if (settings.reduzirMovimento) {
			desenhar(anguloY, anguloX);
			return () => (rodando = false);
		}

		let ultimo = performance.now();
		function loop(agora: number) {
			if (!rodando) return;
			const dt = (agora - ultimo) / 1000;
			ultimo = agora;
			anguloY += dt * 0.3; // rotação lenta
			desenhar(anguloY, anguloX);
			requestAnimationFrame(loop);
		}
		requestAnimationFrame(loop);

		return () => (rodando = false);
	});
</script>

<canvas bind:this={canvas} style="width: {size}px; height: {size}px;" aria-hidden="true"></canvas>

<style>
	canvas {
		display: block;
		flex-shrink: 0;
	}
</style>
