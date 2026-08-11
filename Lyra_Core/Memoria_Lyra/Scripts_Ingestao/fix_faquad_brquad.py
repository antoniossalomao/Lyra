# -*- coding: utf-8 -*-
"""
fix_faquad_brquad.py — Ingestão direta de FaQuAD e br-quad-2.0, contornando o bloqueio
da lib `datasets` a scripts de carregamento legados (ambos os repos no HF só têm o .py,
sem dados em parquet). Baixa os JSONs originais (formato SQuAD) direto do GitHub.
"""
import asyncio
import json
import sys

import httpx
from surrealdb import AsyncSurreal

DB_URL  = "ws://127.0.0.1:8090/rpc"  # 127.0.0.1: evita delay IPv6 do localhost
NS      = "lyra_core"
DB_NAME = "Db_CORTEX"
TABELA  = "base_conhecimento_qa"
BATCH   = 500

FONTES = [
    {
        "fonte": "faquad",
        "urls": [
            "https://raw.githubusercontent.com/liafacom/faquad/master/data/train.json",
            "https://raw.githubusercontent.com/liafacom/faquad/master/data/dev.json",
        ],
    },
    {
        "fonte": "br_quad_2.0",
        "urls": [
            "https://raw.githubusercontent.com/piEsposito/br-quad-2.0/main/data/brquad-gte-dev-v2.0.json",
        ],
    },
]


def extrair_qas(squad_json: dict, fonte: str):
    registros = []
    for artigo in squad_json.get("data", []):
        for paragrafo in artigo.get("paragraphs", []):
            contexto = (paragrafo.get("context") or "").strip()
            for qa in paragrafo.get("qas", []):
                if qa.get("is_impossible"):
                    continue
                q = (qa.get("question") or "").strip()
                answers = qa.get("answers") or []
                a = (answers[0]["text"].strip() if answers else "")
                if not q or not a:
                    continue
                txt = f"Pergunta: {q}\nResposta: {a}"
                if contexto:
                    txt += f"\nContexto: {contexto[:500]}"
                registros.append({
                    "titulo":    q[:200],
                    "texto":     txt[:3000],
                    "fonte":     fonte,
                    "categoria": "conhecimento_qa",
                })
    return registros


async def main():
    todos = []
    async with httpx.AsyncClient(timeout=60) as client:
        for cfg in FONTES:
            for url in cfg["urls"]:
                print(f"   baixando {url} ...")
                resp = await client.get(url)
                resp.raise_for_status()
                squad_json = json.loads(resp.content.decode("utf-8"))
                regs = extrair_qas(squad_json, cfg["fonte"])
                print(f"   {cfg['fonte']}: +{len(regs)} registros de {url.rsplit('/', 1)[-1]}")
                todos.extend(regs)

    print(f"\n   Total a inserir em {TABELA}: {len(todos):,}")

    async with AsyncSurreal(DB_URL) as db:
        await db.signin({"user": "root", "pass": "root"})
        await db.use(NS, DB_NAME)
        for i in range(0, len(todos), BATCH):
            lote = todos[i:i + BATCH]
            await db.query(f"INSERT INTO {TABELA} $lote", {"lote": lote})
            print(f"   inseridos {min(i + BATCH, len(todos)):,}/{len(todos):,}")

    print("\n   Concluído.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(main())
