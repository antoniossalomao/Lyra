"""
routers/logs.py — viewer de log dentro do app (PLANEJAMENTO_LYRA2.0.md seção
9 item 6, parte "logs" — a parte "monitor" já foi resolvida por
SystemRouter/health+metrics, consumidos pelo SystemPanel.svelte).

Hoje `maestro.log`/`maestro.err` só existem como arquivo texto (ver
cerebro_maestro.py: `log = Logger(_LOG_PATH)`). Isto é só um viewer
somente-leitura — não escreve, não roda comando nenhum, só lê as últimas N
linhas do arquivo.
"""
from pathlib import Path

from fastapi import APIRouter


class LogsRouter:
    def __init__(self, *, log_path: str, err_path: str):
        self._log_path = Path(log_path)
        self._err_path = Path(err_path)

        self.router = APIRouter()
        self.router.add_api_route("/logs", self.logs_ler, methods=["GET"])

    def _tail(self, caminho: Path, linhas: int) -> list[str]:
        if not caminho.is_file():
            return []
        try:
            texto = caminho.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []
        return texto.splitlines()[-linhas:]

    def logs_ler(self, linhas: int = 200, fonte: str = "log"):
        """`fonte`: 'log' (maestro.log, saída normal) ou 'err' (maestro.err,
        stderr — só existe se o processo foi lançado redirecionando stderr)."""
        linhas = min(max(linhas, 1), 2000)
        caminho = self._err_path if fonte == "err" else self._log_path
        return {"fonte": fonte, "linhas": self._tail(caminho, linhas)}
