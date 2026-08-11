# -*- coding: utf-8 -*-
"""
ingest_webdocs.py — Ingestão de documentação de referência web → Qdrant

Crawleia páginas curadas de documentação técnica atual (DB, frontend, web dev,
LLMs), converte pra Markdown limpo (crawl4ai), chunka e vetoriza via
embed_service :8001 (BGE-M3 1024d), e sobe pra lyra_memory_v2 com categorias
novas ("referencia_*"). Criado 04/08/2026 a pedido do Antônio ("adicionar
novos repositórios sobre programação na memória, já vetorizados").

Idempotente: IDs uuid5 determinísticos por (url, índice do chunk) — rodar de
novo sobrescreve os mesmos pontos, nunca duplica.

Uso:  python ingest_webdocs.py           # ingere tudo
      python ingest_webdocs.py --dry     # só crawleia e mostra contagens
"""
import asyncio
import sys
import uuid
import httpx

EMBED_URL  = "http://127.0.0.1:8001/embed"
QDRANT_URL = "http://127.0.0.1:6333"
COLECAO    = "lyra_memory_v2"
NAMESPACE  = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # uuid.NAMESPACE_DNS
CHUNK_SIZE = 1400   # ~350 tokens; MAX_SEQ_LEN do BGE-M3 é 512 tokens
CHUNK_MIN  = 200    # chunk menor que isso é descartado (menu/rodapé)
BATCH      = 32

# ── Fontes curadas (categoria -> [(titulo, url)]) ────────────────────────────
FONTES = {
    "referencia_database": [
        ("PostgreSQL: Índices", "https://www.postgresql.org/docs/current/indexes.html"),
        ("PostgreSQL: EXPLAIN", "https://www.postgresql.org/docs/current/using-explain.html"),
        ("PostgreSQL: Performance Tips", "https://www.postgresql.org/docs/current/performance-tips.html"),
        ("SQLite: Query Planner", "https://www.sqlite.org/queryplanner.html"),
        ("Use The Index, Luke: Anatomia de um índice SQL", "https://use-the-index-luke.com/sql/anatomy"),
        ("Redis: Data types", "https://redis.io/docs/latest/develop/data-types/"),
        ("MongoDB: Data Modeling", "https://www.mongodb.com/docs/manual/data-modeling/"),
        ("Qdrant: Filtering", "https://qdrant.tech/documentation/concepts/filtering/"),
        ("Qdrant: Hybrid Queries", "https://qdrant.tech/documentation/concepts/hybrid-queries/"),
        ("SurrealDB: SurrealQL statements", "https://surrealdb.com/docs/surrealql/statements"),
    ],
    "referencia_frontend": [
        ("MDN: CSS Grid Layout", "https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_grid_layout"),
        ("MDN: Flexbox", "https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_flexible_box_layout/Basic_concepts_of_flexbox"),
        ("MDN: CSS Custom Properties", "https://developer.mozilla.org/en-US/docs/Web/CSS/Using_CSS_custom_properties"),
        ("MDN: Web Animations API", "https://developer.mozilla.org/en-US/docs/Web/API/Web_Animations_API/Using_the_Web_Animations_API"),
        ("MDN: Fetch API", "https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API/Using_Fetch"),
        ("MDN: Acessibilidade ARIA", "https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA"),
        ("web.dev: Core Web Vitals", "https://web.dev/articles/vitals"),
        ("web.dev: Otimizar LCP", "https://web.dev/articles/optimize-lcp"),
        ("patterns.dev: Rendering patterns", "https://www.patterns.dev/vanilla/rendering-patterns/"),
        ("React: Thinking in React", "https://react.dev/learn/thinking-in-react"),
        ("React: You Might Not Need an Effect", "https://react.dev/learn/you-might-not-need-an-effect"),
        ("Three.js: Fundamentals", "https://threejs.org/manual/#en/fundamentals"),
    ],
    "referencia_webdev": [
        ("MDN: HTTP Caching", "https://developer.mozilla.org/en-US/docs/Web/HTTP/Caching"),
        ("MDN: CORS", "https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS"),
        ("MDN: WebSockets API", "https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API"),
        ("OWASP: Top 10 2021", "https://owasp.org/Top10/"),
        ("FastAPI: Async", "https://fastapi.tiangolo.com/async/"),
        ("FastAPI: Dependencies", "https://fastapi.tiangolo.com/tutorial/dependencies/"),
        ("FastAPI: Background Tasks", "https://fastapi.tiangolo.com/tutorial/background-tasks/"),
        ("12 Factor App", "https://12factor.net/"),
    ],
    "referencia_llm": [
        ("Anthropic: Prompt engineering overview", "https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview"),
        ("Anthropic: Chain of thought", "https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/chain-of-thought"),
        ("Anthropic: Building effective agents", "https://www.anthropic.com/research/building-effective-agents"),
        ("OpenAI Cookbook: Techniques to improve reliability", "https://cookbook.openai.com/articles/techniques_to_improve_reliability"),
        ("Prompting Guide: RAG", "https://www.promptingguide.ai/techniques/rag"),
        ("Prompting Guide: Few-shot", "https://www.promptingguide.ai/techniques/fewshot"),
        ("Lilian Weng: LLM Powered Autonomous Agents", "https://lilianweng.github.io/posts/2023-06-23-agent/"),
        ("Chip Huyen: RAG e Agents", "https://huyenchip.com/2024/07/25/genai-platform.html"),
    ],
}


