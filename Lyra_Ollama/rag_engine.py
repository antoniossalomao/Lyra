"""rag_engine.py — hybrid retrieval + event persistence for cerebro_maestro.

Extracted from cerebro_maestro.py (OOP refactor 08/2026): hybrid search
(BM25 + dense + cross-encoder rerank), SurrealDB graph traversal, retrieval
access tracking, context assembly and conversation-event persistence.
"""

import asyncio
import datetime
import json
import re
import unicodedata
import uuid
from typing import Callable

import bm25_index

from config import QDRANT_COLLECTION
from surreal_client import SurrealClient

# ── Text utilities (shared with cerebro_maestro) ─────────────────────────────


def remove_accents(texto: str) -> str:
    """Remove acentos pra matching de keywords não depender de o usuário
    digitar certinho ('saude' vs 'saúde')."""
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if not unicodedata.combining(c))


_STOPWORDS_PT = {
    "a", "o", "e", "de", "do", "da", "em", "um", "uma", "que", "se", "por",
    "com", "para", "no", "na", "os", "as", "ao", "dos", "das", "como", "mais",
    "mas", "foi", "ser", "tem", "nao", "ja", "isso", "este", "esta", "aqui",
    "ali", "bem", "sim", "pra", "pro", "pras", "pros", "voce", "nos",
    "ele", "ela", "eles", "elas", "meu", "minha", "seu", "sua", "muito",
    "pouco", "quando", "onde", "quem", "qual", "quais", "esse", "essa",
    "ola", "oi", "tchau", "tudo", "certo", "joia",
}


def extract_keywords(texto: str, n: int = 5) -> list[str]:
    """Extrai os N primeiros tokens relevantes (sem stopwords, ≥3 chars) —
    usados como nós de tópico no grafo SurrealDB (RELATE evento->sobre->topico)."""
    tokens = re.findall(r"[a-zA-ZÀ-ÿ0-9]{3,}", texto.lower())
    vistos: set[str] = set()
    resultado = []
    for t in tokens:
        t_norm = remove_accents(t)
        if t_norm not in _STOPWORDS_PT and t_norm not in vistos:
            vistos.add(t_norm)
            resultado.append(t_norm)
        if len(resultado) >= n:
            break
    return resultado


def classify_intent(ator: str, texto: str) -> str:
    """Goal Drift Detector (Innovation 1): classifica a intenção de uma
    mensagem por heurística (zero custo/latência).
    Retorna: 'objetivo' | 'conclusao' | 'passo' | 'resposta' (para Lyra)."""
    if ator != "Antônio":
        return "resposta"
    t = remove_accents(texto.lower())
    if any(p in t for p in ["preciso que", "quero que", "pode fazer", "me ajuda a",
                            "como faco", "como eu posso", "implementa ", "cria um",
                            "faz um", "gera um", "me de um", "precisaria", "voce pode",
                            "me mostre", "me explica", "queria que", "consegue fazer"]):
        return "objetivo"
    if any(p in t for p in ["funcionou", "consegui", "perfeito", "excelente",
                            "obrigado", "valeu", "foi isso", "otimo", "deu certo",
                            "era isso", "resolvido", "certinho"]):
        return "conclusao"
    return "passo"


# ── Knowledge Freshness (Innovation 2) ───────────────────────────────────────
# Meia-vida por categoria (dias): categorias técnicas voláteis (APIs, código)
# decaem mais rápido que matemática/história (estáveis por natureza).

_FRESHNESS_HALF_LIFE: dict[str, float] = {
    "programacao":           180,   # código/APIs mudam ~a cada 6 meses
    "documentacao":          180,
    "conhecimento_geral":   3650,   # Wikipedia — fatos históricos estáveis
    "raciocinio_matematico": 9999,  # matemática é imutável
    "conversa_geral":        730,
    "instrucao_ptbr":        730,
    "conhecimento_qa":       365,
    "episodio":              9999,  # memória episódica: não penalizar por tempo
}
FRESHNESS_WEIGHT = 0.06  # freshness influi no máximo 6% do score_final


