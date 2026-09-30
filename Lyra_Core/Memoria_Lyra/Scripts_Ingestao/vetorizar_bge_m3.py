# -*- coding: utf-8 -*-
"""
vetorizar_bge_m3.py — Re-vetoriza todo o conteudo do SurrealDB numa coleção NOVA e
paralela do Qdrant (lyra_memory_v2), usando BAAI/bge-m3 em vez do
paraphrase-multilingual-MiniLM-L12-v2 atual. A coleção lyra_memory original NAO e
tocada — zero risco para o que já está em produção. Roda isolado no venv_embed
(torch>=2.6, exigido pelo bge-m3 que só tem pesos .bin).
"""
import asyncio, json, os, sys, time, uuid

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vetorizacao_bge_m3.log")
_log_f = open(LOG_PATH, "a", encoding="utf-8", buffering=1)

def log(msg=""):
    _log_f.write(str(msg) + "\n")
    _log_f.flush()
    try:
        print(msg, flush=True)
    except Exception:
        pass

log(f"\n{'='*60}\nINICIO {time.strftime('%Y-%m-%d %H:%M:%S')}\n{'='*60}")

import pyarrow  # precisa vir antes do torch — ver LYRA_TECNICO.md §2
log("pyarrow ok")

import torch
log(f"torch ok, CUDA={torch.cuda.is_available()}")

from sentence_transformers import SentenceTransformer
log("sentence_transformers ok")

from qdrant_client import QdrantClient
from qdrant_client.http import models
log("qdrant ok")

from surrealdb import AsyncSurreal, RecordID
log("surrealdb ok")

DB_URL      = "ws://127.0.0.1:8090/rpc"
NS          = "lyra_core"
DB_NAME     = "Db_CORTEX"
COLLECTION  = "lyra_memory_v2"
EMBED_MODEL = "BAAI/bge-m3"
EMBED_DIM   = 1024
BATCH_SURREAL = 1000
ENCODE_BATCH  = 32    # wiki tem textos mais longos que base_codigo — batch 64 estourava VRAM; 32 deixa ~2GB de margem
MAX_SEQ_LEN   = 512   # wiki: 512 tokens são suficientes pra capturar semântica, economiza ~40% de VRAM vs 1024
_DIR = os.path.dirname(os.path.abspath(__file__))

# tabela -> (campos extras de payload, esquema de id)
TABELAS_PADRAO = ["base_codigo", "base_instrucoes_ptbr", "base_raciocinio",
                   "base_conversas", "base_conhecimento_qa"]

_apenas_arg = next((a for a in sys.argv if a.startswith("--apenas=")), None)
_so_wiki    = "--apenas-wiki" in sys.argv
_sem_wiki   = "--sem-wiki" in sys.argv
_forcar_cpu = "--cpu" in sys.argv  # libera a GPU pro usuário sem parar o pipeline

def _ckpt_path(nome):
    return os.path.join(_DIR, f"checkpoint_v2_{nome}.json")

def _load_ckpt(nome):
    p = _ckpt_path(nome)
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_id": None, "total": 0}

def _save_ckpt(nome, last_id, total):
    with open(_ckpt_path(nome), "w", encoding="utf-8") as f:
        json.dump({"last_id": last_id, "total": total}, f, ensure_ascii=False)

def _ponto_uuid(surreal_id):
    # BUG CORRIGIDO: antes hasheava o título da linha, não o ID. Linhas com
    # título repetido (comum em datasets de instrução, onde milhares de
    # exemplos reaproveitam o mesmo system prompt) geravam o mesmo UUID e
    # se sobrescreviam silenciosamente via upsert — perda de dados sem erro
    # nenhum no log. O ID do SurrealDB (já único por natureza, com a tabela
    # embutida no formato "tabela:id") é a chave correta.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, surreal_id))

_cpu_fallback = {"ativo": False}

VRAM_LIMITE_MB = 6656  # teto pedido pelo usuário (6.5GB) — placa tem 8192MB, mas reservando margem

def _encode_seguro(model_gpu, model_cpu, textos):
    """Encode com fallback automático pra CPU se a GPU estourar VRAM no meio da noite."""
    if _cpu_fallback["ativo"]:
        return model_cpu.encode(textos, batch_size=ENCODE_BATCH, show_progress_bar=False, normalize_embeddings=True)
    # memory_allocated() = uso real; memory_reserved() inclui buffers internos do PyTorch
    # e pode disparar falso positivo de OOM mesmo com VRAM disponível — por isso allocated()
    if torch.cuda.is_available() and torch.cuda.memory_allocated() / 1024 / 1024 > VRAM_LIMITE_MB:
        log(f"   [AVISO] VRAM reservada passou de {VRAM_LIMITE_MB}MB preventivamente — caindo pra CPU pelo resto da execução.")
        _cpu_fallback["ativo"] = True
        torch.cuda.empty_cache()
        return model_cpu.encode(textos, batch_size=ENCODE_BATCH, show_progress_bar=False, normalize_embeddings=True)
    try:
        return model_gpu.encode(textos, batch_size=ENCODE_BATCH, show_progress_bar=False, normalize_embeddings=True)
    except torch.cuda.OutOfMemoryError:
        log("   [AVISO] CUDA OOM — limpando cache e tentando 1x mais na GPU...")
        torch.cuda.empty_cache()
        try:
            return model_gpu.encode(textos, batch_size=ENCODE_BATCH, show_progress_bar=False, normalize_embeddings=True)
        except torch.cuda.OutOfMemoryError:
            log("   [AVISO] CUDA OOM de novo — caindo pra CPU pelo resto da execução (mais lento, mas não trava).")
            _cpu_fallback["ativo"] = True
            torch.cuda.empty_cache()
            return model_cpu.encode(textos, batch_size=ENCODE_BATCH, show_progress_bar=False, normalize_embeddings=True)

