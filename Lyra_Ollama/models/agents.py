"""
models/agents.py — schemas Pydantic dos endpoints de enxame/agente/shadow thoughts.
Extraído de cerebro_maestro.py (reorganização OOP, Lyra 2.0).
"""
from pydantic import BaseModel


class EnxameRequest(BaseModel):
    objetivo:     str
    subtarefas:   list[str]
    max_paralelo: int = 3


class AgenteRequest(BaseModel):
    objetivo:      str
    max_iteracoes: int = 10


class ShadowRequest(BaseModel):
    fases: str = "nrem,rem,deep"  # fases separadas por vírgula
