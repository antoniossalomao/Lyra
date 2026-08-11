"""
reconciliar_episodios.py — Reconcilia eventos do SurrealDB sem vetor no Qdrant.

Causa documentada: registrar_evento() grava SurrealDB e Qdrant em duas operações
não-atômicas. Se o processo morreu entre elas (restarts de manutenção), o evento
fica no SurrealDB mas nunca chega ao Qdrant. Sem erro visível.

Escopo: apenas eventos pós-migração BGE-M3 (>= 2026-06-26), que deveriam estar
em lyra_memory_v2 (1024d). Eventos anteriores são do v1 (apagado intencionalmente).

Uso:
  python reconciliar_episodios.py          # mostra gap, pergunta antes de corrigir
  python reconciliar_episodios.py --fix    # corrige sem perguntar
  python reconciliar_episodios.py --dry    # só reporta, não grava nada
"""

import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import asyncio
import argparse
import json
import re
import uuid
import datetime
import httpx

SURREAL_URL     = "http://127.0.0.1:8090/sql"
SURREAL_HEADERS = {"Accept": "application/json", "surreal-ns": "lyra_core", "surreal-db": "Db_CORTEX"}
SURREAL_AUTH    = ("root", "root")
QDRANT_URL      = "http://127.0.0.1:6333"
EMBED_URL       = "http://127.0.0.1:8001/embed"
COLECAO         = "lyra_memory_v2"
MIGRACAO_DATA   = "2026-06-26"  # data da migração BGE-M3 — só eventos a partir daqui


async def _sql(client: httpx.AsyncClient, q: str) -> list:
    r = await client.post(SURREAL_URL, headers=SURREAL_HEADERS, auth=SURREAL_AUTH, data=q, timeout=20)
    d = r.json()
    return d[0].get("result", []) if isinstance(d, list) and d else []


def _extrair_uuid(surreal_id) -> str | None:
    """Extrai o UUID de um ID SurrealDB no formato 'evento:uuid' ou RecordID."""
    s = str(surreal_id)
    # formato: "evento:⟨uuid⟩" ou "evento:uuid" ou só "uuid"
    partes = s.split(":")
    raw = partes[-1].strip().strip("⟨⟩`").strip()
    # valida formato UUID
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        # pode ser sem hífens (uuid4().hex[:20]) — tenta normalizar
        clean = re.sub(r"[^0-9a-fA-F]", "", raw)
        if len(clean) == 32:
            return str(uuid.UUID(clean))
        return None


async def listar_ids_qdrant(client: httpx.AsyncClient) -> set[str]:
    """Retorna conjunto de todos os IDs (UUID string) de episódios no Qdrant."""
    ids: set[str] = set()
    offset = None
    while True:
        payload: dict = {
            "limit": 1000, "with_vector": False, "with_payload": False,
            "filter": {"must": [{"key": "categoria", "match": {"value": "episodio"}}]},
        }
        if offset is not None:
            payload["offset"] = offset
        r = await client.post(f"{QDRANT_URL}/collections/{COLECAO}/points/scroll", json=payload, timeout=30)
        corpo = r.json().get("result", {})
        for p in corpo.get("points", []):
            ids.add(str(p["id"]))
        offset = corpo.get("next_page_offset")
        if offset is None:
            break
    return ids


async def embed_texto(client: httpx.AsyncClient, texto: str) -> list[float] | None:
    try:
        r = await client.post(EMBED_URL, json={"texto": texto}, timeout=30)
        return r.json().get("vetor")
    except Exception as e:
        print(f"  [EMBED ERRO] {e}")
        return None


async def reconciliar(dry_run: bool, auto_fix: bool, silencioso: bool = False) -> dict:
    """silencioso=True suprime os prints (uso programático, ex: job periódico
    no loop_proativo) — sempre retorna um dict com as contagens, além do CLI
    continuar imprimindo normalmente quando silencioso=False."""
    def _p(msg: str):
        if not silencioso:
            print(msg)

    async with httpx.AsyncClient(timeout=30) as client:
        _p(f"\n[1] Buscando eventos do SurrealDB >= {MIGRACAO_DATA}...")
        eventos = await _sql(client,
            f"SELECT id, texto, ator, timestamp, fonte FROM evento "
            f"WHERE timestamp >= '{MIGRACAO_DATA}T00:00:00' ORDER BY timestamp ASC LIMIT 5000;"
        )
        _p(f"    {len(eventos)} eventos encontrados.")

        _p(f"[2] Listando episódios no Qdrant ({COLECAO})...")
        ids_qdrant = await listar_ids_qdrant(client)
        _p(f"    {len(ids_qdrant)} pontos no Qdrant.")

        orfaos = []
        for ev in eventos:
            uid = _extrair_uuid(ev.get("id", ""))
            if uid and uid not in ids_qdrant:
                orfaos.append({**ev, "_uuid": uid})

        _p(f"\n[RESULTADO] {len(orfaos)} eventos sem vetor no Qdrant (de {len(eventos)} pós-migração).")

        resultado = {"eventos_verificados": len(eventos), "orfaos_encontrados": len(orfaos), "reconciliados": 0}

        if not orfaos:
            _p("Nada a fazer — sistema consistente.")
            return resultado

        for o in orfaos:
            _p(f"  - {o['_uuid'][:8]}... | {o.get('timestamp','?')[:16]} | {o.get('ator','?')} | {o.get('texto','')[:60]}")

        if dry_run:
            _p("\n[DRY RUN] Modo somente-leitura — nenhuma gravação feita.")
            return resultado

        if not auto_fix:
            resp = input(f"\nDeseja re-embedar e gravar esses {len(orfaos)} eventos no Qdrant? [s/N] ").strip().lower()
            if resp != "s":
                _p("Cancelado.")
                return resultado

        _p(f"\n[3] Re-embedando {len(orfaos)} eventos órfãos...")
        from qdrant_client import QdrantClient
        from qdrant_client.models import PointStruct
        qclient = QdrantClient("127.0.0.1", port=6333, timeout=30)

        ok = 0
        for o in orfaos:
            vetor = await embed_texto(client, o.get("texto", ""))
            if vetor is None:
                _p(f"  [SKIP] {o['_uuid'][:8]}... — embed_service indisponível")
                continue
            ts = o.get("timestamp", datetime.datetime.now().isoformat())
            try:
                qclient.upsert(
                    collection_name=COLECAO,
                    points=[PointStruct(
                        id=o["_uuid"],
                        vector=vetor,
                        payload={
                            "ator":             o.get("ator", ""),
                            "texto":            o.get("texto", ""),
                            "categoria":        "episodio",
                            "timestamp":        ts,
                            "fonte":            o.get("fonte", "chat"),
                            "last_accessed_at": ts,
                            "retrieval_count":  0,
                        }
                    )]
                )
                _p(f"  [OK] {o['_uuid'][:8]}... gravado.")
                ok += 1
            except Exception as e:
                _p(f"  [ERRO] {o['_uuid'][:8]}...: {e}")

        resultado["reconciliados"] = ok
        _p(f"\n[CONCLUÍDO] {ok}/{len(orfaos)} episódios reconciliados no Qdrant.")
        return resultado


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry",  action="store_true", help="Só reporta, não grava")
    parser.add_argument("--fix",  action="store_true", help="Corrige sem perguntar")
    args = parser.parse_args()
    asyncio.run(reconciliar(dry_run=args.dry, auto_fix=args.fix))
