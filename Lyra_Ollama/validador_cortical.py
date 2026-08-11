"""
validador_cortical.py — Item 4
Valida a qualidade do pipeline RAG híbrido da Lyra.

Metodologia:
  1. Amostra N registros aleatórios do Db_CORTEX (SurrealDB)
  2. Gera uma pergunta sintética para cada trecho usando o LLM local (qwen3:8b)
  3. Roda buscar_hibrido() para cada pergunta
  4. Mede Hit Rate (trecho original está no top-K?) e MRR
  5. Se Hit Rate < THRESHOLD_HR ou MRR < THRESHOLD_MRR → exibe alerta de rollback

Uso:
  python validador_cortical.py [--n 50] [--topk 5]

Limites recomendados:
  Hit Rate > 85%  (HR_THRESHOLD)
  MRR      > 0.68 (MRR_THRESHOLD)
"""

import sys
import os
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import asyncio
import random
import argparse
import httpx

# Adiciona o diretório do cerebro ao path para importar buscar_hibrido
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HR_THRESHOLD  = 0.85
MRR_THRESHOLD = 0.68

SURREAL_URL     = "http://127.0.0.1:8090/sql"
SURREAL_HEADERS = {
    "Accept": "application/json",
    "surreal-ns": "lyra_core",
    "surreal-db": "Db_CORTEX",
}
SURREAL_AUTH = ("root", "root")
OLLAMA_URL   = "http://127.0.0.1:11434/api/generate"


