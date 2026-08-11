# -*- coding: utf-8 -*-
"""
audio_manager.py — TTS da Lyra
Cadeia (04/08/2026): Gemini TTS nativo (voz neural de verdade, free tier) →
edge-tts Francisca (fallback) → silêncio.

O Gemini TTS (gemini-2.5-flash-preview-tts) é a primeira opção nova viável
desde que todas as alternativas locais foram esgotadas e rejeitadas (ver
memória lyra-voz-tts): é online (permitido — confirmado por Antônio em
23/06/2026 que voz pode ser online), usa a GEMINI_API_KEY que a Lyra já tem,
e as vozes femininas (Leda/Aoede/Kore) são qualitativamente outra classe em
PT-BR comparadas ao edge-tts Francisca ("medíocre, entonação travada").

- CPU only, sem VRAM
- Cache em Sons/cache/ — frases repetidas tocam offline e instantâneo
- Async-safe
"""
import os
import sys
import asyncio
import hashlib
import struct
import subprocess
import threading

# GEMINI_API_KEY vive no .env do Lyra_Ollama (mesmo usado pelo cerebro)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "Lyra_Ollama", ".env"))
except ImportError:
    pass

# ── Importa broadcast_state da UI (tolerante a falha) ────────────────────────
try:
    from Front_end_Lyra.lyra_app import broadcast_state
except ImportError:
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "Front_end_Lyra"))
        from lyra_app import broadcast_state
    except ImportError:
        def broadcast_state(state: str, intensity: float = 0.0):
            pass

# ── Configuração ──────────────────────────────────────────────────────────────
_DIR       = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR  = os.path.join(_DIR, "Sons", "cache")
VOICE      = "pt-BR-FranciscaNeural"   # jovem, suave, neural
SAPI_VOZ   = "Microsoft Maria Desktop"  # fallback offline PT-BR

os.makedirs(CACHE_DIR, exist_ok=True)

# ── Cache de áudio ────────────────────────────────────────────────────────────
# Gemini TTS gera .wav, edge-tts gera .mp3 — o cache guarda os dois; _cache_hit
# devolve o que existir (preferindo o wav do Gemini, que é a voz melhor).
def _cache_path(texto: str, ext: str = "mp3") -> str:
    h = hashlib.md5(texto.strip().lower().encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, f"{h}.{ext}")


def _cache_hit(texto: str) -> str | None:
    for ext in ("wav", "mp3"):
        p = _cache_path(texto, ext)
        if os.path.exists(p) and os.path.getsize(p) > 500:
            return p
    return None


# ── Geração via Gemini TTS (primário) ────────────────────────────────────────
GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"
GEMINI_TTS_VOICE = "Leda"   # feminina, jovem/suave — combina com a identidade
GEMINI_TTS_STYLE = ("Diga de forma natural e calma, voz feminina suave, "
                    "tom técnico e sereno: ")


def _pcm_para_wav(pcm: bytes, path: str, rate: int = 24000):
    """Gemini TTS devolve PCM cru s16le 24kHz mono — embrulha em WAV."""
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE")
        f.write(b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16))
        f.write(b"data" + struct.pack("<I", len(pcm)) + pcm)


def _gerar_gemini_tts_sync(texto: str, path: str) -> bool:
    try:
        from google import genai
        from google.genai import types
        key = os.environ.get("GEMINI_API_KEY", "")
        if not key:
            return False
        client = genai.Client(api_key=key)
        resp = client.models.generate_content(
            model=GEMINI_TTS_MODEL,
            contents=GEMINI_TTS_STYLE + texto,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=GEMINI_TTS_VOICE))),
            ),
        )
        parte = resp.candidates[0].content.parts[0]
        pcm = parte.inline_data.data
        if not pcm or len(pcm) < 2000:
            return False
        _pcm_para_wav(pcm, path)
        return os.path.exists(path) and os.path.getsize(path) > 500
    except Exception as e:
        print(f"[TTS] gemini-tts erro: {e}")
        return False


async def _gerar_gemini_tts(texto: str, path: str) -> bool:
    return await asyncio.get_event_loop().run_in_executor(
        None, _gerar_gemini_tts_sync, texto, path)

