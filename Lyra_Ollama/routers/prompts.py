"""
routers/prompts.py — biblioteca de prompts salvos (item novo, auditoria de
paridade com Open WebUI 2026-08-12: prompts reutilizáveis inseridos no
composer com 1 clique). Tabela `prompt` nova, aditiva — SurrealDB schemaless,
não toca em nenhuma tabela existente.
"""
import datetime
import json

from fastapi import APIRouter

from models.prompts import PromptCriar, PromptEditar


class PromptsRouter:
    def __init__(self, *, surreal, sessao_id_limpo):
        self._surreal = surreal
        self._sessao_id_limpo = sessao_id_limpo

        self.router = APIRouter(prefix="/prompts", tags=["prompts"])
        self.router.add_api_route("", self.listar, methods=["GET"])
        self.router.add_api_route("", self.criar, methods=["POST"])
        self.router.add_api_route("/{prompt_id}", self.editar, methods=["PATCH"])
        self.router.add_api_route("/{prompt_id}", self.deletar, methods=["DELETE"])

    async def listar(self):
        dados = await self._surreal.query_result(
            "SELECT id, titulo, comando, conteudo, criado_em FROM prompt ORDER BY criado_em DESC;")
        itens = [
            {"id": self._sessao_id_limpo(p.get("id", "")), "titulo": p.get("titulo", ""),
             "comando": p.get("comando", ""), "conteudo": p.get("conteudo", "")}
            for p in dados
        ] if isinstance(dados, list) else []
        return {"total": len(itens), "prompts": itens}

    async def criar(self, req: PromptCriar):
        criado_em = datetime.datetime.now(datetime.timezone.utc).isoformat()
        campos = (f"titulo = {json.dumps(req.titulo)}, comando = {json.dumps(req.comando)}, "
                  f"conteudo = {json.dumps(req.conteudo)}, criado_em = {json.dumps(criado_em)}")
        dados = await self._surreal.query_result(f"CREATE prompt SET {campos};")
        if not dados or not isinstance(dados[0], dict):
            return {"erro": "Falha ao criar prompt."}
        return {"ok": True, "id": self._sessao_id_limpo(dados[0].get("id", ""))}

    async def editar(self, prompt_id: str, req: PromptEditar):
        campos = (f"titulo = {json.dumps(req.titulo)}, comando = {json.dumps(req.comando)}, "
                  f"conteudo = {json.dumps(req.conteudo)}")
        await self._surreal.query(f'UPDATE type::record("prompt", {json.dumps(prompt_id)}) SET {campos};')
        return {"ok": True}

    async def deletar(self, prompt_id: str):
        await self._surreal.query(f'DELETE type::record("prompt", {json.dumps(prompt_id)});')
        return {"ok": True}
