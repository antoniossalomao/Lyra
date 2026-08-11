"""
mic_engine.py — Motor de Microfone da Lyra
==========================================
Ring 0: 100% offline. Zero cloud. Zero telemetria.

Fluxo:
  1. Captura áudio do microfone via sounddevice
  2. VAD via Silero VAD (modelo) — detecta fala robusto a ruído de fundo
  3. Wake word "lyra" (match por palavra inteira, com tolerância a erro de transcrição) — ativa o modo escuta estendida
  4. Transcrição via faster-whisper (Whisper local na GPU/CPU)
  5. Broadcast do estado para UI via WebSocket ws://localhost:8765
  6. POST da transcrição para o backend em http://localhost:8000/chat

Instalação:
    pip install faster-whisper sounddevice numpy websockets httpx torch silero-vad
"""

import asyncio
import difflib
import json
import os
import queue
import sys
import threading
import time
from typing import Optional

# Evita WinError 1314 ("privilégio necessário não detido") ao carregar modelos
# do cache do huggingface_hub nesta máquina, que não tem Modo de Desenvolvedor
# habilitado nem roda como admin — sem isso, o cache tenta criar symlinks entre
# blobs/ e snapshots/ e falha. Precisa ser definido antes de qualquer import
# que toque o cache (faster_whisper -> huggingface_hub).
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from commands import despachar  # despachante de comandos locais (Spotify, volume, etc.)

import httpx
import numpy as np
import sounddevice as sd
import torch
import websockets
from silero_vad import load_silero_vad

# ── Configurações ────────────────────────────────────────────────────────────
WHISPER_RATE      = 16000          # Whisper exige 16kHz — não altere
CAPTURE_RATE      = 48000          # Taxa nativa do NVIDIA Broadcast (e maioria dos WASAPI)
                                   # Se usar outro microfone que suporte 16kHz, mude para 16000
CHANNELS          = 1
DTYPE             = "float32"
BLOCK_DURATION    = 0.03           # 30ms por bloco (VAD responsivo)
BLOCK_SIZE        = int(CAPTURE_RATE * BLOCK_DURATION)  # baseado na taxa de captura
SAMPLE_RATE       = CAPTURE_RATE   # alias para o InputStream

# VAD trocado de RMS por energia para Silero VAD (modelo, muito mais robusto a
# ruído de fundo). Silero exige janelas de exatamente 512 amostras a 16kHz (32ms).
VAD_WINDOW        = 512
VAD_PROB_THRESHOLD = 0.5           # probabilidade de fala (saída do Silero), 0.5 é o padrão recomendado
SILENCE_TIMEOUT   = 1.0            # segundos de silêncio para encerrar captura (reduzido de 2.0 — era a maior fonte de latência percebida)
MAX_RECORD_SEC    = 30             # limite por segurança (não grava para sempre)
PRE_BUFFER_SEC    = 0.5            # guarda meio segundo antes do gatilho VAD
MIN_SPEECH_SEC    = 0.8            # descarta áudio menor que isso (ruído/falso positivo)

# Whisper frequentemente transcreve "Lyra" de formas diferentes
# Todas as variantes abaixo ativam o modo escuta
WAKE_WORDS        = {"lyra", "lira", "leia", "lê", "lhyra", "lyre", "liara", "lya"}
WAKE_WORD_TIMEOUT = 15.0           # segundos esperando comando após wake word

WHISPER_MODEL     = "small"        # "tiny" | "base" | "small" | "medium" | "large-v3"
# Trocado de "base" pra "small" em 24/06/2026 — "base" errava demais em PT-BR
# (inclusive a própria wake word "lyra"). "small" ainda roda rápido em GPU float16.
WHISPER_DEVICE    = "cuda"
WHISPER_COMPUTE   = "float16"
WHISPER_LANG      = "pt"           # força PT-BR, elimina detecção automática

