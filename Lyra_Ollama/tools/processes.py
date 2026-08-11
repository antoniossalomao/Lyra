"""tools/processes.py — Background process tools: fire-and-forget PowerShell jobs and folder watchers."""

import json
import os
import pathlib
import re
import subprocess
import time
from datetime import datetime
from typing import Any

from ._shared import surreal_query, one
from .notifications import notificar_usuario

_PROCESSOS_BG_LOG_DIR = pathlib.Path(__file__).parent.parent / "lyra_processos_bg_logs"
_PROCESSOS_BG_LOG_DIR.mkdir(exist_ok=True)

_VIGILANCIAS: dict[str, Any] = {}  # pasta_abs -> watchdog Observer (vive em memória, não sobrevive a restart)

def iniciar_processo_bg(nome: str, comando: str, notificar_ao_concluir: bool = True) -> dict:
    """
    Dispara um comando PowerShell longo em background (sem bloquear o chat) e
    registra o PID + arquivo de log no SurrealDB ('processo_bg'). Útil pra
    tarefas que demoram (ex: vetorizações, backups grandes) — complementa
    executar_comando, que é síncrono e tem timeout curto.
    Use status_processo_bg ou listar_processos_bg pra acompanhar o progresso;
    o loop_proativo detecta sozinho quando o processo termina e notifica.
    """
    try:
        ts = int(time.time())
        log_path = _PROCESSOS_BG_LOG_DIR / f"{ts}_{re.sub(r'[^a-zA-Z0-9_]', '_', nome)}.log"
        log_f = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", comando],
            stdout=log_f, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        payload = {
            "nome": nome, "comando": comando, "pid": proc.pid,
            "log_path": str(log_path), "iniciado": datetime.now().isoformat(),
            "status": "rodando", "notificar_ao_concluir": notificar_ao_concluir,
            "notificado": False,
        }
        r = surreal_query(f"CREATE processo_bg CONTENT {json.dumps(payload, ensure_ascii=False)}")
        return {"ok": True, "processo": one(r)}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def _tail(path: str, n: int = 30) -> str:
    try:
        linhas = pathlib.Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(linhas[-n:])
    except Exception as e:
        return f"(não foi possível ler o log: {e})"

def status_processo_bg(processo_id: str, linhas_log: int = 30) -> dict:
    """Verifica se um processo em background ainda está rodando (psutil) e
    mostra as últimas linhas do log. Também atualiza o status no SurrealDB
    se detectar que o processo já terminou."""
    try:
        if not re.fullmatch(r"processo_bg:[a-zA-Z0-9_]+", processo_id):
            return {"erro": "Informe 'processo_id' válido (formato 'processo_bg:xxxxx')."}
        registros = surreal_query(f"SELECT * FROM {processo_id}")
        if not registros:
            return {"erro": f"Processo não encontrado: {processo_id}"}
        proc = registros[0]

        import psutil
        ainda_rodando = psutil.pid_exists(proc["pid"])
        if not ainda_rodando and proc.get("status") == "rodando":
            surreal_query(f"UPDATE {processo_id} SET status = 'concluido'")
            proc["status"] = "concluido"

        return {
            "ok": True, "nome": proc.get("nome"), "status": proc.get("status"),
            "rodando": ainda_rodando, "log_tail": _tail(proc.get("log_path", ""), linhas_log),
        }
    except Exception as e:
        return {"erro": str(e), "ok": False}

def listar_processos_bg(somente_ativos: bool = True) -> dict:
    """Lista processos em background iniciados via iniciar_processo_bg."""
    try:
        if somente_ativos:
            r = surreal_query("SELECT * FROM processo_bg WHERE status = 'rodando' ORDER BY iniciado DESC")
        else:
            r = surreal_query("SELECT * FROM processo_bg ORDER BY iniciado DESC LIMIT 50")
        return {"ok": True, "total": len(r), "processos": r}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def _checar_processos_bg_concluidos() -> list[dict]:
    """Uso interno do loop proativo — verifica processos 'rodando' que já
    terminaram e ainda não foram notificados. Retorna os que precisam de
    notificação (já marca status/notificado no banco)."""
    import psutil
    rodando = surreal_query("SELECT * FROM processo_bg WHERE status = 'rodando'")
    concluidos = []
    for proc in rodando:
        if not psutil.pid_exists(proc["pid"]):
            surreal_query(f"UPDATE {proc['id']} SET status = 'concluido'")
            if proc.get("notificar_ao_concluir") and not proc.get("notificado"):
                surreal_query(f"UPDATE {proc['id']} SET notificado = true")
                proc["log_tail"] = _tail(proc.get("log_path", ""), 15)
                concluidos.append(proc)
    return concluidos

