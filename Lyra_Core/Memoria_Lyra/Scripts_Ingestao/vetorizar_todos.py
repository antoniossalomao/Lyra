# -*- coding: utf-8 -*-
"""
vetorizar_todos.py — Vetoriza todas as tabelas restantes do SurrealDB → Qdrant
Tabelas: base_codigo, base_instrucoes_ptbr, base_raciocinio, base_conversas
Mesma coleção lyra_memory — categoria no payload para filtro na busca.
"""
import asyncio, json, os, sys, time, uuid

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vetorizacao_todos.log")
_log_f = open(LOG_PATH, "w", encoding="utf-8", buffering=1)

def log(msg=""):
    _log_f.write(str(msg) + "\n")
    _log_f.flush()
    try:
        print(msg, flush=True)
    except Exception:
        pass

log("PASSO 0 - log aberto")

# IMPORTANTE: pyarrow precisa carregar ANTES do torch — a ordem inversa causa
# access violation (0xc0000005) em arrow.dll no Windows, pois sentence_transformers
# importa pyarrow (via datasets) internamente e os runtimes nativos colidem.
import pyarrow
log("PASSO 0b - pyarrow importado")

import torch
log("PASSO 1 - torch: CUDA=" + str(torch.cuda.is_available()))

# IMPORTANTE: sentence_transformers precisa carregar ANTES do qdrant_client —
# a ordem inversa causa segfault nativo intermitente no Windows.
from sentence_transformers import SentenceTransformer
log("PASSO 2 - sentence_transformers ok")

from qdrant_client import QdrantClient
from qdrant_client.http import models
log("PASSO 3 - qdrant ok")

from surrealdb import AsyncSurreal, RecordID
log("PASSO 4 - surrealdb ok")

# ── Configurações ─────────────────────────────────────────────────────────────
DB_URL        = "ws://127.0.0.1:8090/rpc"  # 127.0.0.1: evita delay IPv6 do localhost
NS            = "lyra_core"
DB_NAME       = "Db_CORTEX"
COLLECTION    = "lyra_memory"
EMBED_MODEL   = "paraphrase-multilingual-MiniLM-L12-v2"
EMBED_DIM     = 384
BATCH_SURREAL = 500
ENCODE_BATCH  = 128
_DIR          = os.path.dirname(os.path.abspath(__file__))

# Tabelas a processar (wiki_conhecimento já está feita, ver final.py)
TABELAS = [
    "base_codigo",
    "base_instrucoes_ptbr",
    "base_raciocinio",
    "base_conversas",
    "base_conhecimento_qa",
]

# --apenas tabela1,tabela2 restringe a execução a um subconjunto (resto do TABELAS é ignorado)
_apenas_arg = next((a for a in sys.argv if a.startswith("--apenas=")), None)
if _apenas_arg:
    _ids_pedidos = set(_apenas_arg.split("=", 1)[1].split(","))
    TABELAS = [t for t in TABELAS if t in _ids_pedidos]

def _ckpt_path(tabela):
    return os.path.join(_DIR, f"checkpoint_{tabela}.json")

def _load_ckpt(tabela):
    p = _ckpt_path(tabela)
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_id": None, "total": 0}

def _save_ckpt(tabela, last_id, total):
    with open(_ckpt_path(tabela), "w", encoding="utf-8") as f:
        json.dump({"last_id": last_id, "total": total}, f, ensure_ascii=False)

def _ponto_uuid(tabela, titulo):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{tabela}:{titulo}"))

def _upsert_com_retry(q, points, tentativas=5):
    """Upsert tolerante a timeouts/instabilidade transitória do Qdrant sob carga prolongada."""
    for i in range(tentativas):
        try:
            q.upsert(collection_name=COLLECTION, points=points)
            return
        except Exception as e:
            if i == tentativas - 1:
                raise
            espera = min(60, 2 ** i)
            log(f"   [QDRANT] upsert falhou ({e}), retry {i+1}/{tentativas} em {espera}s...")
            time.sleep(espera)

