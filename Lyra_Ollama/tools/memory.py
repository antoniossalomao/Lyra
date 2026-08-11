"""tools/memory.py — Vector-memory tools: hybrid search, save to long-term memory, and full backup."""

import json
import pathlib
import uuid
from datetime import datetime

from config import QDRANT_COLLECTION as _COLECAO_MEMORIA
from ._lazy import get_qdrant, get_bm25_index, embed_remote
from ._shared import surreal_query

def buscar_memoria(query: str, top_k: int = 5, categoria: str = "") -> dict:
    """Busca híbrida (BM25 lexical + vetorial denso, combinados via RRF) na
    memória da Lyra (Qdrant lyra_memory) — mesma lógica usada pela busca
    automática do chat em cerebro_maestro.py, agora também disponível aqui."""
    try:
        import bm25_index

        vetor = embed_remote(query)  # BGE-M3 1024d via embed_service :8001

        from qdrant_client.models import Filter, FieldCondition, MatchValue

        filtro = None
        if categoria:
            filtro = Filter(must=[FieldCondition(
                key="categoria", match=MatchValue(value=categoria))])

        hits_dense = get_qdrant().query_points(
            collection_name=_COLECAO_MEMORIA,
            query=vetor,
            query_filter=filtro,
            limit=top_k * 3,
        ).points
        resultados_dense = [(h.id, h.score, h.payload) for h in hits_dense]

        indice = get_bm25_index()
        resultados_bm25 = bm25_index.buscar_bm25(indice, query, top_k=top_k * 3)
        if categoria:
            resultados_bm25 = [r for r in resultados_bm25 if r[2].get("categoria") == categoria]

        fundidos = bm25_index.fusao_rrf(resultados_dense, resultados_bm25, top_k=top_k)

        return {
            "query":            query,
            "categoria_filtro": categoria or "todas",
            "resultados": [
                {
                    "rrf_score":   r["rrf_score"],
                    "dense_score": r["dense_score"],
                    "bm25_score":  r["bm25_score"],
                    "titulo":      r["payload"].get("titulo", ""),
                    "categoria":   r["payload"].get("categoria", ""),
                    "trecho":      (r["payload"].get("texto", "") or "")[:500],
                }
                for r in fundidos
            ],
        }
    except Exception as e:
        return {"erro": str(e)}

def salvar_memoria(titulo: str, texto: str, categoria: str = "geral") -> dict:
    """Salva informação na memória vetorial da Lyra."""
    try:
        conteudo = f"{titulo}\n\n{texto}"
        vetor    = embed_remote(conteudo)  # BGE-M3 1024d via embed_service :8001

        from qdrant_client.models import PointStruct

        ponto_id = str(uuid.uuid4())

        get_qdrant().upsert(
            collection_name=_COLECAO_MEMORIA,
            points=[PointStruct(
                id=ponto_id,
                vector=vetor,
                payload={
                    "titulo":     titulo,
                    "texto":      texto,
                    "categoria":  categoria,
                    "timestamp":  datetime.now().isoformat(),
                    "fonte":      "lyra_tools",
                },
            )],
        )
        return {"ok": True, "id": ponto_id,
                "titulo": titulo, "categoria": categoria}
    except Exception as e:
        return {"erro": str(e)}

def backup_memoria(destino: str = "") -> dict:
    """
    Backup pontual de segurança: exporta todas as tabelas do SurrealDB
    (lyra_core/Db_CORTEX) pra JSON com timestamp, e cria snapshot das coleções
    Qdrant (lyra_memory e lyra_memory_v2, se existirem). Não é incremental —
    é pra rodar antes de qualquer operação arriscada na memória.
    """
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        pasta = pathlib.Path(destino) if destino else (
            pathlib.Path(__file__).parent.parent / "Lyra_Core" / "Memoria_Lyra" / "backups" / ts)
        pasta.mkdir(parents=True, exist_ok=True)

        resultado: dict = {"ok": True, "pasta": str(pasta), "tabelas": {}, "qdrant_snapshots": {}}

        info = surreal_query("INFO FOR DB")
        tabelas = list(info.get("tables", {}).keys()) if isinstance(info, dict) else []

        for tabela in tabelas:
            try:
                dados = surreal_query(f"SELECT * FROM {tabela}")
                (pasta / f"{tabela}.json").write_text(
                    json.dumps(dados, ensure_ascii=False), encoding="utf-8")
                resultado["tabelas"][tabela] = len(dados)
            except Exception as e:
                resultado["tabelas"][tabela] = f"erro: {e}"

        try:
            q = get_qdrant()
            for colecao in ("lyra_memory", "lyra_memory_v2"):
                try:
                    snap = q.create_snapshot(collection_name=colecao)
                    resultado["qdrant_snapshots"][colecao] = snap.name
                except Exception as e:
                    resultado["qdrant_snapshots"][colecao] = f"erro/não existe: {e}"
        except Exception as e:
            resultado["qdrant_erro"] = str(e)

        return resultado
    except Exception as e:
        return {"erro": str(e), "ok": False}


SCHEMA = [
        {
            "type": "function",
            "function": {
                "name": "buscar_memoria",
                "description": "Busca RAG na memória vetorial.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query":     {"type": "string"},
                        "top_k":     {"type": "integer"},
                        "categoria": {"type": "string"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "salvar_memoria",
                "description": "Salva informação na memória longo prazo.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "titulo":    {"type": "string"},
                        "texto":     {"type": "string"},
                        "categoria": {"type": "string"},
                    },
                    "required": ["titulo", "texto", "categoria"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "backup_memoria",
                "description": "Faz backup de segurança de toda a memória (SurrealDB + snapshot Qdrant).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "destino": {"type": "string"},
                    },
                },
            },
        },
]


MAP = {
    "buscar_memoria": buscar_memoria,
    "salvar_memoria": salvar_memoria,
    "backup_memoria": backup_memoria,
}