# Dispositivo de áudio — None = padrão do sistema
# Para ver dispositivos disponíveis: python -c "import sounddevice as sd; print(sd.query_devices())"
# Para selecionar: coloque o índice do microfone correto (ex: AUDIO_DEVICE = 2)
AUDIO_DEVICE      = 2             # NVIDIA Broadcast WASAPI — melhor qualidade, cancela ruído

WS_URL            = "ws://127.0.0.1:8765"  # 127.0.0.1: evita delay ~2s do IPv6 do localhost
BACKEND_URL       = "http://127.0.0.1:8000/chat"  # 127.0.0.1: evita delay ~2s do IPv6 do localhost

# ── Estado global ─────────────────────────────────────────────────────────────
_audio_queue: queue.Queue = queue.Queue()
_ws_connection: Optional[websockets.WebSocketClientProtocol] = None
_ws_lock = threading.Lock()
_loop: Optional[asyncio.AbstractEventLoop] = None


# ── WebSocket: broadcast para a UI ───────────────────────────────────────────
async def _ws_connect():
    """Mantém conexão persistente ao servidor WS da Lyra."""
    global _ws_connection
    while True:
        try:
            async with websockets.connect(WS_URL) as ws:
                _ws_connection = ws
                print(f"[MIC] WebSocket conectado em {WS_URL}")
                await ws.wait_closed()
        except Exception as e:
            print(f"[MIC] WS desconectado ({e}), reconectando em 3s...")
        finally:
            _ws_connection = None
        await asyncio.sleep(3)


def broadcast(state: str, intensity: float = 0.0):
    """Thread-safe: envia estado para a UI via WebSocket."""
    broadcast_raw({"state": state, "intensity": round(float(intensity), 4)})


def broadcast_raw(data: dict):
    """Thread-safe: envia payload JSON arbitrário para a UI via WebSocket."""
    global _ws_connection, _loop
    if _ws_connection is None or _loop is None:
        return
    payload = json.dumps(data)

    async def _send():
        try:
            await _ws_connection.send(payload)
        except Exception:
            pass

    asyncio.run_coroutine_threadsafe(_send(), _loop)


# ── Callback do sounddevice (thread de áudio) ─────────────────────────────────
def _audio_callback(indata: np.ndarray, frames: int, time_info, status):
    if status:
        print(f"[MIC][WARN] {status}")
    _audio_queue.put(indata.copy().flatten())


# ── Resampling (CAPTURE_RATE → WHISPER_RATE) ─────────────────────────────────
def _resample(audio: np.ndarray) -> np.ndarray:
    """Converte áudio de CAPTURE_RATE para WHISPER_RATE via interpolação linear."""
    if CAPTURE_RATE == WHISPER_RATE:
        return audio
    n_amostras = int(len(audio) * WHISPER_RATE / CAPTURE_RATE)
    indices = np.linspace(0, len(audio) - 1, n_amostras)
    return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)


