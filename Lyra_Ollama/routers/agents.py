"""
routers/agents.py — endpoints de enxame de sub-agentes, agente ReAct autônomo
e Shadow Thoughts (consolidação de memória em background).

Extraído de cerebro_maestro.py na reorganização OOP (Lyra 2.0). Comportamento
idêntico ao original — só move código de lugar, não muda lógica.
"""
import asyncio

from fastapi import APIRouter

from models.agents import EnxameRequest, AgenteRequest, ShadowRequest


class AgentsRouter:
    """Agrupa os endpoints de sub-agentes: `/enxame*` (lyra_agentes.py),
    `/agente*` (lyra_agent.py, loop ReAct) e `/shadow_thoughts`
    (lyra_shadow_thoughts.py, ciclo NREM/REM/DEEP).

    Dependências injetadas via construtor — os três módulos de agente e o
    `notificar_usuario`/`query_result` que os handlers chamam.
    """

    def __init__(self, *, agentes_module, agent_module, surreal, notificar_usuario, log):
        self._agentes = agentes_module
        self._agent = agent_module
        self._surreal = surreal
        self._notificar_usuario = notificar_usuario
        self._log = log

        self.router = APIRouter()
        self.router.add_api_route("/enxame", self.enxame_criar, methods=["POST"])
        self.router.add_api_route("/enxames", self.enxames_listar, methods=["GET"])
        self.router.add_api_route("/enxame/{enxame_id}", self.enxame_status, methods=["GET"])
        self.router.add_api_route("/enxame/{enxame_id}/consolidar", self.enxame_consolidar, methods=["POST"])
        self.router.add_api_route("/agente", self.agente_executar, methods=["POST"])
        self.router.add_api_route("/agente/runs", self.agente_runs, methods=["GET"])
        self.router.add_api_route("/shadow_thoughts", self.shadow_thoughts_disparar, methods=["POST"])

    async def enxame_criar(self, req: EnxameRequest):
        return await self._agentes.criar_enxame(req.objetivo, req.subtarefas, req.max_paralelo)

    async def enxames_listar(self, limite: int = 20):
        return await self._agentes.listar_enxames(limite)

    async def enxame_status(self, enxame_id: str):
        return await self._agentes.status_enxame(enxame_id)

    async def enxame_consolidar(self, enxame_id: str):
        resultado = await self._agentes.consolidar_enxame(enxame_id)
        # Notifica proativamente quando consolidação termina
        if "resumo" in resultado:
            self._notificar_usuario(
                titulo="Enxame consolidado",
                mensagem=resultado["resumo"][:200],
                urgencia="normal",
            )
        return resultado

    async def agente_executar(self, req: AgenteRequest):
        """Loop ReAct autônomo (lyra_agent.py) — recebe objetivo, itera com ferramentas
        e retorna resultado final. Não usa streaming; aguarda conclusão antes de responder."""
        return await self._agent.executar_agente_async(req.objetivo, req.max_iteracoes)

    async def agente_runs(self, limite: int = 20):
        """Lista execuções recentes do agente autônomo (tabela agente_run no SurrealDB)."""
        runs = await self._surreal.query_result(
            f"SELECT id, objetivo, sucesso, iteracoes, criado_em FROM agente_run "
            f"ORDER BY criado_em DESC LIMIT {min(limite, 100)};")
        return {"total": len(runs), "runs": runs}

    async def shadow_thoughts_disparar(self, req: ShadowRequest = ShadowRequest()):
        """Dispara o ciclo de Shadow Thoughts em background (NREM/REM/DEEP).
        Retorna imediatamente — progresso aparece no maestro.log."""
        import lyra_shadow_thoughts as _st
        fases = [f.strip().lower() for f in req.fases.split(",") if f.strip() in {"nrem", "rem", "deep"}]
        if not fases:
            return {"erro": "Fases inválidas. Use 'nrem,rem,deep' ou subconjunto."}
        asyncio.create_task(_st.ciclo_completo(fases))
        self._log(f"[SHADOW] Ciclo disparado manualmente — fases: {fases}")
        return {"ok": True, "fases_disparadas": fases, "mensagem": "Ciclo iniciado em background — veja maestro.log."}
