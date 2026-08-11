# -*- coding: utf-8 -*-
"""
embed_service.py — Microserviço de embedding BGE-M3 (FastAPI :8001)

Processo separado do cerebro_maestro (fault isolation + idle-unload de VRAM) —
não mais um venv isolado (venv_embed foi aposentado em 30/06/2026: o Python
global do projeto foi atualizado pra torch 2.6+cu124, exigido pelo bge-m3 por
só ter pesos .bin sem safetensors). Roda no mesmo interpretador do
cerebro_maestro agora, só como processo à parte.

ECONOMIA DE VRAM (idle-unload): o modelo só ocupa a GPU enquanto há uso. Após
IDLE_TIMEOUT segundos sem nenhuma chamada /embed, ele é descarregado e a VRAM
liberada. A próxima chamada recarrega (lazy). Assim a VRAM fica livre quando a
Lyra está ociosa — só a 1ª query após uma pausa paga o reload.

Uso (Python global do projeto):
    python embed_service.py                 # GPU, idle-unload 300s
    python embed_service.py --idle 600      # timeout custom
    python embed_service.py --cpu           # força CPU (sem VRAM, ~2.2s/query)
    python embed_service.py --no-unload     # mantém sempre carregado

RERANKER (bge-reranker-v2-m3): além do embedding denso, este serviço também
serve um cross-encoder de reranking. O RAG híbrido usa ele como 3º estágio
(depois de BM25+denso fundidos por RRF) pra repontuar os candidatos olhando
query e documento JUNTOS — bem mais preciso que similaridade de cosseno. Mesmo
esquema de lazy load + idle-unload (compartilha o watcher e o _ultimo_uso).

Endpoints:
    GET  /health                       -> {ok, device, modelo, dim, carregado, vram_mb, reranker_*}
    POST /embed {texto}                -> {vetor: [1024]}
    POST /embed {textos:[]}            -> {vetores: [[1024], ...]}
    POST /rerank {query, documentos:[]}-> {scores: [float]}  (logit de relevância por doc)
    POST /unload                       -> descarrega ambos manualmente (libera VRAM já)
"""
import sys
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor

# pyarrow antes de torch — access violation no Windows (ver LYRA_TECNICO)
import pyarrow  # noqa: F401
import torch
from sentence_transformers import SentenceTransformer, CrossEncoder

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

# CRÍTICO: todas as operações CUDA (load + encode) rodam neste ÚNICO worker.
# Sem isso, endpoints sync do FastAPI rodam em threads diferentes do threadpool
# e o contexto CUDA não fica quente entre chamadas — latência salta de ~25ms
# pra ~2000ms por query. Fixar num só thread mantém o contexto/stream consistente.
_gpu_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bge")

EMBED_MODEL  = "BAAI/bge-m3"
EMBED_DIM    = 1024
MAX_SEQ_LEN  = 512  # MESMO valor da vetorização — vetor de query precisa casar com o indexado
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"  # cross-encoder de reranking (mesma família)
RERANK_MAX_LEN = 512
_FORCAR_CPU = "--cpu" in sys.argv
_NO_UNLOAD  = "--no-unload" in sys.argv