# ── VAD + Captura ─────────────────────────────────────────────────────────────
def capturar_fala(vad_model) -> Optional[np.ndarray]:
    """
    Bloqueia até capturar um segmento de fala completo, usando Silero VAD
    (substituiu o VAD por energia RMS — muito mais robusto a ruído de fundo).
    Retorna array float32 a 16kHz, ou None se não houver fala válida.
    """
    pre_buffer_amostras = int(PRE_BUFFER_SEC * WHISPER_RATE)
    silencio_limite_amostras = int(SILENCE_TIMEOUT * WHISPER_RATE)
    max_amostras = int(MAX_RECORD_SEC * WHISPER_RATE)
    min_amostras = int(MIN_SPEECH_SEC * WHISPER_RATE)

    pre_buffer = np.zeros(0, dtype=np.float32)
    leftover = np.zeros(0, dtype=np.float32)   # resto não múltiplo de VAD_WINDOW entre callbacks
    segmento = np.zeros(0, dtype=np.float32)
    gravando = False
    amostras_silencio = 0

    while True:
        try:
            bloco = _audio_queue.get(timeout=1.0)
        except queue.Empty:
            continue

        leftover = np.concatenate([leftover, _resample(bloco)])

        while len(leftover) >= VAD_WINDOW:
            janela = leftover[:VAD_WINDOW]
            leftover = leftover[VAD_WINDOW:]

            with torch.no_grad():
                prob = float(vad_model(torch.from_numpy(janela).unsqueeze(0), WHISPER_RATE).item())
            broadcast_raw({"intensity": round(prob, 4)})
            fala = prob > VAD_PROB_THRESHOLD

            if not gravando:
                pre_buffer = np.concatenate([pre_buffer, janela])[-pre_buffer_amostras:]
                if fala:
                    gravando = True
                    segmento = pre_buffer.copy()  # inclui contexto pré-fala
                    amostras_silencio = 0
                    print("[MIC] Fala detectada — gravando...")
            else:
                segmento = np.concatenate([segmento, janela])
                amostras_silencio = 0 if fala else amostras_silencio + VAD_WINDOW

                if amostras_silencio >= silencio_limite_amostras or len(segmento) >= max_amostras:
                    duracao = len(segmento) / WHISPER_RATE
                    print(f"[MIC] Fala encerrada ({duracao:.1f}s)")
                    broadcast("idle")
                    if len(segmento) < min_amostras:
                        print(f"[MIC] Descartado: muito curto ({duracao:.1f}s < {MIN_SPEECH_SEC}s)")
                        return None
                    return segmento.astype(np.float32)


# ── Wake word por palavra inteira (substituiu o match por substring) ─────────
def _detectar_wake_word(texto_lower: str) -> Optional[str]:
    """
    Verifica se alguma palavra do texto é (ou é bem parecida com) uma wake word.
    Antes usava substring simples (`w in texto_lower`), que disparava falso
    positivo em palavras que só continham a substring por acaso. Agora compara
    palavra a palavra, com tolerância a pequenos erros de transcrição do Whisper.
    """
    palavras = texto_lower.replace(",", " ").replace(".", " ").split()
    for palavra in palavras:
        if palavra in WAKE_WORDS:
            return palavra
        if difflib.get_close_matches(palavra, WAKE_WORDS, n=1, cutoff=0.8):
            return palavra
    return None


# ── Transcrição Whisper ───────────────────────────────────────────────────────
def transcrever(audio: np.ndarray, whisper_model) -> str:
    """Roda faster-whisper no áudio capturado. Retorna texto limpo."""
    segmentos, info = whisper_model.transcribe(
        audio,
        language=WHISPER_LANG,
        beam_size=5,
        vad_filter=True,                   # VAD interno do Whisper (remove silêncio)
        vad_parameters={"min_silence_duration_ms": 500},
    )
    texto = " ".join(seg.text.strip() for seg in segmentos).strip()
    print(f"[MIC] Transcrito: '{texto}' (lang={info.language}, prob={info.language_probability:.2f})")
    return texto


# ── POST para o backend ───────────────────────────────────────────────────────
async def enviar_para_backend(texto: str):
    """Envia transcrição ao cerebro_maestro e imprime a resposta em stream."""
    print(f"[MIC] → backend: '{texto}'")
    broadcast_raw({"user_text": texto})   # frontend mostra bubble do usuário
    broadcast("processing")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("POST", BACKEND_URL, json={"texto": texto}) as resp:
                resp.raise_for_status()
                broadcast("speaking")    # frontend muda estado
                resposta_completa = ""
                async for linha in resp.aiter_lines():
                    if not linha.startswith("data:"):
                        continue
                    dado = linha[5:].strip()
                    if dado == "[DONE]":
                        break
                    try:
                        obj = json.loads(dado)
                        fragmento = obj.get("text", "")
                        if fragmento:
                            resposta_completa += fragmento
                            broadcast_raw({"ai_chunk": fragmento})  # frontend mostra bubble
                            print(fragmento, end="", flush=True)
                    except json.JSONDecodeError:
                        pass
                print()  # nova linha
                return resposta_completa
    except Exception as e:
        print(f"[MIC][ERRO] Falha ao chamar backend: {e}")
        broadcast("idle")
        return ""
    finally:
        broadcast("idle")