def iniciar_vigilancia_pasta(pasta: str) -> dict:
    """
    Monitora uma pasta em tempo real (watchdog) e dispara notificar_usuario
    quando um arquivo novo é criado nela. Útil pra "me avisa quando cair
    algo em Downloads". A vigilância fica só em memória — some se o
    cerebro_maestro reiniciar (precisa chamar de novo).
    """
    try:
        pasta_abs = str(pathlib.Path(pasta).expanduser().resolve())
        if not os.path.isdir(pasta_abs):
            return {"erro": f"Pasta não encontrada: {pasta_abs}", "ok": False}
        if pasta_abs in _VIGILANCIAS:
            return {"ok": True, "info": "Já estava sendo vigiada.", "pasta": pasta_abs}

        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        class _Handler(FileSystemEventHandler):
            def on_created(self, event):
                if event.is_directory:
                    return
                notificar_usuario(
                    titulo="Novo arquivo detectado",
                    mensagem=f"{os.path.basename(event.src_path)} em {pasta_abs}",
                    urgencia="normal",
                )

        observer = Observer()
        observer.schedule(_Handler(), pasta_abs, recursive=False)
        observer.start()
        _VIGILANCIAS[pasta_abs] = observer
        return {"ok": True, "pasta": pasta_abs, "status": "vigiando"}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def parar_vigilancia_pasta(pasta: str) -> dict:
    """Para a vigilância de uma pasta iniciada por iniciar_vigilancia_pasta."""
    try:
        pasta_abs = str(pathlib.Path(pasta).expanduser().resolve())
        observer = _VIGILANCIAS.pop(pasta_abs, None)
        if not observer:
            return {"erro": f"Pasta não está sendo vigiada: {pasta_abs}", "ok": False}
        observer.stop()
        observer.join(timeout=5)
        return {"ok": True, "pasta": pasta_abs, "status": "parado"}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def listar_vigilancias() -> dict:
    """Lista pastas atualmente sob vigilância (em memória, nesta execução do processo)."""
    return {"ok": True, "pastas": list(_VIGILANCIAS.keys())}


SCHEMA = [
        {
            "type": "function",
            "function": {
                "name": "iniciar_processo_bg",
                "description": "Inicia um comando PowerShell longo em background, sem bloquear o chat, e registra PID+log pra acompanhamento.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "nome":    {"type": "string"},
                        "comando": {"type": "string"},
                        "notificar_ao_concluir": {"type": "boolean"},
                    },
                    "required": ["nome", "comando"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "status_processo_bg",
                "description": "Verifica se um processo em background ainda está rodando e mostra as últimas linhas do log.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "processo_id": {"type": "string"},
                        "linhas_log":  {"type": "integer"},
                    },
                    "required": ["processo_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "listar_processos_bg",
                "description": "Lista processos em background iniciados via iniciar_processo_bg.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "somente_ativos": {"type": "boolean"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "iniciar_vigilancia_pasta",
                "description": "Começa a vigiar uma pasta e avisa quando um arquivo novo chega nela.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pasta": {"type": "string", "description": "Caminho da pasta a vigiar."},
                    },
                    "required": ["pasta"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "parar_vigilancia_pasta",
                "description": "Para a vigilância de uma pasta.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pasta": {"type": "string", "description": "Caminho da pasta a parar de vigiar."},
                    },
                    "required": ["pasta"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "listar_vigilancias",
                "description": "Lista as pastas atualmente sob vigilância.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
]


MAP = {
    "iniciar_processo_bg": iniciar_processo_bg,
    "status_processo_bg": status_processo_bg,
    "listar_processos_bg": listar_processos_bg,
    "iniciar_vigilancia_pasta": iniciar_vigilancia_pasta,
    "parar_vigilancia_pasta": parar_vigilancia_pasta,
    "listar_vigilancias": listar_vigilancias,
}
