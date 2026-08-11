"""tools/numbers.py — 'Numbers' system: score-weighted observations for proactive (non-interrupting) notification."""

import json
from datetime import datetime

from ._shared import surreal_query, one

def registrar_numero(alvo: str, score: float, motivo: str, fonte: str = "lyra") -> dict:
    """
    Sistema de Números — inspirado na Máquina de Person of Interest: registra
    uma observação com um score de relevância/urgência (0.0 a 1.0) em vez de
    interromper o usuário na hora. O loop proativo de cerebro_maestro.py decide
    quando um número cruza o limiar e merece notificar_usuario.
    """
    try:
        score = max(0.0, min(1.0, float(score)))
        payload = {
            "alvo": alvo, "score": score, "motivo": motivo, "fonte": fonte,
            "criado": datetime.now().isoformat(), "notificado": False,
        }
        r = surreal_query(f"CREATE numero CONTENT {json.dumps(payload, ensure_ascii=False)}")
        return {"ok": True, "numero": one(r)}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def listar_numeros(somente_pendentes: bool = True, limite_score: float = 0.7) -> dict:
    """Lista os 'números' registrados. Por padrão só os ainda não notificados
    com score acima do limiar de relevância."""
    try:
        if somente_pendentes:
            r = surreal_query(
                f"SELECT * FROM numero WHERE notificado = false AND score >= {float(limite_score)} ORDER BY score DESC")
        else:
            r = surreal_query("SELECT * FROM numero ORDER BY criado DESC LIMIT 50")
        return {"ok": True, "total": len(r), "numeros": r}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def _marcar_numero_notificado(numero_id: str) -> None:
    """Uso interno do loop proativo (cerebro_maestro.py) — não exposta ao LLM."""
    surreal_query(f"UPDATE {numero_id} SET notificado = true")


SCHEMA = [
        {
            "type": "function",
            "function": {
                "name": "registrar_numero",
                "description": "Registra uma observação com score de relevância/urgência (0 a 1), pra avaliação proativa posterior em vez de interromper o usuário na hora.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "alvo":   {"type": "string", "description": "Pessoa, evento ou assunto observado."},
                        "score":  {"type": "number", "description": "0.0 a 1.0 — quão urgente/relevante é."},
                        "motivo": {"type": "string"},
                        "fonte":  {"type": "string"},
                    },
                    "required": ["alvo", "score", "motivo"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "listar_numeros",
                "description": "Lista observações registradas pelo Sistema de Números.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "somente_pendentes": {"type": "boolean"},
                        "limite_score":      {"type": "number"},
                    },
                },
            },
        },
]


MAP = {
    "registrar_numero": registrar_numero,
    "listar_numeros": listar_numeros,
}
