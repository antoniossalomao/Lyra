"""
bm25_index.py — Índice lexical (BM25) sobre o payload já existente no Qdrant.
Usado pelo cerebro_maestro.py para busca híbrida (BM25 + denso) via RRF.

Implementação: bm25s (esparso, nativo/numpy+scipy) — substituiu rank_bm25 puro
em 26/06/2026. rank_bm25 pontuava TODOS os ~3M docs por query (~1.4s); bm25s
usa matriz esparsa e devolve top-k direto (~10-50ms). Load via mmap = boot
rápido e pouca RAM pro índice. Não depende de GPU/torch.
"""
import os
import pickle

import bm25s

_DIR        = os.path.dirname(os.path.abspath(__file__))
_INDEX_DIR  = os.path.join(_DIR, "bm25s_index")     # matriz esparsa + vocab (bm25s.save)
_META_PATH  = os.path.join(_DIR, "bm25s_meta.pkl")  # ids do Qdrant + metas (titulo/categoria/fonte/texto)

# Mantém token_pattern/stopwords explícitos pra query e corpus tokenizarem igual.
_TOKENIZE_KW = dict(stopwords=None, stemmer=None, show_progress=False)


def construir_indice(qdrant_client, collection: str = "lyra_memory_v2", batch_size: int = 2000, log=print,
                     out_dir: str | None = None, out_meta: str | None = None):
    """Varre toda a coleção do Qdrant via scroll e constrói o índice bm25s, salvando em disco.

    out_dir/out_meta: destino alternativo do save. Necessário quando o
    cerebro_maestro está rodando — ele carrega o índice com mmap=True no
    STARTUP (não lazy) e o Windows recusa truncar arquivo com seção mapeada
    (erro 1224 → OSError errno 22). Fluxo: buildar pra pasta nova com o
    cerebro no ar, parar o cerebro, swap das pastas, subir de novo (~s de
    downtime em vez de ~25min).
    """
    ids, corpus, metas = [], [], []
    offset = None
    total = 0

    while True:
        pontos, offset = qdrant_client.scroll(
            collection_name=collection,
            limit=batch_size,
            offset=offset,
            with_payload=["titulo", "texto", "categoria", "fonte"],
            with_vectors=False,
        )
        if not pontos:
            break

        for p in pontos:
            payload = p.payload or {}
            titulo = payload.get("titulo", "") or ""
            texto  = payload.get("texto", "") or ""
            ids.append(p.id)
            corpus.append(f"{titulo} {texto}")
            metas.append({
                "titulo":    titulo,
                "categoria": payload.get("categoria", ""),
                "fonte":     payload.get("fonte", ""),
                "texto":     texto,
            })

        total += len(pontos)
        if total % 50000 == 0:
            log(f"   [BM25] {total:,} documentos lidos...")

        if offset is None:
            break

    log(f"   [BM25] Tokenizando e indexando {total:,} documentos (bm25s)...")
    corpus_tokens = bm25s.tokenize(corpus, **_TOKENIZE_KW)
    retriever = bm25s.BM25()
    retriever.index(corpus_tokens, show_progress=False)

    destino_idx  = out_dir or _INDEX_DIR
    destino_meta = out_meta or _META_PATH
    retriever.save(destino_idx)
    with open(destino_meta, "wb") as f:
        pickle.dump({"ids": ids, "metas": metas}, f, protocol=pickle.HIGHEST_PROTOCOL)

    log(f"   [BM25] Índice salvo em {destino_idx} ({total:,} docs).")
    return total


def carregar_indice(log=print):
    if not (os.path.isdir(_INDEX_DIR) and os.path.exists(_META_PATH)):
        log("   [BM25] Índice bm25s não encontrado em disco — busca híbrida ficará só com o vetorial.")
        return None
    # mmap=True: carrega a matriz esparsa memory-mapped (boot rápido, baixa RAM).
    retriever = bm25s.BM25.load(_INDEX_DIR, mmap=True)
    with open(_META_PATH, "rb") as f:
        meta = pickle.load(f)
    log(f"   [BM25] Índice carregado: {len(meta['ids']):,} documentos (bm25s, mmap).")
    return {"retriever": retriever, "ids": meta["ids"], "metas": meta["metas"]}


def buscar_bm25(indice, query: str, top_k: int = 10):
    """Retorna lista de (id_qdrant, score_bm25, meta) ordenada por relevância."""
    if indice is None:
        return []
    n_docs = len(indice["ids"])
    k = min(top_k, n_docs)
    if k <= 0:
        return []
    try:
        query_tokens = bm25s.tokenize(query, **_TOKENIZE_KW)
        # Query sem token válido (ex: só pontuação/stopword) → sem busca lexical.
        ids0 = getattr(query_tokens, "ids", None)
        if ids0 is not None and (len(ids0) == 0 or len(ids0[0]) == 0):
            return []
        # retrieve devolve (indices, scores) com shape (1, k) p/ uma query.
        resultados, scores = indice["retriever"].retrieve(query_tokens, k=k, show_progress=False)
    except Exception:
        return []
    saida = []
    for idx, sc in zip(resultados[0], scores[0]):
        if sc > 0:
            i = int(idx)
            saida.append((indice["ids"][i], float(sc), indice["metas"][i]))
    return saida


def fusao_rrf(resultados_dense, resultados_bm25, k: int = 60, top_k: int = 5):
    """
    Reciprocal Rank Fusion: combina dois rankings (denso + lexical) sem precisar
    normalizar escalas diferentes (cosseno 0-1 vs score BM25 sem limite superior).
    rrf_score(doc) = soma de 1/(k + rank) em cada ranking onde o doc aparece.
    """
    rrf_scores = {}
    doc_info = {}

    for rank, (ponto_id, score, payload) in enumerate(resultados_dense, start=1):
        rrf_scores[ponto_id] = rrf_scores.get(ponto_id, 0.0) + 1.0 / (k + rank)
        doc_info[ponto_id] = {"payload": payload, "dense_score": score, "bm25_score": None}

    for rank, (ponto_id, score, meta) in enumerate(resultados_bm25, start=1):
        rrf_scores[ponto_id] = rrf_scores.get(ponto_id, 0.0) + 1.0 / (k + rank)
        if ponto_id in doc_info:
            doc_info[ponto_id]["bm25_score"] = score
        else:
            doc_info[ponto_id] = {"payload": meta, "dense_score": None, "bm25_score": score}

    ordenados = sorted(rrf_scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    return [{"id": pid, "rrf_score": round(s, 5), **doc_info[pid]} for pid, s in ordenados]
