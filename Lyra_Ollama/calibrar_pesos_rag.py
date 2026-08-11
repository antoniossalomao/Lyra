"""
calibrar_pesos_rag.py — grid search dos pesos peso_relevancia/peso_recencia de
buscar_hibrido() contra Hit Rate/MRR reais (mesma metodologia do
validador_cortical.py, reaproveitada aqui pra não regerar perguntas via LLM a
cada combinação testada — caro e o gargalo do processo).

Uso:
  python calibrar_pesos_rag.py [--n 40] [--topk 5]
"""
import sys
import os
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import asyncio
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from validador_cortical import amostrar_eventos, gerar_pergunta, calcular_metricas, barra, buscar

# Grid: pesos que somam 1.0, cobrindo desde "só recência importa" até "só
# relevância importa". 0.68/0.32 é o par em produção desde 26/06/2026.
GRID = [
    (1.00, 0.00),
    (0.85, 0.15),
    (0.75, 0.25),
    (0.68, 0.32),  # atual em produção
    (0.60, 0.40),
    (0.50, 0.50),
]


def buscar_com_pesos(query: str, top_k: int, peso_rel: float, peso_rec: float) -> list[str]:
    return buscar(query, top_k, peso_relevancia=peso_rel, peso_recencia=peso_rec)


async def main(n_amostras: int, top_k: int):
    print(f"\n{'='*60}")
    print(f"  Calibração de pesos do RAG híbrido")
    print(f"  Amostras: {n_amostras}  ·  Top-K: {top_k}  ·  {len(GRID)} combinações")
    print(f"{'='*60}\n")

    print("→ Amostrando eventos e gerando perguntas sintéticas (uma vez só)...")
    eventos = await amostrar_eventos(n_amostras)
    if not eventos:
        print("  ERRO: Nenhum evento encontrado no SurrealDB. Abortar.")
        return

    pares = []  # (gold_id, pergunta)
    for i, ev in enumerate(eventos, 1):
        eid = str(ev.get("id", ""))
        texto = ev.get("texto", "").strip()
        if not texto:
            continue
        print(f"  [{i:02d}/{len(eventos):02d}] gerando pergunta...", end="\r")
        pergunta = await gerar_pergunta(texto)
        pares.append((eid, pergunta))
    print(f"\n  ✓ {len(pares)} pares (pergunta sintética → memória de origem) prontos\n")

    resultados_grid = []
    for peso_rel, peso_rec in GRID:
        gold_ids, retriev = [], []
        for eid, pergunta in pares:
            r_ids = buscar_com_pesos(pergunta, top_k, peso_rel, peso_rec)
            gold_ids.append(eid)
            retriev.append(r_ids)
        hr, mrr = calcular_metricas(gold_ids, retriev)
        resultados_grid.append((peso_rel, peso_rec, hr, mrr))
        marca = " ← atual em produção" if (peso_rel, peso_rec) == (0.68, 0.32) else ""
        print(f"  rel={peso_rel:.2f} rec={peso_rec:.2f}  HR={hr*100:5.1f}%  MRR={mrr:.3f}{marca}")

    melhor = max(resultados_grid, key=lambda x: (x[3], x[2]))  # MRR primeiro, HR desempate
    atual = next(r for r in resultados_grid if (r[0], r[1]) == (0.68, 0.32))

    print(f"\n{'─'*60}")
    print(f"  Atual (produção):  rel=0.68 rec=0.32  HR={atual[2]*100:.1f}%  MRR={atual[3]:.3f}")
    print(f"  Melhor do grid:    rel={melhor[0]:.2f} rec={melhor[1]:.2f}  HR={melhor[2]*100:.1f}%  MRR={melhor[3]:.3f}")
    print(f"{'─'*60}")

    ganho_mrr = melhor[3] - atual[3]
    if melhor[:2] == (0.68, 0.32):
        print("\n  ✅ O par atual (0.68/0.32) já é o melhor do grid testado. Nenhuma mudança recomendada.")
    elif ganho_mrr < 0.02:
        print(f"\n  ≈ Ganho marginal (+{ganho_mrr:.3f} MRR) — dentro do ruído de uma amostra de {len(pares)}."
              f" Mantendo o par atual por segurança (não trocar por ganho não significativo).")
    else:
        print(f"\n  ⚠ Ganho real (+{ganho_mrr:.3f} MRR). Considerar atualizar os defaults de"
              f" buscar_hibrido() pra rel={melhor[0]:.2f}/rec={melhor[1]:.2f}.")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n",    type=int, default=40, help="Amostras a testar")
    parser.add_argument("--topk", type=int, default=5,  help="Top-K do RAG")
    args = parser.parse_args()
    asyncio.run(main(args.n, args.topk))
