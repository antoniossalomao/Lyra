"""
models/sessions.py — schemas Pydantic dos endpoints de sessão de conversa.
Extraído de cerebro_maestro.py (reorganização OOP, Lyra 2.0).
"""
from pydantic import BaseModel


class SessaoAtivar(BaseModel):
    sessao_id: str


class SessaoRenomear(BaseModel):
    titulo: str


class SessaoFavoritar(BaseModel):
    favorita: bool