def _upsert_com_retry(q, points, tentativas=6):
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
        log(f"   [QDRANT] Coleção já existe: {COLLECTION}")


class ConexaoResiliente:
    """Wrapper sobre AsyncSurreal que reconecta automaticamente se o websocket cair
    (ex: o SurrealDB foi reiniciado, ou a conexão ficou idle demais e morreu) —
    sem isso, qualquer queda de conexão durante a noite mata o processo inteiro."""

    def __init__(self):
        self.db = None

    async def _conectar(self):
        db = AsyncSurreal(DB_URL)
        await db.connect()
        await db.signin({"user": "root", "pass": "root"})
        await db.use(NS, DB_NAME)
        self.db = db

    async def query(self, q_str, params=None, tentativas=8):
        for i in range(tentativas):
            try:
                if self.db is None:
                    await self._conectar()
                return await (self.db.query(q_str, params) if params else self.db.query(q_str))
            except Exception as e:
                log(f"   [SURREAL] conexão falhou ({e}) — reconectando, tentativa {i+1}/{tentativas}...")
                try:
                    if self.db:
                        await self.db.close()
                except Exception:
                    pass
                self.db = None
                if i == tentativas - 1:
                    raise
                time.sleep(min(60, 2 ** i))

    async def fechar(self):
        try:
            if self.db:
                await self.db.close()
        except Exception:
            pass


async def vetorizar_tabela_padrao(db, q, model_gpu, model_cpu, tabela):
    log(f"\n{'='*60}\n  TABELA: {tabela}\n{'='*60}")
    ckpt = _load_ckpt(tabela)
    total, ck_str = ckpt["total"], ckpt["last_id"]
    last_id = RecordID(*ck_str.split(":", 1)) if ck_str else None
    log(f"   Checkpoint: last_id={ck_str!r}, vetorizados={total:,}")

    pagina = 0
    while True:
        if last_id is None:
            res = await db.query(f"SELECT id, titulo, texto, categoria, fonte FROM {tabela} ORDER BY id LIMIT {BATCH_SURREAL}")
        else:
            res = await db.query(
                f"SELECT id, titulo, texto, categoria, fonte FROM {tabela} WHERE id > $cursor ORDER BY id LIMIT {BATCH_SURREAL}",
                {"cursor": last_id})
        registros = res if res else []
        if not registros:
            log(f"   [{tabela}] Concluída! Total: {total:,}")
            break

        pagina += 1
        titulos  = [r.get("titulo")     or "Sem Título" for r in registros]
        textos   = [r.get("texto")     or ""           for r in registros]
        cats     = [r.get("categoria") or tabela        for r in registros]
        fontes   = [r.get("fonte")     or tabela        for r in registros]
        ids_surr = [str(r.get("id", ""))                for r in registros]

        validos = [(t, tx, cat, fonte, sid) for t, tx, cat, fonte, sid in zip(titulos, textos, cats, fontes, ids_surr) if tx.strip()]
        if validos:
            tit_v, txt_v, cat_v, fonte_v, sid_v = zip(*validos)
            embeddings = _encode_seguro(model_gpu, model_cpu, list(txt_v)).tolist()
            points = [models.PointStruct(
                id=_ponto_uuid(sid_v[i]),
                vector=embeddings[i],
                payload={"titulo": tit_v[i], "texto": txt_v[i][:500], "categoria": cat_v[i],
                         "fonte": fonte_v[i], "surreal_id": sid_v[i], "tabela": tabela}
            ) for i in range(len(tit_v))]
            _upsert_com_retry(q, points)
            total += len(points)

        last_id = registros[-1]["id"]
        _save_ckpt(tabela, str(last_id), total)
        if pagina % 5 == 0 and torch.cuda.is_available():
            torch.cuda.empty_cache()
        if pagina % 10 == 0:
            log(f"   [{tabela}] {total:>8,} vetores | cursor: {last_id} | VRAM alocada: {torch.cuda.memory_allocated()/1024/1024:.0f}MB")