def _chunkar(texto: str) -> list[str]:
    """Divide em chunks de ~CHUNK_SIZE chars respeitando parágrafos."""
    chunks, atual = [], ""
    for par in texto.split("\n\n"):
        par = par.strip()
        if not par:
            continue
        if len(atual) + len(par) + 2 <= CHUNK_SIZE:
            atual = f"{atual}\n\n{par}" if atual else par
        else:
            if len(atual) >= CHUNK_MIN:
                chunks.append(atual)
            # Parágrafo sozinho maior que CHUNK_SIZE: corta em fatias duras
            while len(par) > CHUNK_SIZE:
                chunks.append(par[:CHUNK_SIZE])
                par = par[CHUNK_SIZE:]
            atual = par
    if len(atual) >= CHUNK_MIN:
        chunks.append(atual)
    return chunks


async def _crawl(urls: list[tuple[str, str]]) -> dict[str, tuple[str, str]]:
    """Crawleia todas as URLs → {url: (titulo, markdown)}. Falhas são puladas."""
    from crawl4ai import AsyncWebCrawler
    out = {}
    async with AsyncWebCrawler(verbose=False) as crawler:
        for titulo, url in urls:
            try:
                r = await crawler.arun(url=url)
                md = (getattr(r, "markdown", None) or "")
                md = md if isinstance(md, str) else str(md)
                if len(md) > 300:
                    out[url] = (titulo, md)
                    print(f"  [ok] {titulo} ({len(md)} chars)")
                else:
                    print(f"  [vazio] {titulo}")
            except Exception as e:
                print(f"  [FALHA] {titulo}: {str(e)[:80]}")
    return out


async def _embed_batch(client: httpx.AsyncClient, textos: list[str]) -> list[list[float]]:
    r = await client.post(EMBED_URL, json={"textos": textos}, timeout=180)
    r.raise_for_status()
    return r.json()["vetores"]


async def main():
    dry = "--dry" in sys.argv
    total_pontos = 0

    async with httpx.AsyncClient() as client:
        for categoria, fontes in FONTES.items():
            print(f"\n== {categoria} ({len(fontes)} páginas) ==")
            paginas = await _crawl(fontes)

            pontos = []
            for url, (titulo, md) in paginas.items():
                for i, chunk in enumerate(_chunkar(md)):
                    pid = str(uuid.uuid5(NAMESPACE, f"{url}#{i}"))
                    pontos.append({
                        "id": pid,
                        "payload": {
                            "titulo":    f"{titulo} (parte {i+1})",
                            "texto":     chunk,
                            "categoria": categoria,
                            "fonte":     url,
                        },
                        "_texto": chunk,
                    })
            print(f"  -> {len(pontos)} chunks")
            total_pontos += len(pontos)
            if dry or not pontos:
                continue

            # Vetoriza e sobe em lotes
            for i in range(0, len(pontos), BATCH):
                lote = pontos[i:i + BATCH]
                vetores = await _embed_batch(client, [p["_texto"] for p in lote])
                upsert = [{"id": p["id"], "vector": v, "payload": p["payload"]}
                          for p, v in zip(lote, vetores)]
                r = await client.put(
                    f"{QDRANT_URL}/collections/{COLECAO}/points",
                    json={"points": upsert}, timeout=60,
                )
                r.raise_for_status()
            print(f"  [UPSERT] {len(pontos)} pontos em '{categoria}'")

    print(f"\nTotal: {total_pontos} chunks {'(dry-run, nada subiu)' if dry else 'ingeridos'}")


if __name__ == "__main__":
    asyncio.run(main())