def freshness_factor(categoria: str, timestamp_str: str) -> float:
    """Fator de frescor 0..1 baseado na meia-vida da categoria.
    1.0 = documento novo ou imutável; < 1.0 = conteúdo técnico antigo."""
    meia_vida = _FRESHNESS_HALF_LIFE.get(categoria, 365.0)
    if meia_vida >= 9999:
        return 1.0
    try:
        ts = datetime.datetime.fromisoformat(timestamp_str)
        dias = max(0, (datetime.datetime.now() - ts).days)
        return max(0.0, min(1.0, 0.5 ** (dias / meia_vida)))
    except Exception:
        return 1.0  # sem timestamp válido → não penaliza


class RAGEngine:
    """Hybrid retrieval engine combining dense (Qdrant), sparse (BM25) and
    cross-encoder reranking, plus conversation-event persistence.

    Uses Reciprocal Rank Fusion (RRF) to merge dense and sparse scores, then
    re-ranks top candidates with a cross-encoder; a light freshness signal
    (max 6%) demotes stale technical content.

    Stateless except for the shared Qdrant client and BM25 index references,
    which are attached after service startup via attributes (they only exist
    once Qdrant is reachable):
        rag.qdrant_client = QdrantClient(...)
        rag.bm25_index    = bm25_index.carregar_indice(...)
    """

    def __init__(self, surreal: SurrealClient,
                 embed: Callable, rerank: Callable, log: Callable):
        self._surreal = surreal
        self._embed = embed      # sync fn: text -> 1024-float vector | None
        self._rerank = rerank    # sync fn: (query, docs) -> scores | None
        self._log = log
        self.qdrant_client = None
        self.bm25_index = None
        self.last_event_id: str | None = None  # ponteiro pro RELATE precedeu

    @property
    def active(self) -> bool:
        """True once the Qdrant client is attached (brain initialized)."""
        return self.qdrant_client is not None

    # ── Hybrid search ────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 5, categoria: str = "",
               peso_relevancia: float = 1.0, peso_recencia: float = 0.0) -> list[dict]:
        """Run hybrid BM25 + dense + rerank search (synchronous — call via
        asyncio.to_thread from the event loop; takes 5-10 s on 2M+ vectors).

        Args:
            query:     Natural-language query string.
            top_k:     Number of results after reranking.
            categoria: Optional payload category filter.
            peso_relevancia / peso_recencia: kept for validador_cortical.py
                grid-search compatibility; defaults are the calibrated weights.

        Returns:
            List of candidate dicts with id, payload, rrf/dense/bm25/rerank
            scores, freshness_factor and score_final, sorted by score_final.
        """
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        vetor = self._embed(query)
        filtro = None
        if categoria:
            filtro = Filter(must=[FieldCondition(key="categoria",
                                                 match=MatchValue(value=categoria))])

        # Sem vetor (embed_service fora) → cai só pro BM25 lexical, sem denso.
        resultados_dense = []
        if vetor is not None:
            hits_dense = self.qdrant_client.query_points(
                collection_name=QDRANT_COLLECTION, query=vetor,
                query_filter=filtro, limit=top_k * 3).points
            resultados_dense = [(h.id, h.score, h.payload) for h in hits_dense]

        resultados_bm25 = bm25_index.buscar_bm25(self.bm25_index, query, top_k=top_k * 3)
        if categoria:
            resultados_bm25 = [r for r in resultados_bm25
                               if r[2].get("categoria") == categoria]

        candidatos = bm25_index.fusao_rrf(resultados_dense, resultados_bm25, top_k=top_k * 2)
        if not candidatos:
            return []

        # 3º estágio — reranking cross-encoder (bge-reranker-v2-m3): repontua
        # olhando query+documento juntos. Se o reranker cair, degrada pro RRF.
        docs_rerank = [f"{r['payload'].get('titulo', '')} {r['payload'].get('texto', '')}"[:1500]
                       for r in candidatos]
        scores_rerank = self._rerank(query, docs_rerank)

        if scores_rerank and len(scores_rerank) == len(candidatos):
            # O CrossEncoder já devolve probabilidade 0..1 (sigmoid interno).
            for r, s in zip(candidatos, scores_rerank):
                r["rerank_score"] = float(s)
                r["relevancia"] = min(1.0, max(0.0, float(s)))
        else:
            max_rrf = max((r["rrf_score"] for r in candidatos), default=1e-9)
            for r in candidatos:
                r["rerank_score"] = None
                r["relevancia"] = r["rrf_score"] / max_rrf

        # Score final = relevância + freshness leve por categoria (Innovation 2).
        for r in candidatos:
            p = r["payload"]
            ff = freshness_factor(p.get("categoria", ""), p.get("timestamp", ""))
            r["freshness_factor"] = round(ff, 3)
            r["score_final"] = r["relevancia"] * (1.0 - FRESHNESS_WEIGHT) + ff * FRESHNESS_WEIGHT

        candidatos.sort(key=lambda r: r["score_final"], reverse=True)
        return candidatos[:top_k]

    # ── Graph traversal ──────────────────────────────────────────────────────

    async def search_graph(self, query: str, limite: int = 5) -> list[dict]:
        """Traversal de grafo no SurrealDB: eventos ligados aos tópicos da
        query. Complementa o RAG vetorial em perguntas de memória."""
        keywords = extract_keywords(query, n=3)
        if not keywords:
            return []

        eventos: list[dict] = []
        vistos: set[str] = set()
        try:
            for kw in keywords:
                kw_safe = re.sub(r"[^a-z0-9]", "", kw)[:30]
                if not kw_safe:
                    continue
                # Traversal individual por tópico — LIMIT limita eventos por tópico
                q = f"SELECT <-sobre<-evento.* AS evs FROM topico:`{kw_safe}` LIMIT {limite};"
                try:
                    rows = await self._surreal.query_result(q, timeout=5)
                    for row in rows:
                        for ev in (row.get("evs") or []):
                            if isinstance(ev, dict):
                                txt = ev.get("texto", "")
                                if txt and txt not in vistos:
                                    vistos.add(txt)
                                    eventos.append(ev)
                                    if len(eventos) >= limite:
                                        return eventos
                except Exception:
                    continue
        except Exception as e:
            self._log(f"[GRAFO] Falha ao buscar: {e}")
        return eventos

    # ── Access tracking ──────────────────────────────────────────────────────

    async def update_access(self, resultados: list) -> None:
        """Incrementa retrieval_count e atualiza last_accessed_at nos vetores
        recuperados. Roda em background — não bloqueia o stream."""
        agora = datetime.datetime.now().isoformat()

        async def _um(r):
            ponto_id = r.get("id")
            if not ponto_id:
                return
            count = r["payload"].get("retrieval_count", 0) + 1
            try:
                await asyncio.to_thread(
                    self.qdrant_client.set_payload,
                    collection_name=QDRANT_COLLECTION,
                    payload={"last_accessed_at": agora, "retrieval_count": count},
                    points=[ponto_id],
                )
            except Exception:
                pass

        await asyncio.gather(*[_um(r) for r in resultados], return_exceptions=True)

    # ── Context assembly ─────────────────────────────────────────────────────

    async def build_context(self, query: str, resultados: list,
                            memoria_query: bool) -> str:
        """Format search results (plus graph events for memory questions)
        into the context string injected into the system prompt.

        Perguntas factuais genéricas NÃO recebem 'episodio' de volta (linhas
        do próprio chat) como se fosse fato — já causou loop de auto-reforço.
        """
        if not memoria_query:
            resultados = [r for r in resultados
                          if r["payload"].get("categoria") != "episodio"]

        textos_vistos: set[str] = set()
        partes = []

        def _add(ator: str, ts: str, txt: str) -> None:
            if not txt or txt in textos_vistos:
                return
            textos_vistos.add(txt)
            if ts:
                dt = datetime.datetime.fromisoformat(ts)
                partes.append(f"[{ator} - {dt.strftime('%d/%m/%Y %H:%M')}] {txt}")
            else:
                partes.append(f"[{ator}] {txt}")

        for r in resultados:
            p = r["payload"]
            _add(p.get("ator", "?"), p.get("timestamp", ""), p.get("texto", ""))

        if memoria_query:
            for ev in await self.search_graph(query, limite=5):
                _add(ev.get("ator", "?"), ev.get("timestamp", ""), ev.get("texto", ""))
            self._log(f"[RAG MEMÓRIA] {len(partes)} episódios (Qdrant + grafo SurrealDB)")

        return "\n".join(partes)

    # ── Event persistence ────────────────────────────────────────────────────

    async def record_event(self, fonte: str, ator: str, texto: str,
                           session=None,
                           intencao: str | None = None,
                           fontes_rag: list | None = None,
                           divergencia_draft: float | None = None) -> None:
        """Grava o evento no SurrealDB (cronológico + grafo) e Qdrant (vetorial).

        Args:
            session: SessionManager opcional — fornece session_id e recebe o
                ensure_title() na primeira fala do usuário.
            intencao: classificação do Goal Drift (default: classify_intent).
            fontes_rag: IDs Qdrant que alimentaram esta resposta (Innovation 5).
            divergencia_draft: distância coseno resposta×draft (spec-decoding).
        """
        if not self.active:
            return
        agora = datetime.datetime.now()
        evento_id = str(uuid.uuid4())
        _intencao = intencao or classify_intent(ator, texto)
        session_id = getattr(session, "session_id", None)

        # 1. SurrealDB (log cronológico)
        try:
            payload = {
                "id": evento_id, "fonte": fonte, "ator": ator, "texto": texto,
                "timestamp": agora.isoformat(), "intencao": _intencao,
            }
            if session_id:
                payload["sessao_id"] = session_id
            if fontes_rag:
                payload["fontes_rag"] = fontes_rag
            if divergencia_draft is not None:
                payload["divergencia_draft"] = divergencia_draft
            corpo = await self._surreal.query(
                f"CREATE evento CONTENT {json.dumps(payload)}")
            if corpo and corpo[0].get("status") != "OK":
                self._log(f"[FALHA SURREAL] {corpo}")
        except Exception as e:
            self._log(f"[FALHA SURREAL] {e}")

        # Título automático da sessão: primeira fala do usuário vira o título.
        if session is not None and ator.lower() != "lyra":
            await session.ensure_title(texto)

        # 2. Qdrant (busca semântica)
        try:
            from qdrant_client.models import PointStruct
            vetor = self._embed(texto)
            if vetor is None:
                raise RuntimeError("embed_service indisponível — episódio não vetorizado")
            qpayload = {
                "ator": ator, "texto": texto, "categoria": "episodio",
                "timestamp": agora.isoformat(), "fonte": fonte,
                "last_accessed_at": agora.isoformat(), "retrieval_count": 0,
                "intencao": _intencao,
            }
            if fontes_rag:
                qpayload["fontes_rag"] = fontes_rag
            if divergencia_draft is not None:
                qpayload["divergencia_draft"] = divergencia_draft
            self.qdrant_client.upsert(
                collection_name=QDRANT_COLLECTION,
                points=[PointStruct(id=evento_id, vector=vetor, payload=qpayload)]
            )
        except Exception as e:
            self._log(f"[FALHA QDRANT] {e}")

        # Grava relações de grafo (threading + tópicos) e avança o ponteiro.
        prev_id = self.last_event_id
        self.last_event_id = evento_id
        asyncio.create_task(self._save_graph_relations(evento_id, texto, prev_id))

    async def _save_graph_relations(self, evento_id: str, texto: str,
                                    prev_id: str | None) -> None:
        """evento->precedeu->anterior (threading) + evento->sobre->topico."""
        statements = []
        if prev_id:
            statements.append(
                f"RELATE evento:`{prev_id}` -> precedeu -> evento:`{evento_id}`;")
        for kw in extract_keywords(texto, n=5):
            kw_safe = re.sub(r"[^a-z0-9]", "", kw)[:30]
            if kw_safe:
                statements.append(
                    f"RELATE evento:`{evento_id}` -> sobre -> topico:`{kw_safe}`;")
        if not statements:
            return
        try:
            await self._surreal.query("\n".join(statements), timeout=5)
        except Exception as e:
            self._log(f"[GRAFO] Falha ao salvar relações: {e}")
