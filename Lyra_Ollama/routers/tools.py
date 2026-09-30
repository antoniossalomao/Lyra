"""
routers/tools.py — lista + toggle de ferramentas disponíveis
(LYRA_NUCLEO.md §5.4, "painel de MCP servers"). O backend
já expõe as tools via FastApiMCP em `/mcp` (protocolo MCP, não é JSON
simples pra uma UI consumir direto) — este endpoint é uma view em REST
simples do mesmo catálogo (`lyra_tools.TOOLS_SCHEMA`) pra alimentar um
painel no frontend, com liga/desliga.

Estado do toggle é em memória (`tools_desabilitadas`, um `set[str]`
compartilhado por referência com `ChatRouter`) — mesmo padrão de
persistência que `_tts_mudo` já usa: não sobrevive restart do cérebro, e
está tudo bem, é reaplicado pelo frontend se precisar. `ChatRouter` filtra
`TOOLS_SCHEMA` por esse set antes de mandar pra cascata — ver
`routers/chat.py`.
"""
from fastapi import APIRouter


class ToolsRouter:
    def __init__(self, *, tools_schema: list, tools_desabilitadas: set):
        self._tools_schema = tools_schema
        self._tools_desabilitadas = tools_desabilitadas

        self.router = APIRouter()
        self.router.add_api_route("/tools", self.tools_listar, methods=["GET"])
        self.router.add_api_route("/tools/{nome}/toggle", self.tools_toggle, methods=["POST"])

    def tools_listar(self):
        ferramentas = [
            {"nome": t["function"]["name"], "descricao": t["function"].get("description", ""),
             "habilitada": t["function"]["name"] not in self._tools_desabilitadas}
            for t in self._tools_schema
            if t.get("type") == "function"
        ]
        return {"total": len(ferramentas), "ferramentas": ferramentas, "mcp_endpoint": "/mcp"}

    def tools_toggle(self, nome: str):
        nomes_validos = {t["function"]["name"] for t in self._tools_schema if t.get("type") == "function"}
        if nome not in nomes_validos:
            return {"erro": f"Ferramenta '{nome}' não existe."}
        if nome in self._tools_desabilitadas:
            self._tools_desabilitadas.discard(nome)
            habilitada = True
        else:
            self._tools_desabilitadas.add(nome)
            habilitada = False
        return {"ok": True, "nome": nome, "habilitada": habilitada}
