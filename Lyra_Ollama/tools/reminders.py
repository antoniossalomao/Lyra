"""tools/reminders.py — Scheduling tools: one-off reminders, recurring cron-like schedules, and a to-do list — all persisted in SurrealDB."""

import json
import re
from datetime import datetime, timedelta
from typing import Any

from ._shared import surreal_query, one

def gerenciar_lembretes(acao: str, titulo: str = "", quando: str = "",
                        lembrete_id: str = "", nota: str = "") -> dict:
    """
    CRUD de lembretes, persistido no SurrealDB (tabela 'lembrete').
    acao: 'criar' | 'listar' | 'pendentes' | 'concluir' | 'remover'
    quando: data/hora ISO, ex: '2026-06-25T14:30:00'.
    'pendentes' retorna só os não concluídos cuja hora já passou — é o que o
    loop proativo do cerebro_maestro.py consulta pra disparar notificar_usuario.
    """
    try:
        if acao == "criar":
            if not titulo or not quando:
                return {"erro": "Para criar, informe 'titulo' e 'quando' (ISO, ex: 2026-06-25T14:30:00)."}
            payload = {
                "titulo": titulo, "quando": quando, "nota": nota,
                "criado": datetime.now().isoformat(), "concluido": False,
            }
            r = surreal_query(f"CREATE lembrete CONTENT {json.dumps(payload, ensure_ascii=False)}")
            return {"ok": True, "lembrete": one(r)}

        elif acao == "listar":
            r = surreal_query("SELECT * FROM lembrete ORDER BY quando ASC")
            return {"ok": True, "total": len(r), "lembretes": r}

        elif acao == "pendentes":
            agora = datetime.now().isoformat()
            r = surreal_query(
                f"SELECT * FROM lembrete WHERE concluido = false AND quando <= '{agora}' ORDER BY quando ASC")
            return {"ok": True, "total": len(r), "lembretes": r}

        elif acao in ("concluir", "remover"):
            if not lembrete_id or not re.fullmatch(r"lembrete:[a-zA-Z0-9_]+", lembrete_id):
                return {"erro": "Informe 'lembrete_id' válido (formato 'lembrete:xxxxx', use a ação 'listar' pra ver os ids)."}
            if acao == "concluir":
                r = surreal_query(f"UPDATE {lembrete_id} SET concluido = true")
                return {"ok": True, "lembrete": one(r)}
            r = surreal_query(f"DELETE {lembrete_id}")
            return {"ok": True, "removido": lembrete_id}

        else:
            return {"erro": f"Ação inválida: {acao}. Use: criar, listar, pendentes, concluir, remover."}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def _proxima_execucao(tipo: str, base: datetime, quando: str = "",
                      horario: str = "", intervalo_min: int = 0) -> str:
    """Calcula o próximo horário de disparo conforme o tipo de agendamento."""
    if tipo == "unico":
        if not quando:
            raise ValueError("tipo 'unico' exige 'quando' (ISO).")
        return quando
    if tipo == "diario":
        if not horario:
            raise ValueError("tipo 'diario' exige 'horario' (HH:MM).")
        h, m = (int(x) for x in horario.split(":"))
        prox = base.replace(hour=h, minute=m, second=0, microsecond=0)
        if prox <= base:
            prox += timedelta(days=1)
        return prox.isoformat()
    if tipo == "intervalo_min":
        if intervalo_min <= 0:
            raise ValueError("tipo 'intervalo_min' exige 'intervalo_min' > 0.")
        return (base + timedelta(minutes=intervalo_min)).isoformat()
    raise ValueError(f"tipo inválido: {tipo}. Use: unico, diario, intervalo_min.")

