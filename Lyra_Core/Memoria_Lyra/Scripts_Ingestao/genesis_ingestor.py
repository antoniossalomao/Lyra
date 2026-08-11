"""
genesis_ingestor.py — Indexa os arquivos do Projeto Lyra no Qdrant
Lyra aprende sobre ela mesma: código, config e LYRA_GENESIS_V2.md
"""
import os, sys, uuid, json, time, hashlib
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── Env vars ANTES de qualquer import ──
os.environ["TOKENIZERS_PARALLELISM"]            = "false"
os.environ["TRANSFORMERS_OFFLINE"]              = "1"
os.environ["HF_HUB_OFFLINE"]                   = "1"
os.environ["HF_DATASETS_OFFLINE"]              = "1"
os.environ["TRANSFORMERS_VERBOSITY"]            = "error"
os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"

# ── Log file PRIMEIRO — antes de sentence_transformers ──
_DIR      = os.path.dirname(os.path.abspath(__file__))
_LOG_PATH = os.path.join(_DIR, "genesis_ingestor.log")
_log_f    = open(_LOG_PATH, "w", encoding="utf-8")

def log(msg=""):
    _log_f.write(str(msg) + "\n")
    _log_f.flush()
    try: print(msg, flush=True)
    except Exception: pass

log("[START] genesis_ingestor iniciando...")
log("[1/5] Importando sentence_transformers (10-30s)...")

# IMPORTANTE: pyarrow precisa carregar ANTES do torch — a ordem inversa causa
# access violation (0xc0000005) em arrow.dll no Windows.
import pyarrow
from sentence_transformers import SentenceTransformer

log("[2/5] sentence_transformers OK.")
log("[3/5] Importando qdrant_client...")

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

log("[4/5] Imports OK.")

# ── Checkpoint ──
_CKPT = os.path.join(_DIR, "checkpoint_genesis.json")
def _load_ckpt():
    try: return set(json.load(open(_CKPT)))
    except: return set()
def _save_ckpt(done):
    json.dump(list(done), open(_CKPT, "w"))

# ── Extensões suportadas ──
EXT_CAT = {
    ".py":   "codigo_python",
    ".js":   "codigo_js",
    ".ts":   "codigo_ts",
    ".md":   "documentacao",
    ".txt":  "documentacao",
    ".json": "config",
    ".yaml": "config",
    ".yml":  "config",
    ".toml": "config",
    ".ps1":  "script",
    ".sh":   "script",
    ".html": "web",
    ".css":  "web",
    ".sql":  "banco_de_dados",
}

IGNORAR_DIRS = {
    "__pycache__", ".git", "node_modules", ".venv", "venv", "env",
    ".idea", ".vscode", "dist", "build", ".next", "target",
    "bin", "obj", ".mypy_cache", "site-packages",
}

def _ler(path):
    for enc in ("utf-8", "latin-1"):
        try:
            return open(path, encoding=enc).read()
        except UnicodeDecodeError:
            continue
        except Exception as e:
            log(f"  [erro leitura] {Path(path).name}: {e}")
            return ""
    return ""

def processar_arquivo(path, qdrant, emb, done):
    path  = os.path.abspath(path)
    ext   = Path(path).suffix.lower()
    if ext not in EXT_CAT or not os.path.exists(path):
        return 0
    chave = hashlib.md5(path.encode()).hexdigest()
    if chave in done:
        return 0

    texto = _ler(path)
    if not texto or len(texto.strip()) < 30:
        return 0

    chunks, i = [], 0
    while i < len(texto):
        c = texto[i:i+1200].strip()
        if c: chunks.append(c)
        i += 1000

    cat  = EXT_CAT.get(ext, "documento")
    nome = Path(path).name
    pontos = [
        PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"genesis:{path}:{idx}")),
            vector=emb.encode(chunk).tolist(),
            payload={"titulo": nome, "texto": chunk,
                     "fonte": path, "categoria": cat}
        )
        for idx, chunk in enumerate(chunks)
    ]
    qdrant.upsert("lyra_memory", points=pontos)
    done.add(chave)
    return len(chunks)

def processar_pasta(pasta, qdrant, emb, done, label=""):
    pasta = os.path.abspath(pasta)
    if not os.path.isdir(pasta):
        log(f"  [SKIP] não existe: {pasta}")
        return 0

    arqs = []
    for raiz, dirs, files in os.walk(pasta):
        dirs[:] = [d for d in dirs if d not in IGNORAR_DIRS]
        for f in files:
            if Path(f).suffix.lower() not in EXT_CAT: continue
            p = os.path.join(raiz, f)
            try:
                if os.path.getsize(p) < 5 * 1024 * 1024:
                    arqs.append(p)
            except OSError:
                pass

    novos = sum(1 for a in arqs
                if hashlib.md5(os.path.abspath(a).encode()).hexdigest() not in done)
    log(f"\n[PASTA] {label or pasta}")
    log(f"  {len(arqs)} arquivos elegíveis, {novos} novos")
    if novos == 0:
        return 0

    t0 = time.time()
    total = 0
    for arq in arqs:
        n = processar_arquivo(arq, qdrant, emb, done)
        if n:
            total += n
            log(f"  ✓ {Path(arq).name} → {n} chunks")
    _save_ckpt(done)
    log(f"  Total: {total} chunks em {time.time()-t0:.1f}s")
    return total


if __name__ == "__main__":
    t0 = time.time()

    log("\n[5/5] Conectando Qdrant...")
    qdrant = QdrantClient("localhost", port=6333, timeout=60)
    cols   = [c.name for c in qdrant.get_collections().collections]
    if "lyra_memory" not in cols:
        qdrant.create_collection(
            "lyra_memory",
            vectors_config=VectorParams(size=384, distance=Distance.COSINE))
        log("[OK] Coleção lyra_memory criada.")
    else:
        n = qdrant.count("lyra_memory").count
        log(f"[OK] lyra_memory: {n:,} vetores existentes.")

    log("\n[EMB] Carregando embedder na GPU...")
    emb  = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2", device="cuda")
    log("[OK] Embedder pronto.")

    done = _load_ckpt()
    log(f"[OK] Checkpoint: {len(done)} arquivos já processados.")

    log("\n" + "="*50)
    log("  INDEXANDO: Projeto Lyra")
    log("="*50)

    total = processar_pasta(
        r"C:\Lyra_Project",
        qdrant, emb, done,
        label="C:\\Lyra_Project"
    )

    _save_ckpt(done)

    n_final = qdrant.count("lyra_memory").count
    log(f"\n{'='*50}")
    log(f"  CONCLUÍDO")
    log(f"  Chunks indexados: {total}")
    log(f"  Total vetores:    {n_final:,}")
    log(f"  Tempo:            {time.time()-t0:.1f}s")
    log(f"{'='*50}")
    _log_f.close()
