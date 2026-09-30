"""
routers/models_hub.py — hub de modelos Ollama (LYRA_NUCLEO.md
§5.4): listar modelos instalados e puxar um novo com progresso.

Não existe API pública de busca no registry do Ollama documentada de forma
confiável pra chamar daqui sem arriscar quebrar quando o formato mudar — o
usuário digita o nome do modelo que já conhece (ex: "llama3.2:3b"), igual
`ollama pull <nome>` no terminal. `GET /ollama/models` é só leitura (lista o
que já está instalado, via `/api/tags` do Ollama). `POST /ollama/models/pull`
DISPARA um download de verdade — só executa quando alguém chama o endpoint
de propósito (o frontend exige confirmação explícita antes, ver
`GraphPanel`-equivalente no `Chat.svelte`/`SystemPanel`); escrever este
código não baixa nada sozinho.
"""
import json

import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


class PullRequest(BaseModel):
    nome: str


class ModelsHubRouter:
    def __init__(self, *, ollama_url: str, log):
        self._ollama_url = ollama_url
        self._log = log

        self.router = APIRouter(prefix="/ollama", tags=["models_hub"])
        self.router.add_api_route("/models", self.listar_modelos, methods=["GET"])
        self.router.add_api_route("/models/pull", self.puxar_modelo, methods=["POST"])

    async def listar_modelos(self):
        """Lista modelos já instalados localmente (só leitura, sem custo de rede externa)."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self._ollama_url}/api/tags", timeout=10)
                resp.raise_for_status()
                dados = resp.json()
        except Exception as e:
            return {"erro": f"Falha ao consultar Ollama: {e}", "modelos": []}
        modelos = [
            {"nome": m.get("name", ""), "tamanho_bytes": m.get("size", 0),
             "modificado_em": m.get("modified_at", "")}
            for m in dados.get("models", [])
        ]
        return {"total": len(modelos), "modelos": modelos}

    async def puxar_modelo(self, req: PullRequest):
        """Dispara `ollama pull <nome>` via API HTTP do Ollama, com progresso
        em streaming (SSE). Download real — só roda porque este endpoint foi
        chamado de propósito, não é disparado automaticamente por nada."""
        nome = req.nome.strip()
        if not nome:
            return StreamingResponse(iter([f"data: {json.dumps({'erro': 'nome vazio'})}\n\n"]),
                                     media_type="text/event-stream")

        async def eventos():
            try:
                async with httpx.AsyncClient(timeout=None) as client:
                    async with client.stream(
                        "POST", f"{self._ollama_url}/api/pull",
                        json={"name": nome, "stream": True},
                    ) as resp:
                        async for linha in resp.aiter_lines():
                            if not linha.strip():
                                continue
                            try:
                                progresso = json.loads(linha)
                            except json.JSONDecodeError:
                                continue
                            yield f"data: {json.dumps(progresso)}\n\n"
                self._log(f"[MODEL HUB] Pull concluído: {nome}")
            except Exception as e:
                self._log(f"[MODEL HUB] Pull de '{nome}' falhou: {e}")
                yield f"data: {json.dumps({'erro': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(eventos(), media_type="text/event-stream")