def _garantir_colecao(q):
    existentes = {c.name for c in q.get_collections().collections}
    if COLLECTION not in existentes:
        q.create_collection(collection_name=COLLECTION,
            vectors_config=models.VectorParams(size=EMBED_DIM, distance=models.Distance.COSINE))
        log(f"   [QDRANT] Coleção criada: {COLLECTION}")
    else:
        log(f"   [QDRANT] Coleção existe: {COLLECTION}")

async def vetorizar_tabela(db, q, model, tabela):
    log(f"\n{'='*60}")
    log(f"  TABELA: {tabela}")
    log(f"{'='*60}")

    ckpt    = _load_ckpt(tabela)
    total   = ckpt["total"]
    ck_str  = ckpt["last_id"]
    last_id = RecordID(*ck_str.split(":", 1)) if ck_str else None

    log(f"   Checkpoint: last_id={ck_str!r}, vetorizados={total:,}")

    pagina = 0
    while True:
        if last_id is None:
            res = await db.query(
                f"SELECT id, titulo, texto, categoria, fonte FROM {tabela} ORDER BY id LIMIT {BATCH_SURREAL}")
        else:
            res = await db.query(
                f"SELECT id, titulo, texto, categoria, fonte FROM {tabela} WHERE id > $cursor ORDER BY id LIMIT {BATCH_SURREAL}",
                {"cursor": last_id})

        registros = res if res else []
        if not registros:
            log(f"   [{tabela}] Concluída! Total: {total:,}")
            break

        pagina += 1
        titulos  = [r.get("titulo")   or "Sem Título" for r in registros]
        textos   = [r.get("texto")    or ""           for r in registros]
        cats     = [r.get("categoria") or tabela      for r in registros]
        fontes   = [r.get("fonte")    or tabela       for r in registros]
        ids_surr = [str(r.get("id", ""))              for r in registros]

        validos = [(t, tx, cat, fonte, sid)
                   for t, tx, cat, fonte, sid in zip(titulos, textos, cats, fontes, ids_surr)
                   if tx.strip()]

        if validos:
            tit_v, txt_v, cat_v, fonte_v, sid_v = zip(*validos)
            embeddings = model.encode(list(txt_v), batch_size=ENCODE_BATCH,
                                      show_progress_bar=False, normalize_embeddings=True).tolist()
            points = [models.PointStruct(
                id=_ponto_uuid(tabela, tit_v[i]),
                vector=embeddings[i],
                payload={
                    "titulo":     tit_v[i],
                    "texto":      txt_v[i][:500],
                    "categoria":  cat_v[i],
                    "fonte":      fonte_v[i],
                    "surreal_id": sid_v[i],
                    "tabela":     tabela,
                }
            ) for i in range(len(tit_v))]
            _upsert_com_retry(q, points)
            total += len(points)

        last_id = registros[-1]["id"]
        _save_ckpt(tabela, str(last_id), total)

        if pagina % 10 == 0:
            log(f"   [{tabela}] {total:>8,} vetores | cursor: {last_id}")

async def vetorizar():
    # GPU: o crash nativo era causado pela ordem de import pyarrow/torch (corrigido
    # acima), não pela CUDA em si — confirmado estável 5/5 com a ordem corrigida.
    device = "cuda" if torch.cuda.is_available() else "cpu"
    log(f"\n   Dispositivo: {device.upper()}")
    model = SentenceTransformer(EMBED_MODEL, device=device)
    log("   Modelo carregado.")

    q = QdrantClient("localhost", port=6333, timeout=60)
    _garantir_colecao(q)

    async with AsyncSurreal(DB_URL) as db:
        await db.signin({"user": "root", "pass": "root"})
        await db.use(NS, DB_NAME)
        log("   SurrealDB conectado.")

        for tabela in TABELAS:
            await vetorizar_tabela(db, q, model, tabela)

    # Total geral no Qdrant
    total_qdrant = q.get_collection(COLLECTION).points_count
    log(f"\n   TOTAL NO QDRANT ({COLLECTION}): {total_qdrant:,} vetores")
    _log_f.close()

if __name__ == "__main__":
    log("PASSO 5 - iniciando asyncio.run")
    asyncio.run(vetorizar())