# ── Loop principal assíncrono ─────────────────────────────────────────────────
async def _main_loop():
    global _loop
    _loop = asyncio.get_running_loop()

    # Inicia conexão WebSocket em background
    asyncio.create_task(_ws_connect())

    # Carrega modelo Whisper (demora ~5s na primeira vez)
    print(f"[MIC] Carregando faster-whisper '{WHISPER_MODEL}' em {WHISPER_DEVICE}...")
    try:
        from faster_whisper import WhisperModel
        whisper = WhisperModel(
            WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE,
        )
        print("[MIC] Whisper pronto.")
    except Exception as e:
        print(f"[MIC][ERRO CRÍTICO] Falha ao carregar Whisper: {e}")
        return

    print("[MIC] Carregando Silero VAD...")
    vad_model = load_silero_vad()
    print("[MIC] Silero VAD pronto.")

    # Lista dispositivos disponíveis para facilitar seleção
    print("\n[MIC] Dispositivos de áudio disponíveis:")
    for i, dev in enumerate(sd.query_devices()):
        if dev['max_input_channels'] > 0:
            print(f"  [{i}] {dev['name']}")
    print(f"[MIC] Usando dispositivo: {'padrão' if AUDIO_DEVICE is None else AUDIO_DEVICE}")
    print("      → Para trocar: edite AUDIO_DEVICE = <índice> no topo do mic_engine.py\n")

    # Inicia captura de áudio em thread separada
    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
        blocksize=BLOCK_SIZE,
        callback=_audio_callback,
        device=AUDIO_DEVICE,
    )

    modo_ativo = False          # True = aguardando comando após wake word
    deadline_ativo = 0.0

    print(f'[MIC] Escutando... Diga "Lyra" para ativar. Variantes: {WAKE_WORDS}')
    broadcast("idle")

    with stream:
        while True:
            # Captura fala de forma não-bloqueante no loop async
            audio = await asyncio.to_thread(capturar_fala, vad_model)
            if audio is None:
                continue

            # Transcreve
            texto = await asyncio.to_thread(transcrever, audio, whisper)
            if not texto:
                continue

            texto_lower = texto.lower()

            if not modo_ativo:
                # Modo passivo: verifica qualquer variante do wake word
                palavra_detectada = _detectar_wake_word(texto_lower)
                if palavra_detectada:
                    modo_ativo = True
                    deadline_ativo = time.time() + WAKE_WORD_TIMEOUT
                    print(f'[MIC] Wake word detectada ("{palavra_detectada}")! Aguardando comando...')
                    broadcast("listening")

                    # Remove a variante detectada e verifica se há comando junto
                    comando = texto_lower.replace(palavra_detectada, "").strip(" ,.")
                    if len(comando) > 3:
                        modo_ativo = False
                        tratado = await asyncio.to_thread(despachar, comando)
                        if not tratado:
                            await enviar_para_backend(comando)
                else:
                    print(f'[MIC] (passivo) Ignorado: "{texto}"')
            else:
                # Modo ativo: processa qualquer fala como comando
                if time.time() > deadline_ativo:
                    print("[MIC] Timeout do modo ativo. Voltando ao modo passivo.")
                    modo_ativo = False
                    broadcast("idle")
                    continue

                modo_ativo = False
                # Tenta despachar como comando local primeiro
                tratado = await asyncio.to_thread(despachar, texto)
                if not tratado:
                    await enviar_para_backend(texto)


# ── Ponto de entrada ──────────────────────────────────────────────────────────
def main():
    try:
        asyncio.run(_main_loop())
    except KeyboardInterrupt:
        print("\n[MIC] Encerrado pelo usuário.")
        broadcast("idle")


if __name__ == "__main__":
    main()
