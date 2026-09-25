// voiceLive.ts — cliente do WebSocket /ws/voice (lyra_voice_live.py).
//
// Protocolo (documentado no docstring de lyra_voice_live.py, seguido à risca
// aqui, não é palpite):
//   Browser → Server (bytes) : PCM 16-bit, 16kHz, mono, little-endian
//   Browser → Server (text)  : JSON {"cmd": "start"} / {"cmd": "stop"}
//   Server → Browser (bytes) : PCM 16-bit, 24kHz, mono — pra tocar
//   Server → Browser (text)  : JSON {type: "text"|"done"|"error", ...}
export class VoiceLiveSession {
	private ws: WebSocket | null = null;
	private micContext: AudioContext | null = null;
	private micStream: MediaStream | null = null;
	private processor: ScriptProcessorNode | null = null;
	private playbackContext: AudioContext | null = null;
	private playbackTime = 0;

	onText: (texto: string) => void = () => {};
	onDone: () => void = () => {};
	onError: (msg: string) => void = () => {};
	onStatusChange: (ativo: boolean) => void = () => {};

	async start(): Promise<void> {
		this.micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
		this.micContext = new AudioContext();
		this.playbackContext = new AudioContext({ sampleRate: 24000 });
		this.playbackTime = this.playbackContext.currentTime;

		const proto = location.protocol === 'https:' ? 'wss' : 'ws';
		this.ws = new WebSocket(`${proto}://${location.host}/ws/voice`);
		this.ws.binaryType = 'arraybuffer';

		await new Promise<void>((resolve, reject) => {
			if (!this.ws) return reject(new Error('WebSocket não inicializado'));
			this.ws.onopen = () => resolve();
			this.ws.onerror = () => reject(new Error('Falha ao conectar em /ws/voice'));
		});

		this.ws.send(JSON.stringify({ cmd: 'start' }));
		this.ws.onmessage = (ev) => this.handleMessage(ev);
		this.ws.onclose = () => this.onStatusChange(false);

		this.iniciarCaptura();
		this.onStatusChange(true);
	}

	private iniciarCaptura(): void {
		if (!this.micContext || !this.micStream) return;
		const source = this.micContext.createMediaStreamSource(this.micStream);
		// ponytail: ScriptProcessorNode é deprecated mas universalmente suportado;
		// AudioWorkletNode exigiria um módulo separado carregado via addModule —
		// mais peso pra um MVP. Trocar se o navegador-alvo remover suporte.
		this.processor = this.micContext.createScriptProcessor(4096, 1, 1);
		source.connect(this.processor);
		this.processor.connect(this.micContext.destination);

		const taxaOrigem = this.micContext.sampleRate;
		this.processor.onaudioprocess = (e) => {
			if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
			const entrada = e.inputBuffer.getChannelData(0);
			const pcm16 = this.reamostrarPara16kHz(entrada, taxaOrigem);
			this.ws.send(pcm16.buffer as ArrayBuffer);
		};
	}

	// Reamostragem por nearest-neighbor — simples e barata o bastante pra fala
	// (não é reamostragem de qualidade de áudio musical). Nota-mental: se a
	// transcrição vier ruim, trocar por interpolação linear é o próximo passo.
	private reamostrarPara16kHz(dados: Float32Array, taxaOrigem: number): Int16Array {
		const taxaAlvo = 16000;
		if (taxaOrigem === taxaAlvo) return this.paraInt16(dados);
		const razao = taxaOrigem / taxaAlvo;
		const tamanhoAlvo = Math.floor(dados.length / razao);
		const saida = new Float32Array(tamanhoAlvo);
		for (let i = 0; i < tamanhoAlvo; i++) {
			saida[i] = dados[Math.floor(i * razao)];
		}
		return this.paraInt16(saida);
	}

	private paraInt16(dados: Float32Array): Int16Array {
		const saida = new Int16Array(dados.length);
		for (let i = 0; i < dados.length; i++) {
			saida[i] = Math.max(-32768, Math.min(32767, Math.round(dados[i] * 32768)));
		}
		return saida;
	}

	private handleMessage(ev: MessageEvent): void {
		if (typeof ev.data === 'string') {
			const msg = JSON.parse(ev.data);
			if (msg.type === 'text') this.onText(msg.text);
			else if (msg.type === 'done') this.onDone();
			else if (msg.type === 'error') this.onError(msg.msg);
		} else {
			this.tocarAudio(ev.data as ArrayBuffer);
		}
	}

	private tocarAudio(dados: ArrayBuffer): void {
		if (!this.playbackContext) return;
		const pcm16 = new Int16Array(dados);
		const float32 = new Float32Array(pcm16.length);
		for (let i = 0; i < pcm16.length; i++) float32[i] = pcm16[i] / 32768;

		const buffer = this.playbackContext.createBuffer(1, float32.length, 24000);
		buffer.copyToChannel(float32, 0);

		const source = this.playbackContext.createBufferSource();
		source.buffer = buffer;
		source.connect(this.playbackContext.destination);

		// Agenda em fila (não sobrepõe) — cada chunk começa exatamente onde o
		// anterior termina, ou agora se a fila já esvaziou.
		const agora = this.playbackContext.currentTime;
		const inicio = Math.max(agora, this.playbackTime);
		source.start(inicio);
		this.playbackTime = inicio + buffer.duration;
	}

	stop(): void {
		this.ws?.send(JSON.stringify({ cmd: 'stop' }));
		this.ws?.close();
		this.processor?.disconnect();
		this.micStream?.getTracks().forEach((t) => t.stop());
		this.micContext?.close();
		this.playbackContext?.close();
		this.ws = null;
		this.onStatusChange(false);
	}
}