async def amostrar_eventos(n: int) -> list[dict]:
    """Busca N eventos aleatórios do SurrealDB."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            SURREAL_URL, headers=SURREAL_HEADERS, auth=SURREAL_AUTH,
            data=f"SELECT id, texto FROM evento ORDER BY rand() LIMIT {n};",
        )
        dados = r.json()
        return dados[0].get("result", []) if isinstance(dados, list) and dados else []


async def gerar_pergunta(texto: str) -> str:
    """Gera uma pergunta sintética para um trecho de texto usando qwen3:8b."""
    prompt = (
        f"Dado o seguinte trecho de memória:\n\n\"{texto[:400]}\"\n\n"
        "Escreva UMA pergunta curta (máx 15 palavras) em português que seja respondida "
        "por esse trecho. Responda APENAS a pergunta, sem prefixos ou explicações."
    )
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.post(OLLAMA_URL, json={
                "model": "qwen3:8b",
                "prompt": prompt,
                "stream": False,
                # think=False obrigatório: qwen3 gasta o num_predict inteiro em
                # <think>...</think> e nunca chega a gerar "response" (bug real
                # encontrado 30/06/2026 — todo o validador ficava com perguntas
                # vazias, zerando Hit Rate/MRR silenciosamente). Mesmo padrão
                # já usado em cerebro_maestro._stream_local.
                "think": False,
                "options": {"temperature": 0.3, "num_predict": 60},
            })
            resposta = r.json().get("response", "").strip().strip('"')
            if not resposta:
                raise ValueError("resposta vazia do qwen3:8b")
            return resposta
        except Exception:
            # Fallback: usa as primeiras palavras do texto como "pergunta"
            palavras = texto.split()[:8]
            return " ".join(palavras) + "?"


_cm = None  # módulo cerebro_maestro, importado e inicializado sob demanda


def _garantir_cerebro_inicializado():
    """cerebro_maestro.qdrant_client/indice_bm25 só existem depois de _init() —
    que só roda sob `if __name__=='__main__'` do próprio arquivo. Importar o
    módulo (como fazíamos antes) NÃO inicializa nada — buscar_hibrido() batia
    em qdrant_client=None e falhava silencioso (try/except em buscar()),
    retornando [] pra toda query. Bug real, presente desde que este validador
    foi criado — corrigido 30/06/2026 chamando _init() explicitamente aqui,
    uma vez só (não sobe uvicorn/porta 8000, só popula os globals)."""
    global _cm
    if _cm is None:
        import cerebro_maestro as cm
        cm._init()
        _cm = cm
    return _cm


def buscar(query: str, top_k: int, **pesos) -> list[str]:
    """Chama buscar_hibrido e retorna os IDs dos resultados."""
    try:
        cm = _garantir_cerebro_inicializado()
        resultados = cm.buscar_hibrido(query, top_k=top_k, **pesos)
        return [str(r.get("id", "")) for r in resultados]
    except Exception as e:
        print(f"  [ERRO] buscar_hibrido: {e}")
        return []


def calcular_metricas(gold_ids: list[str], retrieved_ids_list: list[list[str]]) -> tuple[float, float]:
    """Calcula Hit Rate e MRR."""
    hits, mrrs = 0, []
    for gold_id, retrieved in zip(gold_ids, retrieved_ids_list):
        hit = False
        for rank, rid in enumerate(retrieved, start=1):
            if gold_id in rid or rid in gold_id:
                hit = True
                mrrs.append(1.0 / rank)
                break
        if hit:
            hits += 1
        else:
            mrrs.append(0.0)

    hr  = hits / len(gold_ids) if gold_ids else 0.0
    mrr = sum(mrrs) / len(mrrs) if mrrs else 0.0
    return hr, mrr


def barra(val: float, width: int = 30) -> str:
    filled = round(val * width)
    return "█" * filled + "░" * (width - filled)


async def main(n_amostras: int, top_k: int):
    print(f"\n{'='*60}")
    print(f"  Validador Cortical de RAG")
    print(f"  Amostras: {n_amostras}  ·  Top-K: {top_k}")
    print(f"  Limites: HR>{HR_THRESHOLD*100:.0f}%  MRR>{MRR_THRESHOLD:.2f}")
    print(f"{'='*60}\n")

    print("→ Amostrando eventos do Db_CORTEX...")
    eventos = await amostrar_eventos(n_amostras)
    if not eventos:
        print("  ERRO: Nenhum evento encontrado no SurrealDB. Abortar.")
        return

    print(f"  ✓ {len(eventos)} eventos carregados")

    gold_ids:   list[str]       = []
    retriev:    list[list[str]] = []
    erros = 0

    for i, ev in enumerate(eventos, 1):
        eid   = str(ev.get("id", ""))
        texto = ev.get("texto", "").strip()
        if not texto:
            continue

        print(f"  [{i:02d}/{len(eventos):02d}] gerando pergunta...", end="\r")
        pergunta = await gerar_pergunta(texto)

        r_ids = buscar(pergunta, top_k)
        if not r_ids:
            erros += 1

        gold_ids.append(eid)
        retriev.append(r_ids)

    print(f"\n\n→ {len(gold_ids)} pares avaliados  ({erros} sem resultado)")
    hr, mrr = calcular_metricas(gold_ids, retriev)

    hr_ok  = hr  >= HR_THRESHOLD
    mrr_ok = mrr >= MRR_THRESHOLD

    print(f"\n{'─'*60}")
    print(f"  Hit Rate  {barra(hr)}  {hr*100:5.1f}%  {'✓' if hr_ok else '✗'}")
    print(f"  MRR       {barra(mrr)} {mrr:6.3f}   {'✓' if mrr_ok else '✗'}")
    print(f"{'─'*60}")

    if hr_ok and mrr_ok:
        print("\n  ✅ Pipeline RAG dentro dos limites de qualidade.")
    else:
        problemas = []
        if not hr_ok:
            problemas.append(f"Hit Rate {hr*100:.1f}% < {HR_THRESHOLD*100:.0f}% mínimo")
        if not mrr_ok:
            problemas.append(f"MRR {mrr:.3f} < {MRR_THRESHOLD:.2f} mínimo")

        print(f"\n  ⚠ ALERTA DE QUALIDADE: {' | '.join(problemas)}")
        print("\n  Ações recomendadas:")
        if not hr_ok:
            print("    - Verificar embed_service (:8001) e índice BM25")
            print("    - Considerar rollback do modelo de embedding")
            print("    - Checar consistência Qdrant ↔ SurrealDB")
        if not mrr_ok:
            print("    - Ajustar pesos RRF ou threshold do reranker")
            print("    - Aumentar pool de candidatos (top_k * 3)")
        print("\n  Para rollback automático, integre com CI/CD ou cron de validação.")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n",    type=int, default=50, help="Amostras a testar")
    parser.add_argument("--topk", type=int, default=5,  help="Top-K do RAG")
    args = parser.parse_args()
    asyncio.run(main(args.n, args.topk))
