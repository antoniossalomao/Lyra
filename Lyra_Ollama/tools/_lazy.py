"""tools/_lazy.py — lazy singletons shared by memory.py (Qdrant client, BM25
index, embed_service HTTP call). Double-checked locking: tools run via
asyncio.to_thread (real threads), so unguarded init would race.
"""

import json
import threading

from config import QDRANT_PORT, EMBED_URL

_qdrant = None
_indice_bm25 = "nao_carregado"  # sentinela: distingue "não tentou" de "tentou e não achou"
_lock_qdrant = threading.Lock()
_lock_bm25 = threading.Lock()


def get_qdrant():
    """Return the shared QdrantClient, initializing it on first call."""
    global _qdrant
    if _qdrant is None:
        with _lock_qdrant:
            if _qdrant is None:
                from qdrant_client import QdrantClient
                _qdrant = QdrantClient("127.0.0.1", port=QDRANT_PORT, timeout=30)
    return _qdrant


def get_bm25_index():
    """Return the shared BM25 index (same one used by cerebro_maestro's hybrid
    search), loaded once on first call."""
    global _indice_bm25
    if _indice_bm25 == "nao_carregado":
        with _lock_bm25:
            if _indice_bm25 == "nao_carregado":
                import bm25_index
                _indice_bm25 = bm25_index.carregar_indice(log=lambda *_: None)
    return _indice_bm25


def embed_remote(texto: str):
    """Embed via embed_service :8001 (BGE-M3 1024d)."""
    import urllib.request
    req = urllib.request.Request(
        EMBED_URL,
        data=json.dumps({"texto": texto}).encode("utf-8"),
        method="POST", headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())["vetor"]
