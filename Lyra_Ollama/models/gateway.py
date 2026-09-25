"""
models/gateway.py — envelope de mensagem do WebSocket tipado (Fase 3).
"""
from typing import Any

from pydantic import BaseModel


class GatewayRequest(BaseModel):
    """Toda mensagem recebida em /ws/gateway tem essa forma:
    {"action": "status", "payload": {}}"""
    action: str
    payload: dict[str, Any] = {}