def _arg(flag, default):
    if flag in sys.argv:
        try:
            return int(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            pass
    return default

IDLE_TIMEOUT = _arg("--idle", 300)  # segundos sem uso antes de descarregar da VRAM

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

app = FastAPI()
_model = None
_model_parked = None   # embedder estacionado na RAM (idle-unload parcial, ~2.3GB)
_reranker = None
_device = "cpu"
_lock = threading.Lock()
_ultimo_uso = 0.0


class EmbedRequest(BaseModel):
    texto: str | None = None
    textos: list[str] | None = None


class RerankRequest(BaseModel):
    query: str
    documentos: list[str]


def _resolver_device():
    return "cpu" if _FORCAR_CPU else ("cuda" if torch.cuda.is_available() else "cpu")


def _garantir_modelo():
    """Carrega o modelo se ainda não estiver na memória (lazy load).
    Se estiver estacionado na RAM (_model_parked), só move de volta pra GPU
    (~1-2s via PCIe) em vez de recarregar do disco (~10-15s)."""
    global _model, _device, _ultimo_uso
    with _lock:
        _ultimo_uso = time.monotonic()
        if _model is not None:
            return
        _device = _resolver_device()
        global _model_parked
        if _model_parked is not None and _device == "cuda":
            print("[EMBED] Reativando modelo estacionado na RAM -> GPU...", flush=True)
            t0 = time.monotonic()
            m = _model_parked
            _model_parked = None
            m.to("cuda")
            _model = m
            print(f"[EMBED] Reativado em {time.monotonic()-t0:.1f}s.", flush=True)
            return
        kwargs = {"torch_dtype": torch.float16} if _device == "cuda" else {}
        print(f"[EMBED] Carregando {EMBED_MODEL} em {_device}...", flush=True)
        t0 = time.monotonic()
        m = SentenceTransformer(EMBED_MODEL, device=_device, model_kwargs=kwargs)
        m.max_seq_length = MAX_SEQ_LEN
        _model = m
        print(f"[EMBED] Pronto em {time.monotonic()-t0:.1f}s. dim={EMBED_DIM}", flush=True)


def _garantir_reranker():
    """Carrega o cross-encoder de reranking se ainda não estiver na memória (lazy)."""
    global _reranker, _device, _ultimo_uso
    with _lock:
        _ultimo_uso = time.monotonic()
        if _reranker is not None:
            return
        _device = _resolver_device()
        kwargs = {"torch_dtype": torch.float16} if _device == "cuda" else {}
        print(f"[EMBED] Carregando reranker {RERANK_MODEL} em {_device}...", flush=True)
        t0 = time.monotonic()
        r = CrossEncoder(RERANK_MODEL, device=_device, max_length=RERANK_MAX_LEN,
                         model_kwargs=kwargs)
        _reranker = r
        print(f"[EMBED] Reranker pronto em {time.monotonic()-t0:.1f}s.", flush=True)


def _descarregar_impl():
    """Libera a VRAM no idle. O embedder é ESTACIONADO na RAM (~2.3GB fp16,
    máquina tem 64GB) em vez de descartado — a reativação vira um .to('cuda')
    de ~1-2s via PCIe em vez de reload do disco de ~10-15s, que era o cold
    start sentido na 1ª busca RAG depois de qualquer pausa (achado 04/08/2026:
    /buscar dava timeout de 10s pós-idle). O reranker continua com unload
    completo: é menos usado (só 3º estágio do RAG) e manter os dois na RAM
    não compensa."""
    global _model, _model_parked, _reranker
    import gc
    with _lock:
        if _model is None and _reranker is None:
            return False
        if _model is not None:
            try:
                _model.to("cpu")
                _model_parked = _model
            except Exception as e:
                print(f"[EMBED] Falha ao estacionar na RAM ({e}) — unload completo.", flush=True)
                _model_parked = None
        _model = None
        _reranker = None
        gc.collect()  # libera as refs dos modelos ANTES do empty_cache, senão a VRAM não cai
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print(f"[EMBED] VRAM liberada — embedder {'estacionado na RAM' if _model_parked is not None else 'descarregado'}.", flush=True)
        return True


def _descarregar():
    """Roda no mesmo worker do encode/load — contexto CUDA consistente."""
    return _gpu_executor.submit(_descarregar_impl).result()


def _vram_mb():
    if _device == "cuda" and torch.cuda.is_available():
        return round(torch.cuda.memory_allocated() / 1024 / 1024)
    return 0


def _watcher_idle():
    """Descarrega o modelo após IDLE_TIMEOUT sem uso."""
    while True:
        time.sleep(30)
        if _NO_UNLOAD or (_model is None and _reranker is None):
            continue
        if time.monotonic() - _ultimo_uso > IDLE_TIMEOUT:
            _descarregar()


@app.on_event("startup")
def _startup():
    print(f"[EMBED] Serviço :8001 | device-alvo={_resolver_device()} | "
          f"idle_unload={'OFF' if _NO_UNLOAD else str(IDLE_TIMEOUT)+'s'}", flush=True)
    if not _NO_UNLOAD:
        threading.Thread(target=_watcher_idle, daemon=True).start()
    # Não carrega no startup — lazy na 1ª query (economiza VRAM até precisar)


@app.get("/health")
def health():
    return {"ok": True, "device": _device, "modelo": EMBED_MODEL, "dim": EMBED_DIM,
            "carregado": _model is not None, "estacionado_ram": _model_parked is not None,
            "vram_mb": _vram_mb(),
            "reranker_modelo": RERANK_MODEL, "reranker_carregado": _reranker is not None,
            "idle_timeout": None if _NO_UNLOAD else IDLE_TIMEOUT}


def _encode(payload):
    """Roda no worker único do _gpu_executor — contexto CUDA consistente."""
    _garantir_modelo()
    if payload.get("textos") is not None:
        vetores = _model.encode(payload["textos"], normalize_embeddings=True,
                                show_progress_bar=False).tolist()
        return {"vetores": vetores, "n": len(vetores)}
    vetor = _model.encode(payload["texto"], normalize_embeddings=True,
                          show_progress_bar=False).tolist()
    return {"vetor": vetor, "dim": len(vetor)}


def _rerank(payload):
    """Roda no worker único do _gpu_executor — contexto CUDA consistente.
    Devolve um logit de relevância por documento (maior = mais relevante)."""
    _garantir_reranker()
    query = payload["query"]
    docs  = payload["documentos"]
    if not docs:
        return {"scores": []}
    pares = [[query, d] for d in docs]
    scores = _reranker.predict(pares, show_progress_bar=False, convert_to_numpy=True)
    return {"scores": [float(s) for s in scores]}


@app.post("/embed")
def embed(req: EmbedRequest):
    if req.texto is None and req.textos is None:
        return {"erro": "informe 'texto' ou 'textos'"}
    fut = _gpu_executor.submit(_encode, {"texto": req.texto, "textos": req.textos})
    return JSONResponse(content=fut.result())


@app.post("/rerank")
def rerank(req: RerankRequest):
    fut = _gpu_executor.submit(_rerank, {"query": req.query, "documentos": req.documentos})
    return JSONResponse(content=fut.result())


@app.post("/unload")
def unload():
    return {"descarregado": _descarregar()}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")
