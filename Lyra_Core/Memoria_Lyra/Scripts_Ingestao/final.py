# -*- coding: utf-8 -*-
import asyncio, json, os, time, uuid

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vetorizacao.log")
_log_f = open(LOG_PATH, "w", encoding="utf-8", buffering=1)

def log(msg=""):
    _log_f.write(str(msg) + "\n")
    _log_f.flush()
    try:
        print(msg, flush=True)
    except Exception:
        pass

log("PASSO 0 - arquivo aberto, log funcionando")

# IMPORTANTE: pyarrow precisa carregar ANTES do torch — a ordem inversa causa
# access violation (0xc0000005) em arrow.dll no Windows, pois sentence_transformers
# importa pyarrow (via datasets) internamente e os runtimes nativos colidem.
import pyarrow
log("PASSO 0b - pyarrow importado")

import torch
log("PASSO 1 - torch importado, CUDA=" + str(torch.cuda.is_available()))

# IMPORTANTE: sentence_transformers precisa carregar ANTES do qdrant_client —
# a ordem inversa causa segfault nativo intermitente no Windows.
from sentence_transformers import SentenceTransformer
log("PASSO 2 - sentence_transformers importado")

from qdrant_client import QdrantClient
from qdrant_client.http import models
log("PASSO 3 - qdrant importado")

from surrealdb import AsyncSurreal, RecordID
log("PASSO 4 - surrealdb importado")

log("PASSO 5 - todos os imports OK")

DB_URL        = "ws://127.0.0.1:8090/rpc"  # 127.0.0.1: evita delay IPv6 do localhost
NS            = "lyra_core"
DB_NAME       = "Db_CORTEX"
COLLECTION    = "lyra_memory"
EMBED_MODEL   = "paraphrase-multilingual-MiniLM-L12-v2"
EMBED_DIM     = 384
BATCH_SURREAL = 500
ENCODE_BATCH  = 128
CHECKPOINT    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checkpoint_wiki.json")

def _load_checkpoint():
    if os.path.exists(CHECKPOINT):
        with open(CHECKPOINT, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_id": None, "total": 0}

def _save_checkpoint(last_id, total):
    with open(CHECKPOINT, "w", encoding="utf-8") as f:
        json.dump({"last_id": last_id, "total": total}, f, ensure_ascii=False)

def _ponto_uuid(titulo):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, titulo))

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
        log("   [QDRANT] Colecao criada.")
    else:
        log("   [QDRANT] Colecao ja existe.")

async def vetorizar():
    log("=" * 60)
    log("  LYRA - VETORIZACAO WIKIPEDIA (SurrealDB -> Qdrant)")
    log("=" * 60)

    # GPU: o crash nativo era causado pela ordem de import pyarrow/torch (corrigido
    # acima), não pela CUDA em si — confirmado estável 5/5 com a ordem corrigida.
    device = "cuda" if torch.cuda.is_available() else "cpu"
    log(f"   Dispositivo : {device.upper()}")
    model = SentenceTransformer(EMBED_MODEL, device=device)
    log("   Modelo carregado.")

    q = QdrantClient("localhost", port=6333, timeout=60)
    _garantir_colecao(q)

    ckpt   = _load_checkpoint()
    total  = ckpt["total"]
    ck_str = ckpt["last_id"]
    if ck_str:
        partes  = ck_str.split(":", 1)
        last_id = RecordID(partes[0], partes[1])
    else:
        last_id = None

    log(f"   Checkpoint: last_id={ck_str!r}, vetorizados={total:,}")
    log()

    async with AsyncSurreal(DB_URL) as db:
        await db.signin({"user": "root", "pass": "root"})
        await db.use(NS, DB_NAME)

        pagina = 0
        while True:
            if last_id is None:
                res = await db.query(
                    f"SELECT id, titulo, texto FROM wiki_conhecimento ORDER BY id LIMIT {BATCH_SURREAL}")
            else:
                res = await db.query(
                    f"SELECT id, titulo, texto FROM wiki_conhecimento WHERE id > $cursor ORDER BY id LIMIT {BATCH_SURREAL}",
                    {"cursor": last_id})

            registros = res if res else []
            if not registros:
                log("Vetorizacao concluida!")
                break

            pagina += 1
            titulos  = [r.get("titulo") or "Sem Titulo" for r in registros]
            textos   = [r.get("texto")  or ""           for r in registros]
            ids_surr = [str(r.get("id", ""))            for r in registros]

            validos = [(t, tx, sid) for t, tx, sid in zip(titulos, textos, ids_surr) if tx.strip()]

            if validos:
                tit_v, txt_v, sid_v = zip(*validos)
                embeddings = model.encode(list(txt_v), batch_size=ENCODE_BATCH,
                                          show_progress_bar=False, normalize_embeddings=True).tolist()
                points = [models.PointStruct(
                    id=_ponto_uuid(tit_v[i]), vector=embeddings[i],
                    payload={"titulo": tit_v[i], "texto": txt_v[i][:500], "surreal_id": sid_v[i],
                             "categoria": "conhecimento_geral", "fonte": "wikipedia_ptbr"}
                ) for i in range(len(tit_v))]
                _upsert_com_retry(q, points)
                total += len(points)

            last_id = registros[-1]["id"]
            _save_checkpoint(str(last_id), total)

            if pagina == 1:
                log(f"   [DEBUG] cursor lote 1: {last_id!r}")
            if pagina % 10 == 0:
                log(f"   [VETORES] {total:>8,} artigos | cursor: {last_id}")

    log(f"   Total: {total:,} artigos")
    log(f"   Checkpoint: {CHECKPOINT}")
    _log_f.close()

if __name__ == "__main__":
    log("PASSO 6 - entrando em asyncio.run")
    asyncio.run(vetorizar())
