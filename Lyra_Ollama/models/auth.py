"""
models/auth.py — schemas Pydantic dos endpoints de autenticação.
Ver PLANEJAMENTO_LYRA2.0.md seção 5 (proteção de acesso mínima, single-user).
"""
from pydantic import BaseModel


class UserSetup(BaseModel):
    """Corpo de POST /auth/setup — criação da conta admin no primeiro boot."""
    username: str
    senha: str


class UserLogin(BaseModel):
    """Corpo de POST /auth/login."""
    username: str
    senha: str