def gerenciar_agendamentos(acao: str, titulo: str = "", tipo: str = "unico",
                           quando: str = "", horario: str = "", intervalo_min: int = 0,
                           ferramenta: str = "", parametros: str = "{}",
                           agendamento_id: str = "") -> dict:
    """
    Agendamento recorrente (tipo cron), persistido em SurrealDB ('agendamento') —
    diferente de gerenciar_lembretes (que é só um aviso pontual e some depois
    de concluído), aqui o item pode se repetir (diario/intervalo_min) e
    opcionalmente EXECUTAR uma ferramenta existente quando disparar (ex: rodar
    checar_saude_sistema todo dia às 8h e notificar o resultado).
    acao: 'criar' | 'listar' | 'pausar' | 'retomar' | 'remover'
    tipo: 'unico' (usa 'quando' ISO) | 'diario' (usa 'horario' HH:MM) |
          'intervalo_min' (usa 'intervalo_min', em minutos)
    ferramenta: nome de uma função já existente em TOOLS_MAP pra chamar
                automaticamente quando o agendamento disparar (opcional).
    parametros: argumentos da ferramenta, como string JSON, ex: '{"query":"clima SP"}'.
    O loop_proativo (cerebro_maestro.py) é quem efetivamente checa e dispara isso.
    """
    try:
        if acao == "criar":
            if not titulo:
                return {"erro": "Informe 'titulo'."}
            try:
                prox = _proxima_execucao(tipo, datetime.now(), quando, horario, intervalo_min)
            except ValueError as e:
                return {"erro": str(e)}
            payload = {
                "titulo": titulo, "tipo": tipo, "horario": horario,
                "intervalo_min": intervalo_min, "ferramenta": ferramenta,
                "parametros": parametros, "proxima_execucao": prox,
                "ultima_execucao": None, "ativo": True,
                "criado": datetime.now().isoformat(),
            }
            r = surreal_query(f"CREATE agendamento CONTENT {json.dumps(payload, ensure_ascii=False)}")
            return {"ok": True, "agendamento": one(r)}

        elif acao == "listar":
            r = surreal_query("SELECT * FROM agendamento ORDER BY proxima_execucao ASC")
            return {"ok": True, "total": len(r), "agendamentos": r}

        elif acao in ("pausar", "retomar", "remover"):
            if not agendamento_id or not re.fullmatch(r"agendamento:[a-zA-Z0-9_]+", agendamento_id):
                return {"erro": "Informe 'agendamento_id' válido (formato 'agendamento:xxxxx', use 'listar' pra ver os ids)."}
            if acao == "pausar":
                r = surreal_query(f"UPDATE {agendamento_id} SET ativo = false")
                return {"ok": True, "agendamento": one(r)}
            if acao == "retomar":
                r = surreal_query(f"UPDATE {agendamento_id} SET ativo = true")
                return {"ok": True, "agendamento": one(r)}
            r = surreal_query(f"DELETE {agendamento_id}")
            return {"ok": True, "removido": agendamento_id}

        else:
            return {"erro": f"Ação inválida: {acao}. Use: criar, listar, pausar, retomar, remover."}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def _processar_agendamentos_devidos() -> list[dict]:
    """Uso interno do loop proativo — busca agendamentos vencidos, executa a
    ferramenta vinculada (se houver) e recalcula a próxima execução. Retorna
    a lista de itens disparados (pra quem chamou decidir como notificar)."""
    agora = datetime.now()
    devidos = surreal_query(
        f"SELECT * FROM agendamento WHERE ativo = true AND proxima_execucao <= '{agora.isoformat()}'")
    disparados = []
    for ag in devidos:
        resultado_ferramenta = None
        if ag.get("ferramenta"):
            from . import TOOLS_MAP
            fn = TOOLS_MAP.get(ag["ferramenta"])
            if fn:
                try:
                    params = json.loads(ag.get("parametros") or "{}")
                    resultado_ferramenta = fn(**params)
                except Exception as e:
                    resultado_ferramenta = {"erro": str(e)}
        disparados.append({"agendamento": ag, "resultado_ferramenta": resultado_ferramenta})

        if ag.get("tipo") == "unico":
            surreal_query(f"UPDATE {ag['id']} SET ativo = false, ultima_execucao = '{agora.isoformat()}'")
        else:
            prox = _proxima_execucao(ag["tipo"], agora, horario=ag.get("horario", ""),
                                     intervalo_min=ag.get("intervalo_min", 0))
            surreal_query(
                f"UPDATE {ag['id']} SET ultima_execucao = '{agora.isoformat()}', proxima_execucao = '{prox}'")
    return disparados