# ── Geração via edge-tts ──────────────────────────────────────────────────────
async def _gerar_edge_tts(texto: str, path: str) -> bool:
    try:
        import edge_tts
        communicate = edge_tts.Communicate(texto, VOICE)
        await communicate.save(path)
        return os.path.exists(path) and os.path.getsize(path) > 500
    except Exception as e:
        print(f"[TTS] edge-tts erro: {e}")
        return False

# ── Reprodução de MP3 via playsound ───────────────────────────────────────────
def _tocar_mp3(path: str) -> bool:
    try:
        from playsound import playsound
        playsound(path, block=True)
        return True
    except Exception as e:
        print(f"[TTS] playsound erro: {e}")
        return False

# ── Removido: Fallback SAPI Maria (Voz de Robô) ──────────────────────────────

# ── Interface pública ─────────────────────────────────────────────────────────
async def falar(texto: str):
    """Versão assíncrona — usar no event loop do FastAPI/WebSocket."""
    if not texto or not texto.strip():
        return

    _broadcast("speaking", 0.8)
    try:
        cache = _cache_hit(texto)

        # Gera áudio se não estiver em cache: Gemini TTS → edge-tts → silêncio
        if cache is None:
            wav = _cache_path(texto, "wav")
            if await _gerar_gemini_tts(texto, wav):
                cache = wav
            else:
                mp3 = _cache_path(texto, "mp3")
                if await _gerar_edge_tts(texto, mp3):
                    cache = mp3
                else:
                    return  # Falhou tudo, fica em silêncio (sem SAPI)

        # Toca (em executor pra não bloquear o loop)
        await asyncio.get_event_loop().run_in_executor(None, _tocar_mp3, cache)
    finally:
        _broadcast("idle", 0.0)

def falar_sync(texto: str):
    """Versão síncrona — usar em threads ou scripts."""
    if not texto or not texto.strip():
        return

    _broadcast("speaking", 0.8)
    try:
        cache = _cache_hit(texto)

        if cache is None:
            wav = _cache_path(texto, "wav")
            if _gerar_gemini_tts_sync(texto, wav):
                cache = wav
            else:
                mp3 = _cache_path(texto, "mp3")
                # Roda o async dentro de uma nova thread com seu próprio loop
                if _run_async(_gerar_edge_tts(texto, mp3)):
                    cache = mp3
                else:
                    return

        _tocar_mp3(cache)
    finally:
        _broadcast("idle", 0.0)

# ── Helpers ───────────────────────────────────────────────────────────────────
def _broadcast(state: str, intensity: float):
    try:
        if asyncio.iscoroutinefunction(broadcast_state):
            pass  # caller deve fazer await
        else:
            broadcast_state(state, intensity)
    except Exception:
        pass

def _run_async(coro):
    """Roda uma coroutine de forma síncrona (thread própria com novo loop)."""
    result = [None]
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result[0] = loop.run_until_complete(coro)
        finally:
            loop.close()
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=15)
    return result[0]

# ── Pré-cache de frases fixas ─────────────────────────────────────────────────
FRASES_FIXAS = [
    "Olá! Estou aqui.",
    "Pode falar.",
    "Entendido.",
    "Um momento.",
    "Pronto.",
    "Não entendi, pode repetir?",
    "Estou processando sua solicitação.",
]

async def pre_cachear():
    """Pré-gera áudio das frases fixas. Chamar na inicialização da Lyra."""
    print("[TTS] Pré-cacheando frases fixas...")
    for frase in FRASES_FIXAS:
        if _cache_hit(frase):
            print(f"  [cache] {frase[:50]}")
            continue
        wav = _cache_path(frase, "wav")
        if await _gerar_gemini_tts(frase, wav):
            print(f"  [OK gemini] {frase[:50]}")
            continue
        mp3 = _cache_path(frase, "mp3")
        ok = await _gerar_edge_tts(frase, mp3)
        print(f"  [{'OK edge' if ok else 'FALHOU'}] {frase[:50]}")
    print("[TTS] Pré-cache concluído.")

# ── Teste rápido ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    async def _teste():
        print(f"Voz: {VOICE}")
        print(f"Cache: {CACHE_DIR}")
        print("Gerando e tocando...")
        await falar("Olá, eu sou a Lyra. Sua assistente pessoal. Pronta para ajudar.")
        print("Teste concluído.")

    asyncio.run(_teste())
