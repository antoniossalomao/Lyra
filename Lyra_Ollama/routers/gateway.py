"""
routers/gateway.py — WebSocket tipado (Lyra 2.0 Fase 3, inspirado no padrão
Gateway do OpenClaw — ver LYRA_NUCLEO.md §5.3).

Camada ADITIVA: não substitui os endpoints REST existentes (removê-los
quebraria o frontend React atual, que consome REST/SSE). Expõe um
subconjunto das MESMAS capacidades por um único socket `/ws/gateway`,
despachando por `action` — o próximo passo natural quando o frontend
SvelteKit (Fase 4) e as cascas desktop (Fase 5) quiserem 1 conexão
persistente em vez de poll REST repetido.

Só ações de LEITURA entraram nesta primeira rodada (status/stats/histórico/
busca) — nada destrutivo (deletar sessão) nem o /chat (ainda dentro de
cerebro_maestro.py, ver LYRA_NUCLEO.md §5.3 pro motivo). Cada handler já
existe nos routers REST; este arquivo só reaproveita os métodos deles via
um dict {action: callable} montado em cerebro_maestro.py — esta classe não
precisa conhecer o resto do sistema, só sabe despachar.
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from models.gateway import GatewayRequest


class GatewayRouter:
    """1 WebSocket (`/ws/gateway`) despachando mensagens `{action, payload}`
    pros handlers registrados em `actions`."""

    def __init__(self, *, actions: dict, log):
        self._actions = actions
        self._log = log

        self.router = APIRouter()
        self.router.add_api_websocket_route("/ws/gateway", self.gateway_ws)

    async def gateway_ws(self, websocket: WebSocket):
        await websocket.accept()
        try:
            while True:
                raw = await websocket.receive_text()
                await self._despachar(websocket, raw)
        except WebSocketDisconnect:
            pass

    async def _despachar(self, websocket: WebSocket, raw: str):
        try:
            req = GatewayRequest.model_validate_json(raw)
        except Exception as e:
            await websocket.send_json({"ok": False, "action": None, "erro": f"payload inválido: {e}"})
            return

        handler = self._actions.get(req.action)
        if handler is None:
            await websocket.send_json({"ok": False, "action": req.action,
                                       "erro": f"ação desconhecida: {req.action}"})
            return

        try:
            resultado = handler(**req.payload)
            if hasattr(resultado, "__await__"):
                resultado = await resultado
            await websocket.send_json({"ok": True, "action": req.action, "data": resultado})
        except Exception as e:
            self._log(f"[GATEWAY] ação '{req.action}' falhou: {e}")
            await websocket.send_json({"ok": False, "action": req.action, "erro": str(e)})
