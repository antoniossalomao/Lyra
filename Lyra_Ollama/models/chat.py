"""
models/chat.py — schema Pydantic da mensagem de chat.
Extraído de cerebro_maestro.py (reorganização OOP, Lyra 2.0).
"""
from pydantic import BaseModel


class MensagemUsuario(BaseModel):
    texto: str
    modelo: str = "auto"  # "auto" (cascata) | "groq" | "gemini" | "claude" | "local" — seletor manual do painel
