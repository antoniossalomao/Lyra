"""
routers/misc.py — upload de arquivo e voz bidirecional (WebSocket).

Extraído de cerebro_maestro.py na reorganização OOP (Lyra 2.0). Comportamento
idêntico ao original — só move código de lugar, não muda lógica.
"""
import os
import re
import time

from fastapi import APIRouter, UploadFile, File, WebSocket


class MiscRouter:
    """Agrupa os dois endpoints que não se encaixam em nenhum outro grupo:
    upload de anexo (`/upload`) e o WebSocket de voz bidirecional (`/ws/voice`).

    O contador de sessões de voz ativas (`_voice_live_ativas`, exposto em
    `/integracoes` via `SystemRouter`) continua sendo uma global em
    cerebro_maestro.py — os callbacks `increment_voice_live`/
    `decrement_voice_live` mutam essa global sem esta classe precisar saber
    onde ela mora, mantendo `SystemRouter` funcionando sem mudança.
    """

    def __init__(self, *, pasta_uploads, voice_session, gemini_api_key,
                 increment_voice_live, decrement_voice_live):
        self._pasta_uploads = pasta_uploads
        self._voice_session = voice_session
        self._gemini_api_key = gemini_api_key
        self._increment_voice_live = increment_voice_live
        self._decrement_voice_live = decrement_voice_live

        self.router = APIRouter()
        self.router.add_api_route("/upload", self.upload_arquivo, methods=["POST"])
        self.router.add_api_websocket_route("/ws/voice", self.voice_ws)

    async def upload_arquivo(self, file: UploadFile = File(...)):
        """Recebe imagem/áudio colado ou anexado no chat do frontend. Salva em
        Sons/cache/uploads e devolve o path — o frontend então manda esse path
        numa mensagem de chat normal, e o modelo decide chamar analisar_imagem
        ou transcrever_audio dependendo do tipo de arquivo."""
        nome_seguro = re.sub(r"[^a-zA-Z0-9_.-]", "_", file.filename or "arquivo")
        destino = os.path.join(self._pasta_uploads, f"{int(time.time())}_{nome_seguro}")
        conteudo = await file.read()
        with open(destino, "wb") as f:
            f.write(conteudo)
        return {"ok": True, "path": destino, "nome": nome_seguro, "bytes": len(conteudo)}

    async def voice_ws(self, websocket: WebSocket):
        self._increment_voice_live()
        try:
            await self._voice_session(websocket, self._gemini_api_key)
        finally:
            self._decrement_voice_live()
