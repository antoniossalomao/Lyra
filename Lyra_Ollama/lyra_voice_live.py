"""
lyra_voice_live.py — Gemini Live API: voz bidirecional em tempo real.

Endpoint: WebSocket ws://127.0.0.1:8000/ws/voice

Fluxo:
  Browser → envia chunks de áudio PCM (16-bit, 16kHz, mono, little-endian)
  Gemini Live ← processa em tempo real, com baixa latência
  Gemini Live → devolve áudio PCM de resposta + transcrição de texto
  Browser ← recebe áudio para tocar + texto para exibir no chat

Protocolo de mensagens:
  Browser → Server (bytes)  : áudio PCM bruto (16-bit, 16kHz, mono)
  Browser → Server (text)   : JSON {"cmd": "start"} ou {"cmd": "stop"}
  Server → Browser (bytes)  : áudio PCM de resposta (24kHz, para tocar)
  Server → Browser (text)   : JSON {"type": "text",  "text": "..."}  — transcrição
  Server → Browser (text)   : JSON {"type": "done"}                   — fim do turno
  Server → Browser (text)   : JSON {"type": "error", "msg": "..."}   — erro

Modelo default: gemini-2.5-flash-native-audio-latest — único modelo com suporte a
bidiGenerateContent disponível para esta API key em 30/06/2026 (confirmado via
GET /v1beta/models — "gemini-2.0-flash-live-001" listado antes não existe mais
pra esta key, causava erro 1008 "model not found for bidiGenerateContent").
"""

import asyncio
import json

from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

GEMINI_LIVE_MODEL = "gemini-2.5-flash-native-audio-latest"

_SYSTEM_VOICE = (
    "[Lyra] IA pessoal do Projeto Lyra. Admin: Antônio. "
    "Hardware: RTX2060S, Ryzen3700X, 64GB. "
    "Personalidade: feminina, clínica, técnica, não-servil. "
    "REGRAS DE VOZ: respostas curtas (máx 2-3 frases), PT-BR, "
    "sem asteriscos, sem markdown, sem listas com bullets."
)


async def voice_session(websocket: WebSocket, gemini_api_key: str) -> None:
    """
    Handler completo de uma sessão de voz via Gemini Live API.
    Chame de dentro de um endpoint @app.websocket("/ws/voice").
    """
    await websocket.accept()

    if not gemini_api_key:
        await websocket.send_text(json.dumps({
            "type": "error", "msg": "GEMINI_API_KEY não configurada."
        }))
        await websocket.close()
        return

    client = genai.Client(api_key=gemini_api_key)

    live_config = types.LiveConnectConfig(
        # Modelos native-audio só aceitam UMA modalidade de resposta (AUDIO ou
        # TEXT, nunca as duas) — "AUDIO"+"TEXT" juntos dá erro 1007. Pra ter
        # texto (transcrição) e voz ao mesmo tempo, response_modalities fica
        # só em AUDIO e a transcrição vem via output_audio_transcription.
        response_modalities=["AUDIO"],
        system_instruction=_SYSTEM_VOICE,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
            )
        ),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )

    try:
        async with client.aio.live.connect(
            model=GEMINI_LIVE_MODEL, config=live_config
        ) as session:

            async def _browser_to_gemini() -> None:
                """Recebe áudio/comandos do browser e encaminha ao Gemini."""
                try:
                    while True:
                        msg = await websocket.receive()
                        if "bytes" in msg and msg["bytes"]:
                            await session.send_realtime_input(
                                audio=types.Blob(
                                    data=msg["bytes"],
                                    mime_type="audio/pcm;rate=16000",
                                )
                            )
                        elif "text" in msg:
                            cmd = json.loads(msg["text"]).get("cmd", "")
                            if cmd == "stop":
                                break
                except (WebSocketDisconnect, Exception):
                    pass

            async def _gemini_to_browser() -> None:
                """Recebe resposta do Gemini e encaminha ao browser."""
                try:
                    async for response in session.receive():
                        sc = response.server_content
                        if sc and sc.model_turn:
                            for part in sc.model_turn.parts:
                                if part.inline_data and part.inline_data.data:
                                    # áudio PCM da resposta
                                    await websocket.send_bytes(part.inline_data.data)
                        if sc and sc.output_transcription and sc.output_transcription.text:
                            # transcrição do áudio de resposta (response_modalities=AUDIO
                            # só, sem TEXT — texto vem por aqui, não em model_turn.parts)
                            await websocket.send_text(
                                json.dumps({"type": "text", "text": sc.output_transcription.text})
                            )
                        if sc and sc.turn_complete:
                            await websocket.send_text(json.dumps({"type": "done"}))
                except (WebSocketDisconnect, Exception):
                    pass

            await asyncio.gather(_browser_to_gemini(), _gemini_to_browser())

    except Exception as e:
        try:
            await websocket.send_text(json.dumps({"type": "error", "msg": str(e)}))
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