async def vetorizar_wiki(db, q, model_gpu, model_cpu):
    nome = "wiki_conhecimento"
    log(f"\n{'='*60}\n  TABELA: {nome}\n{'='*60}")
    ckpt = _load_ckpt(nome)
    total, ck_str = ckpt["total"], ckpt["last_id"]
    last_id = RecordID(*ck_str.split(":", 1)) if ck_str else None
    log(f"   Checkpoint: last_id={ck_str!r}, vetorizados={total:,}")

    pagina = 0
    while True:
        if last_id is None:
            res = await db.query(f"SELECT id, titulo, texto FROM {nome} ORDER BY id LIMIT {BATCH_SURREAL}")
        else:
            res = await db.query(
                f"SELECT id, titulo, texto FROM {nome} WHERE id > $cursor ORDER BY id LIMIT {BATCH_SURREAL}",
                {"cursor": last_id})
        registros = res if res else []
        if not registros:
            log(f"   [{nome}] Concluída! Total: {total:,}")
            break

        pagina += 1
        titulos  = [r.get("titulo") or "Sem Título" for r in registros]
        textos   = [r.get("texto")  or ""           for r in registros]
        ids_surr = [str(r.get("id", ""))            for r in registros]
        validos = [(t, tx, sid) for t, tx, sid in zip(titulos, textos, ids_surr) if tx.strip()]
        if validos:
            tit_v, txt_v, sid_v = zip(*validos)
            embeddings = _encode_seguro(model_gpu, model_cpu, list(txt_v)).tolist()
            points = [models.PointStruct(
                id=_ponto_uuid(sid_v[i]), vector=embeddings[i],
                payload={"titulo": tit_v[i], "texto": txt_v[i][:500], "surreal_id": sid_v[i],
                         "categoria": "conhecimento_geral", "fonte": "wikipedia_ptbr"}
            ) for i in range(len(tit_v))]
            _upsert_com_retry(q, points)
            total += len(points)

        last_id = registros[-1]["id"]
        _save_ckpt(nome, str(last_id), total)
        if pagina % 5 == 0 and torch.cuda.is_available():
            torch.cuda.empty_cache()
        if pagina % 20 == 0:
            log(f"   [{nome}] {total:>8,} vetores | cursor: {last_id} | VRAM alocada: {torch.cuda.memory_allocated()/1024/1024:.0f}MB")

async def vetorizar():
    device_gpu = "cpu" if _forcar_cpu else ("cuda" if torch.cuda.is_available() else "cpu")
    log(f"\n   Dispositivo principal: {device_gpu.upper()}  |  modelo: {EMBED_MODEL}")
    model_kwargs_gpu = {"torch_dtype": torch.float16} if device_gpu == "cuda" else {}
    model_gpu = SentenceTransformer(EMBED_MODEL, device=device_gpu, model_kwargs=model_kwargs_gpu)
    model_gpu.max_seq_length = MAX_SEQ_LEN
    model_cpu = model_gpu if device_gpu == "cpu" else SentenceTransformer(EMBED_MODEL, device="cpu")
    model_cpu.max_seq_length = MAX_SEQ_LEN
    log(f"   Modelo carregado (GPU + fallback CPU prontos). max_seq_length={MAX_SEQ_LEN}, encode_batch={ENCODE_BATCH}")

    q = QdrantClient("127.0.0.1", port=6333, timeout=120)
    _garantir_colecao(q)

    db = ConexaoResiliente()
    await db.query("RETURN 1")  # força a primeira conexão e confirma que está saudável
    log("   SurrealDB conectado (com reconexão automática habilitada).")

    tabelas = TABELAS_PADRAO
    if _apenas_arg:
        ids_pedidos = set(_apenas_arg.split("=", 1)[1].split(","))
        tabelas = [t for t in tabelas if t in ids_pedidos]

    if not _so_wiki:
        for tabela in tabelas:
            await vetorizar_tabela_padrao(db, q, model_gpu, model_cpu, tabela)

    if _so_wiki or (not _sem_wiki and not _apenas_arg):
        await vetorizar_wiki(db, q, model_gpu, model_cpu)

    await db.fechar()

    total_qdrant = q.get_collection(COLLECTION).points_count
    log(f"\n   TOTAL NO QDRANT ({COLLECTION}): {total_qdrant:,} vetores")
    log(f"   CPU fallback foi ativado: {_cpu_fallback['ativo']}")
    log("   CONCLUIDO_OK")
    _log_f.close()

if __name__ == "__main__":
    # Rede de segurança extra: qualquer erro não tratado (driver da GPU, Qdrant
    # reiniciando, etc.) reinicia o processo do checkpoint em vez de morrer de vez —
    # seguro pq os checkpoints + IDs determinísticos tornam tudo idempotente.
    _tentativa = 0
    while True:
        try:
            asyncio.run(vetorizar())
            break
        except Exception as e:
            _tentativa += 1
            log(f"\n   [FATAL] processo caiu ({e!r}) — reiniciando do checkpoint em 30s (tentativa {_tentativa})...")
            time.sleep(30)
