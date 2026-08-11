# -*- coding: utf-8 -*-
"""Constrói (ou reconstrói) o índice BM25 a partir do payload já vetorizado no Qdrant."""
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from qdrant_client import QdrantClient
import bm25_index as bi


def main():
    # Coleção pode ser passada por argv; default lyra_memory_v2 (BGE-M3, produção atual).
    colecao = sys.argv[1] if len(sys.argv) > 1 else "lyra_memory_v2"
    # --novo: salva em bm25s_index_new/ + bm25s_meta_new.pkl (swap manual depois,
    # com o cerebro parado — ver docstring de construir_indice sobre o lock mmap).
    out_dir = out_meta = None
    if "--novo" in sys.argv:
        import os
        base = os.path.dirname(os.path.abspath(__file__))
        out_dir  = os.path.join(base, "bm25s_index_new")
        out_meta = os.path.join(base, "bm25s_meta_new.pkl")
    q = QdrantClient("127.0.0.1", port=6333, timeout=60)
    t0 = time.time()
    print(f"[BM25] Construindo índice sobre '{colecao}'...")
    total = bi.construir_indice(q, collection=colecao, log=print, out_dir=out_dir, out_meta=out_meta)
    print(f"\n[BM25] Concluído: {total:,} documentos em {time.time() - t0:.1f}s.")


if __name__ == "__main__":
    main()