def gerenciar_tarefas(acao: str, titulo: str = "", tarefa_id: str = "",
                      status: str = "pendente") -> dict:
    """
    Lista de tarefas estruturada (to-do), pra pedidos do usuário com várias
    etapas — diferente de gerenciar_lembretes (que tem hora marcada) e do
    Sistema de Números (observações por relevância), isso é progresso de
    trabalho em andamento que pode ser mostrado a qualquer momento.
    acao: 'criar' | 'listar' | 'atualizar' | 'remover'
    status: 'pendente' | 'em_andamento' | 'concluida'
    """
    try:
        if acao == "criar":
            if not titulo:
                return {"erro": "Informe 'titulo'."}
            payload = {"titulo": titulo, "status": "pendente", "criado": datetime.now().isoformat()}
            r = surreal_query(f"CREATE tarefa CONTENT {json.dumps(payload, ensure_ascii=False)}")
            return {"ok": True, "tarefa": one(r)}

        elif acao == "listar":
            r = surreal_query("SELECT * FROM tarefa ORDER BY criado ASC")
            return {"ok": True, "total": len(r), "tarefas": r}

        elif acao in ("atualizar", "remover"):
            if not tarefa_id or not re.fullmatch(r"tarefa:[a-zA-Z0-9_]+", tarefa_id):
                return {"erro": "Informe 'tarefa_id' válido (formato 'tarefa:xxxxx', use 'listar' pra ver os ids)."}
            if acao == "atualizar":
                if status not in ("pendente", "em_andamento", "concluida"):
                    return {"erro": "status inválido. Use: pendente, em_andamento, concluida."}
                r = surreal_query(f"UPDATE {tarefa_id} SET status = '{status}'")
                return {"ok": True, "tarefa": one(r)}
            r = surreal_query(f"DELETE {tarefa_id}")
            return {"ok": True, "removido": tarefa_id}

        else:
            return {"erro": f"Ação inválida: {acao}. Use: criar, listar, atualizar, remover."}
    except Exception as e:
        return {"erro": str(e), "ok": False}


SCHEMA = [
        {
            "type": "function",
            "function": {
                "name": "gerenciar_lembretes",
                "description": "Cria, lista, conclui ou remove lembretes com data/hora.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "acao":        {"type": "string", "enum": ["criar", "listar", "pendentes", "concluir", "remover"]},
                        "titulo":      {"type": "string"},
                        "quando":      {"type": "string", "description": "Data/hora ISO, ex: 2026-06-25T14:30:00"},
                        "lembrete_id": {"type": "string"},
                        "nota":        {"type": "string"},
                    },
                    "required": ["acao"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "gerenciar_agendamentos",
                "description": "Cria/lista/pausa/remove agendamentos recorrentes (cron), opcionalmente executando outra ferramenta automaticamente quando disparar.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "acao":           {"type": "string", "enum": ["criar", "listar", "pausar", "retomar", "remover"]},
                        "titulo":         {"type": "string"},
                        "tipo":           {"type": "string", "enum": ["unico", "diario", "intervalo_min"]},
                        "quando":         {"type": "string", "description": "ISO, só pra tipo 'unico'."},
                        "horario":        {"type": "string", "description": "HH:MM, só pra tipo 'diario'."},
                        "intervalo_min":  {"type": "integer", "description": "Minutos entre execuções, só pra tipo 'intervalo_min'."},
                        "ferramenta":     {"type": "string", "description": "Nome de outra ferramenta pra chamar automaticamente quando disparar (opcional)."},
                        "parametros":     {"type": "string", "description": "Argumentos da ferramenta como JSON string."},
                        "agendamento_id": {"type": "string"},
                    },
                    "required": ["acao"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "gerenciar_tarefas",
                "description": "CRUD de uma lista de tarefas (to-do) pra acompanhar pedidos com várias etapas.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "acao":      {"type": "string", "enum": ["criar", "listar", "atualizar", "remover"]},
                        "titulo":    {"type": "string"},
                        "tarefa_id": {"type": "string"},
                        "status":    {"type": "string", "enum": ["pendente", "em_andamento", "concluida"]},
                    },
                    "required": ["acao"],
                },
            },
        },
]


MAP = {
    "gerenciar_lembretes": gerenciar_lembretes,
    "gerenciar_agendamentos": gerenciar_agendamentos,
    "gerenciar_tarefas": gerenciar_tarefas,
}
