"""
models/prompts.py — schemas Pydantic da biblioteca de prompts salvos.
Ver LYRA_NUCLEO.md §5.4 — item novo (auditoria de paridade com Open WebUI,
2026-08-12): prompts reutilizáveis, inseridos no composer com 1 clique.
"""
from pydantic import BaseModel


class PromptCriar(BaseModel):
    titulo: str
    comando: str  # gatilho curto, ex: "resumo" — não usado como slash-command ainda, só label
    conteudo: str


class PromptEditar(BaseModel):
    titulo: str
    comando: str
    conteudo: str
