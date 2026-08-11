"""
lyra_shadow_thoughts.py — Item 5
Ciclo de sono da Lyra: processamento offline de memórias em background.

Fases:
  NREM — deduplica memórias semanticamente próximas no Qdrant (cosseno > 0.95)
  REM  — cria arestas cross-domain no SurrealDB (tópicos relacionados que nunca se tocaram)
  DEEP — comprime eventos antigos em sumários (agrupa por semana, cria evento "resumo")

Uso:
  python lyra_shadow_thoughts.py           # roda as 3 fases uma vez
  python lyra_shadow_thoughts.py --fase nrem|rem|deep
  python lyra_shadow_thoughts.py --daemon  # roda a cada 3h em background

Segurança:
  - NREM: só marca duplicatas com flag "duplicado=True", NÃO deleta vetores
  - REM:  usa RELATE upsert — não cria arestas duplicadas
  - DEEP: só cria resumo se houver ≥ MIN_EVENTOS_RESUMO eventos na semana
"""

import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import asyncio
import argparse
import datetime
import json
import time

import httpx

MIN_NREM_COSSENO  = 0.95  # limiar de similaridade para considerar duplicata
MIN_EVENTOS_RESUMO = 20   # mínimo de eventos por semana para compressão DEEP
DEEP_SLEEP_SEMANAS = 4    # comprime semanas mais antigas que este valor
REM_MIN_TOPICOS    = 2    # mínimo de tópicos compartilhados para RELATE cross-domain
DAEMON_INTERVAL_H  = 3    # horas entre ciclos em modo --daemon

from config import QDRANT_URL as QDRANT_HOST, QDRANT_COLLECTION as COLECAO
from surreal_client import surreal


