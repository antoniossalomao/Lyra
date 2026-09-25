"""
routers/sessions.py — endpoints de histórico e sessões de conversa.

Extraído de cerebro_maestro.py na reorganização OOP (Lyra 2.0). Comportamento
idêntico ao original — só move código de lugar, não muda lógica.
"""
import json

from fastapi import APIRouter

from models.sessions import SessaoAtivar, SessaoRenomear, SessaoFavoritar


class SessionsRouter:
    """Agrupa os endpoints de histórico/sessões (`/historico`, `/sessoes*`).

    Recebe o `SessionManager` (estado de conversa em memória) e o par
    query/result do `SurrealClient` compartilhado via construtor — mesmo
    padrão de `SystemRouter`: dependências explícitas, sem globals soltos.
    """

    def __init__(self, *, session, sql_surreal, surreal_result, sessao_id_limpo, log):
        self._session = session
        self._sql = sql_surreal
        self._result = surreal_result
        self._sessao_id_limpo = sessao_id_limpo
        self._log = log

        self.router = APIRouter()
        self.router.add_api_route("/historico", self.historico_get, methods=["GET"])
        self.router.add_api_route("/historico", self.historico_limpar, methods=["DELETE"])
        self.router.add_api_route("/sessoes", self.sessoes_listar, methods=["GET"])
        self.router.add_api_route("/sessoes", self.sessao_nova, methods=["POST"])
        self.router.add_api_route("/sessoes/ativar", self.sessao_ativar, methods=["POST"])
        self.router.add_api_route("/sessoes/{sessao_id}", self.sessao_renomear, methods=["PATCH"])
        self.router.add_api_route("/sessoes/{sessao_id}", self.sessao_deletar, methods=["DELETE"])
        self.router.add_api_route("/sessoes/{sessao_id}/favoritar", self.sessao_favoritar, methods=["POST"])

    async def historico_get(self, sessao: str | None = None):
        """Sem parâmetro: histórico em memória (comportamento original).
        Com ?sessao=<id>: mensagens daquela sessão direto do SurrealDB
        ('legado' = eventos gravados antes da migração de sessões)."""
        if not sessao:
            hist = await self._session.snapshot()
            return {"total": len(hist), "mensagens": hist}
        cond = "sessao_id IS NONE" if sessao == "legado" else f"sessao_id = {json.dumps(sessao)}"
        try:
            dados = await self._sql(
                f"SELECT ator, texto, timestamp FROM evento WHERE {cond} "
                "ORDER BY timestamp ASC LIMIT 300")
            eventos = self._result(dados)
        except Exception as e:
            return {"erro": f"Falha ao ler sessão: {e}", "total": 0, "mensagens": []}
        mensagens = [
            {"role": "assistant" if ev.get("ator", "").lower() == "lyra" else "user",
             "content": ev.get("texto", ""), "timestamp": ev.get("timestamp", "")}
            for ev in eventos
        ]
        return {"total": len(mensagens), "mensagens": mensagens, "sessao": sessao}

    async def historico_limpar(self):
        """Limpa o histórico em memória (não apaga SurrealDB/Qdrant)."""
        await self._session.clear_history()
        self._log("[HIST] Histórico em memória limpo via DELETE /historico.")
        return {"ok": True, "mensagem": "Histórico em memória limpo."}

    async def sessoes_listar(self):
        """Lista as sessões de conversa pra sidebar do frontend (mais recentes
        primeiro). Inclui uma entrada sintética 'legado' se existirem eventos
        gravados antes da migração de sessões."""
        itens = []
        try:
            dados = await self._sql(
                "SELECT id, criada, titulo, favorita FROM sessao ORDER BY criada DESC LIMIT 40")
            for r in self._result(dados):
                sid = self._sessao_id_limpo(r.get("id", ""))
                itens.append({
                    "sessao_id": sid,
                    "titulo": r.get("titulo") or "conversa sem título",
                    "criada": r.get("criada", ""),
                    "ativa": sid == self._session.session_id,
                    "favorita": bool(r.get("favorita", False)),  # aditivo — sessões antigas sem o campo caem em False
                })
        except Exception as e:
            return {"erro": f"Falha ao listar sessões: {e}", "sessoes": []}
        try:
            dados = await self._sql("SELECT count() FROM evento WHERE sessao_id IS NONE GROUP ALL")
            legado = self._result(dados)
            if legado and legado[0].get("count", 0) > 0:
                itens.append({"sessao_id": "legado", "titulo": "conversas antigas (pré-sessões)",
                              "criada": "", "ativa": False, "somente_leitura": True})
        except Exception:
            pass  # contagem de legado é cosmética — a lista principal já foi montada
        return {"total": len(itens), "sessoes": itens, "ativa": self._session.session_id}

    async def sessao_nova(self):
        """Cria uma nova sessão de conversa e a torna ativa. O histórico em
        memória é zerado — a Lyra começa a conversa limpa (SurrealDB/Qdrant
        seguem intactos, memória de longo prazo continua via RAG)."""
        return await self._session.new_session()

    async def sessao_ativar(self, req: SessaoAtivar):
        """Torna outra sessão a ativa e recarrega o histórico com as últimas
        mensagens dela ('legado' é somente leitura — use GET /historico)."""
        return await self._session.activate_session(req.sessao_id)

    async def sessao_renomear(self, sessao_id: str, req: SessaoRenomear):
        return await self._session.rename_session(sessao_id, req.titulo)

    async def sessao_deletar(self, sessao_id: str):
        return await self._session.delete_session(sessao_id)

    async def sessao_favoritar(self, sessao_id: str, req: SessaoFavoritar):
        return await self._session.favorite_session(sessao_id, req.favorita)