def log(msg: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


async def _sql(q: str) -> list:
    """Delegates to the shared SurrealClient (result[0] unwrapped)."""
    return await surreal.query_result(q, timeout=20)


# ── NREM — Deduplicação ───────────────────────────────────────────────────────

async def fase_nrem():
    """Busca pares de eventos semanticamente quase idênticos e marca o mais antigo
    com payload duplicado=True. Não apaga — só sinaliza para o RAG ignorar.

    Escopo: só categoria='episodio' (memórias de chat). Corrigido 01/07/2026 —
    a versão original fazia scroll(limit=500) SEM filtro e SEM paginação, ou
    seja: sempre os mesmos ~500 primeiros pontos da coleção inteira (~3M
    vetores), nunca cobrindo o resto, e comparando categorias sem sentido
    juntas (wiki com episódio de chat). Rodar O(N²) pareado contra os 3M
    vetores estáticos (wiki/datasets) é inviável e desnecessário — esse
    conteúdo já vem limpo da fonte; a duplicação real acontece em episódios de
    chat repetidos (ex: mensagens de teste). Agora pagina via scroll cursor
    até esgotar TODOS os pontos com essa categoria (hoje são poucas dezenas,
    então O(N²) ainda é seguro — se crescer muito, trocar por Qdrant
    query_points por ponto em vez de pairwise em memória)."""
    log("[NREM] Iniciando deduplicação semântica (categoria=episodio)...")
    pontos: list[dict] = []
    offset = None
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            while True:
                payload = {
                    "limit": 500, "with_vector": True,
                    "with_payload": ["timestamp", "duplicado"],
                    "filter": {"must": [{"key": "categoria", "match": {"value": "episodio"}}]},
                }
                if offset is not None:
                    payload["offset"] = offset
                r = await http.post(f"{QDRANT_HOST}/collections/{COLECAO}/points/scroll", json=payload)
                corpo = r.json().get("result", {})
                pontos.extend(corpo.get("points", []))
                offset = corpo.get("next_page_offset")
                if offset is None:
                    break
    except Exception as e:
        log(f"[NREM] Erro ao ler Qdrant: {e}")
        return 0

    duplicatas: list[int] = []
    N = len(pontos)
    log(f"[NREM] {N} vetores carregados — verificando similaridade...")

    for i in range(N):
        if pontos[i].get("payload", {}).get("duplicado"):
            continue
        vi = pontos[i].get("vector")
        if not vi:
            continue
        for j in range(i + 1, N):
            if pontos[j].get("payload", {}).get("duplicado"):
                continue
            vj = pontos[j].get("vector")
            if not vj:
                continue
            # Cosseno
            dot = sum(a * b for a, b in zip(vi, vj))
            na  = sum(a * a for a in vi) ** 0.5
            nb  = sum(b * b for b in vj) ** 0.5
            sim = dot / (na * nb) if na > 0 and nb > 0 else 0.0
            if sim >= MIN_NREM_COSSENO:
                # Marca o mais antigo como duplicata
                ts_i = pontos[i].get("payload", {}).get("timestamp", "")
                ts_j = pontos[j].get("payload", {}).get("timestamp", "")
                older_id = pontos[i]["id"] if ts_i <= ts_j else pontos[j]["id"]
                if older_id not in duplicatas:
                    duplicatas.append(older_id)

    if not duplicatas:
        log("[NREM] Nenhuma duplicata encontrada.")
        return 0

    log(f"[NREM] {len(duplicatas)} duplicatas encontradas — marcando no Qdrant...")
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            await http.post(
                f"{QDRANT_HOST}/collections/{COLECAO}/points/payload",
                json={
                    "payload": {"duplicado": True},
                    "points":  duplicatas,
                },
            )
    except Exception as e:
        log(f"[NREM] Erro ao marcar duplicatas: {e}")
        return 0

    log(f"[NREM] ✓ {len(duplicatas)} eventos marcados como duplicados.")
    return len(duplicatas)


# ── REM — Conexões cross-domain ───────────────────────────────────────────────

async def fase_rem():
    """Cria arestas 'conecta' entre tópicos que aparecem no mesmo evento mas
    não têm relação direta no grafo — conexões cross-domain latentes."""
    log("[REM] Buscando conexões cross-domain latentes...")
    # Busca todos os tópicos ligados a cada evento
    pares = await _sql(
        "SELECT in AS ev, array::group(out) AS topicos "
        "FROM sobre GROUP BY in HAVING count(out) >= 2 LIMIT 500;"
    )

    criadas = 0
    for row in pares:
        topicos = row.get("topicos", [])
        if len(topicos) < REM_MIN_TOPICOS:
            continue
        # Cria relação 'conecta' entre cada par de tópicos do mesmo evento
        for i in range(len(topicos)):
            for j in range(i + 1, len(topicos)):
                t1, t2 = str(topicos[i]), str(topicos[j])
                if not t1 or not t2 or t1 == t2:
                    continue
                q = (
                    f"IF (SELECT * FROM conecta WHERE in = {t1} AND out = {t2}) = [] "
                    f"THEN (RELATE {t1}->conecta->{t2} SET tipo='rem', peso=1) "
                    f"ELSE (UPDATE conecta SET peso += 1 WHERE in = {t1} AND out = {t2}) END;"
                )
                try:
                    await _sql(q)
                    criadas += 1
                except Exception:
                    pass

    log(f"[REM] ✓ {criadas} arestas cross-domain criadas/incrementadas.")
    return criadas


# ── DEEP SLEEP — Compressão temporal ─────────────────────────────────────────

async def fase_deep():
    """Agrupa eventos antigos por semana e cria um evento-resumo comprimido.
    Os eventos originais são marcados com comprimido=True (não são deletados)."""
    log("[DEEP] Iniciando compressão de memórias antigas...")
    corte = datetime.datetime.now() - datetime.timedelta(weeks=DEEP_SLEEP_SEMANAS)
    corte_iso = corte.isoformat()

    eventos = await _sql(
        f"SELECT id, texto, timestamp, ator FROM evento "
        f"WHERE timestamp < '{corte_iso}' AND comprimido != true "
        f"ORDER BY timestamp ASC LIMIT 2000;"
    )

    if not eventos:
        log("[DEEP] Nenhum evento antigo para comprimir.")
        return 0

    # Agrupa por semana
    por_semana: dict[str, list[dict]] = {}
    for ev in eventos:
        ts = ev.get("timestamp", "")
        try:
            dt = datetime.datetime.fromisoformat(ts)
            semana_key = dt.strftime("%Y-W%V")
        except Exception:
            semana_key = "unknown"
        por_semana.setdefault(semana_key, []).append(ev)

    criados = 0
    for semana, evs in por_semana.items():
        if len(evs) < MIN_EVENTOS_RESUMO:
            continue

        # Cria evento-resumo
        textos   = [e.get("texto", "")[:200] for e in evs[:20]]
        resumo   = f"[RESUMO SEMANAL {semana}] {len(evs)} eventos. " + " | ".join(textos[:5])
        ts_inicio = evs[0].get("timestamp", "")

        create_q = (
            f"CREATE evento SET "
            f"texto = {json.dumps(resumo, ensure_ascii=False)}, "
            f"ator = 'lyra_deep_sleep', "
            f"timestamp = '{ts_inicio}', "
            f"tipo = 'resumo', "
            f"semana = '{semana}', "
            f"n_eventos = {len(evs)};"
        )
        try:
            await _sql(create_q)
            criados += 1

            # Marca originais como comprimidos
            ids_str = ", ".join(str(e["id"]) for e in evs)
            await _sql(f"UPDATE [{ids_str}] SET comprimido = true;")
        except Exception as e:
            log(f"[DEEP] Erro ao comprimir semana {semana}: {e}")

    log(f"[DEEP] ✓ {criados} resumos semanais criados ({len(eventos)} eventos comprimidos).")
    return criados


# ── Orquestrador ──────────────────────────────────────────────────────────────

async def ciclo_completo(fases: list[str]):
    inicio = time.time()
    log(f"╔═ Shadow Thoughts — início do ciclo {'·'.join(fases)}")

    resultados = {}
    if "nrem" in fases:
        resultados["nrem"] = await fase_nrem()
    if "rem" in fases:
        resultados["rem"] = await fase_rem()
    if "deep" in fases:
        resultados["deep"] = await fase_deep()

    elapsed = time.time() - inicio
    log(f"╚═ Ciclo concluído em {elapsed:.1f}s — {resultados}")


async def daemon(fases: list[str]):
    log(f"[Daemon] Shadow Thoughts ativo · ciclo a cada {DAEMON_INTERVAL_H}h")
    while True:
        await ciclo_completo(fases)
        log(f"[Daemon] Próximo ciclo em {DAEMON_INTERVAL_H}h — aguardando...")
        await asyncio.sleep(DAEMON_INTERVAL_H * 3600)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fase",   type=str, default="nrem,rem,deep",
                        help="Fases separadas por vírgula: nrem,rem,deep")
    parser.add_argument("--daemon", action="store_true",
                        help="Roda em loop a cada DAEMON_INTERVAL_H horas")
    args = parser.parse_args()

    fases = [f.strip().lower() for f in args.fase.split(",")]
    validas = {"nrem", "rem", "deep"}
    fases = [f for f in fases if f in validas]
    if not fases:
        print("Fases inválidas. Use --fase nrem,rem,deep")
        raise SystemExit(1)

    if args.daemon:
        asyncio.run(daemon(fases))
    else:
        asyncio.run(ciclo_completo(fases))
