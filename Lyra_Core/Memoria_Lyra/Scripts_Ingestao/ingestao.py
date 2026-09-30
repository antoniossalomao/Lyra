"""
ingestao.py — Gênesis da Memória Neural Lyra
══════════════════════════════════════════════════════════════════
RING 0: 100% offline após download inicial dos datasets.
Limpa o SurrealDB e re-ingere tudo do zero.

Uso:
  python ingestao.py            → fresh start (apaga tudo e reinicia)
  python ingestao.py --retomar  → retoma de onde parou (usa checkpoints)

Dependências:
  pip install surrealdb datasets

Datasets ingeridos:
  wiki_conhecimento    Wikipedia PT-BR ~1M artigos
  base_codigo          Evol-Instruct 80k + Python 120k + CodeAlpaca 20k + Python 18k
  base_instrucoes_ptbr Canarim 316k instruções em PT-BR nativo
  base_raciocinio      GSM8K 8.5k + MetaMathQA 395k (matemática/lógica)
  base_conversas       OpenHermes 2.5 ~1M conversas de alta qualidade
══════════════════════════════════════════════════════════════════
"""

import asyncio
import json
import os
import sys
import time
from itertools import islice

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── Verificação de dependências antes de qualquer coisa ───────────────────────
def _checar_deps():
    erros = []
    try:
        import surrealdb
    except ImportError:
        erros.append("surrealdb  → pip install surrealdb")
    try:
        import datasets
    except ImportError:
        erros.append("datasets   → pip install datasets")
    if erros:
        print("\n[ERRO] Dependências faltando:")
        for e in erros:
            print(f"  {e}")
        sys.exit(1)

_checar_deps()

from datasets import load_dataset
from surrealdb import AsyncSurreal

# ─── CONFIGURAÇÃO ─────────────────────────────────────────────────────────────
DB_URL   = "ws://127.0.0.1:8090/rpc"   # porta 8090 (8000 é do FastAPI); 127.0.0.1 evita delay IPv6
NS       = "lyra_core"
DB_NAME  = "Db_CORTEX"
BATCH    = 500       # registros por INSERT — conservador para evitar timeout WS
MAX_CONC = 4         # máx. ingestões paralelas no SurrealDB
CKPT_DIR = os.path.dirname(os.path.abspath(__file__))

TABELAS = [
    "wiki_conhecimento",
    "base_codigo",
    "base_instrucoes_ptbr",
    "base_raciocinio",
    "base_conversas",
    "base_conhecimento_qa",
]


# ─── MAPPERS ──────────────────────────────────────────────────────────────────
# Schema padrão Lyra: { titulo, texto, fonte, categoria }
# 'texto' é vetorizado pelo vetorizar_bge_m3.py — máx 3000 chars

def _m_wiki(d):
    t = (d.get("title") or "").strip()
    x = (d.get("text")  or "").strip()
    return {
        "titulo":    t[:200],
        "texto":     f"{t}\n\n{x}"[:3000],
        "fonte":     "wikipedia_ptbr",
        "categoria": "conhecimento_geral",
    }


def _m_codigo(fonte: str):
    def _inner(d):
        inst = (d.get("instruction") or d.get("prompt") or "").strip()
        inp  = (d.get("input",  "") or "").strip()
        out  = (d.get("output", "") or "").strip()
        txt  = f"Instrução: {inst}"
        if inp: txt += f"\nEntrada: {inp}"
        if out: txt += f"\nResposta: {out}"
        return {
            "titulo":    inst[:200],
            "texto":     txt[:3000],
            "fonte":     fonte,
            "categoria": "programacao",
        }
    return _inner


def _m_canarim(d):
    inst = (d.get("instruction") or "").strip()
    ctx  = (d.get("context",  "") or "").strip()
    out  = (d.get("output",   "") or "").strip()
    txt  = f"Instrução: {inst}"
    if ctx: txt += f"\nContexto: {ctx}"
    if out: txt += f"\nResposta: {out}"
    return {
        "titulo":    inst[:200],
        "texto":     txt[:3000],
        "fonte":     "canarim_ptbr",
        "categoria": "instrucao_ptbr",
    }


def _m_gsm8k(d):
    q = (d.get("question") or "").strip()
    a = (d.get("answer",   "") or "").strip()
    return {
        "titulo":    q[:200],
        "texto":     f"Problema: {q}\nSolução: {a}"[:3000],
        "fonte":     "gsm8k",
        "categoria": "raciocinio_matematico",
    }


def _m_metamath(d):
    q = (d.get("query") or d.get("original_question") or "").strip()
    r = (d.get("response", "") or "").strip()
    t = (d.get("type", "") or "")
    return {
        "titulo":    q[:200],
        "texto":     f"[{t}] Problema: {q}\nSolução: {r}"[:3000],
        "fonte":     "metamath_qa",
        "categoria": "raciocinio_matematico",
    }


def _m_openhermes(d):
    convs  = d.get("conversations") or []
    partes = []
    for c in (convs if isinstance(convs, list) else []):
        if not isinstance(c, dict):
            continue
        role = "Humano" if c.get("from") in ("human", "user") else "Lyra"
        val  = (c.get("value") or "").strip()
        if val:
            partes.append(f"{role}: {val}")
    texto  = "\n".join(partes)
    titulo = partes[0][:200] if partes else ""
    cat    = str(d.get("category") or "geral")
    return {
        "titulo":    titulo,
        "texto":     texto[:3000],
        "fonte":     f"openhermes_{cat}",
        "categoria": "conversa_geral",
    }


def _m_aya(d):
    # Aya Dataset é multilíngue (65+ idiomas) — mantém só as linhas em português
    lang = (d.get("language_code") or d.get("language") or "").lower()
    if lang not in ("por", "portuguese", "pt"):
        return None
    inst = (d.get("inputs")  or "").strip()
    out  = (d.get("targets") or "").strip()
    if not inst or not out:
        return None
    return {
        "titulo":    inst[:200],
        "texto":     f"Instrução: {inst}\nResposta: {out}"[:3000],
        "fonte":     "aya_dataset_ptbr",
        "categoria": "instrucao_ptbr",
    }


def _m_squad_qa(fonte: str):
    """Mapper genérico para datasets em formato SQuAD (br-quad-2.0, FaQuAD)."""
    def _inner(d):
        q = (d.get("question") or "").strip()
        answers = d.get("answers") or {}
        textos = answers.get("text") if isinstance(answers, dict) else None
        a = (textos[0].strip() if textos else "")
        if not q or not a:
            return None
        contexto = (d.get("context") or "").strip()
        txt = f"Pergunta: {q}\nResposta: {a}"
        if contexto:
            txt += f"\nContexto: {contexto[:500]}"
        return {
            "titulo":    q[:200],
            "texto":     txt[:3000],
            "fonte":     fonte,
            "categoria": "conhecimento_qa",
        }
    return _inner


# ─── CATÁLOGO ─────────────────────────────────────────────────────────────────
DATASETS = [
    {
        "id":        "wiki_ptbr",
        "tabela":    "wiki_conhecimento",
        "hf":        ("wikimedia/wikipedia", "20231101.pt"),
        "split":     "train",
        "streaming": True,
        "mapper":    _m_wiki,
        "desc":      "Wikipedia PT-BR ~1M artigos",
    },
    {
        "id":        "evol_code",
        "tabela":    "base_codigo",
        "hf":        ("nickrosh/Evol-Instruct-Code-80k-v1", None),
        "split":     "train",
        "streaming": False,
        "mapper":    _m_codigo("evol_instruct_80k"),
        "desc":      "Evol-Instruct Code 80k",
    },
    {
        "id":        "python_120k",
        "tabela":    "base_codigo",
        "hf":        ("iamtarun/code_instructions_120k_alpaca", None),
        "split":     "train",
        "streaming": False,
        "mapper":    _m_codigo("python_120k"),
        "desc":      "Python Instructions 120k",
    },
    {
        "id":        "code_alpaca",
        "tabela":    "base_codigo",
        "hf":        ("sahil2801/CodeAlpaca-20k", None),
        "split":     "train",
        "streaming": False,
        "mapper":    _m_codigo("code_alpaca_20k"),
        "desc":      "CodeAlpaca 20k",
    },
    {
        "id":        "python_18k",
        "tabela":    "base_codigo",
        "hf":        ("iamtarun/python_code_instructions_18k_alpaca", None),
        "split":     "train",
        "streaming": False,
        "mapper":    _m_codigo("python_18k"),
        "desc":      "Python Instructions 18k",
    },
    {
        "id":        "canarim",
        "tabela":    "base_instrucoes_ptbr",
        "hf":        ("dominguesm/Canarim-Instruct-PTBR-Dataset", None),
        "split":     "train",
        "streaming": False,
        "mapper":    _m_canarim,
        "desc":      "Canarim PT-BR 316k instruções",
    },
    {
        "id":        "gsm8k",
        "tabela":    "base_raciocinio",
        "hf":        ("openai/gsm8k", "main"),
        "split":     "train",
        "streaming": False,
        "mapper":    _m_gsm8k,
        "desc":      "GSM8K Matemática 8.5k",
    },
    {
        "id":        "metamath",
        "tabela":    "base_raciocinio",
        "hf":        ("meta-math/MetaMathQA", None),
        "split":     "train",
        "streaming": False,
        "mapper":    _m_metamath,
        "desc":      "MetaMathQA 395k",
    },
    {
        "id":        "openhermes",
        "tabela":    "base_conversas",
        "hf":        ("teknium/OpenHermes-2.5", None),
        "split":     "train",
        "streaming": False,
        "mapper":    _m_openhermes,
        "desc":      "OpenHermes 2.5 ~1M conversas",
    },
    {
        "id":        "aya_ptbr",
        "tabela":    "base_instrucoes_ptbr",
        "hf":        ("CohereLabs/aya_dataset", None),
        "split":     "train",
        "streaming": False,
        "mapper":    _m_aya,
        "desc":      "Aya Dataset — instruções PT-BR curadas por humanos (filtra idioma)",
    },
    {
        "id":        "br_quad",
        "tabela":    "base_conhecimento_qa",
        "hf":        ("piEsposito/br-quad-2.0", None),
        "split":     "train",
        "streaming": False,
        "mapper":    _m_squad_qa("br_quad_2.0"),
        "desc":      "SQuAD 2.0 traduzido para PT-BR",
    },
    {
        "id":        "faquad",
        "tabela":    "base_conhecimento_qa",
        "hf":        ("eraldoluis/faquad", None),
        "split":     "train",
        "streaming": False,
        "mapper":    _m_squad_qa("faquad"),
        "desc":      "FaQuAD — QA nativo em PT-BR (ensino superior)",
    },
]


# ─── CHECKPOINT ───────────────────────────────────────────────────────────────
def _ckpt_file(ds_id: str) -> str:
    return os.path.join(CKPT_DIR, f".ckpt_{ds_id}.json")

def _load_ckpt(ds_id: str) -> dict:
    p = _ckpt_file(ds_id)
    if os.path.exists(p):
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            pass
    return {"done": False, "count": 0, "offset": 0}

def _save_ckpt(ds_id: str, done: bool, count: int, offset: int) -> None:
    with open(_ckpt_file(ds_id), "w") as f:
        json.dump({"done": done, "count": count, "offset": offset}, f)

def _clear_ckpts() -> None:
    for cfg in DATASETS:
        p = _ckpt_file(cfg["id"])
        if os.path.exists(p):
            os.remove(p)


# ─── PRÉ-VOO: verifica SurrealDB ──────────────────────────────────────────────
async def _preflight() -> bool:
    print("   Verificando SurrealDB...", end=" ", flush=True)
    try:
        async with AsyncSurreal(DB_URL) as db:
            await db.signin({"user": "root", "pass": "root"})
            await db.use(NS, DB_NAME)
        print("✓ online")
        return True
    except Exception as e:
        print(f"\n\n[ERRO] SurrealDB não está respondendo em {DB_URL}")
        print(f"   Detalhe: {e}")
        print(f"   → Certifique que o SurrealDB está rodando antes de iniciar.\n")
        return False


# ─── LIMPAR BANCO ─────────────────────────────────────────────────────────────
async def limpar_banco() -> None:
    print("🗑️  Limpando SurrealDB (fresh start)...")
    async with AsyncSurreal(DB_URL) as db:
        await db.signin({"user": "root", "pass": "root"})
        await db.use(NS, DB_NAME)
        for t in TABELAS:
            try:
                await db.query(f"DELETE {t}")
                print(f"   ✓ {t}")
            except Exception as e:
                print(f"   ! {t} — {e}")
    _clear_ckpts()
    print("   ✓ Checkpoints removidos\n")


# ─── CARREGAR DATASET ─────────────────────────────────────────────────────────
async def _carregar_dataset(cfg: dict):
    hf_path, hf_name = cfg["hf"]
    streaming        = cfg["streaming"]

    def _load():
        kwargs = {
            "split":             cfg["split"],
            "streaming":         streaming,
            "trust_remote_code": True,
        }
        if hf_name:
            return load_dataset(hf_path, hf_name, **kwargs)
        return load_dataset(hf_path, **kwargs)

    return await asyncio.to_thread(_load)


# ─── INGERIR UM DATASET ───────────────────────────────────────────────────────
async def ingerir(cfg: dict, semaforo: asyncio.Semaphore) -> int:
    ds_id     = cfg["id"]
    tabela    = cfg["tabela"]
    mapper    = cfg["mapper"]
    streaming = cfg["streaming"]

    ckpt = _load_ckpt(ds_id)
    if ckpt["done"]:
        print(f"   ⏭️  {ds_id:<24} já concluído ({ckpt['count']:>8,} registros)")
        return ckpt["count"]

    count  = ckpt["count"]
    offset = ckpt["offset"]

    print(f"   ⬇️  {ds_id:<24} baixando — {cfg['desc']}")

    try:
        ds = await _carregar_dataset(cfg)
    except Exception as e:
        print(f"   ✗  {ds_id:<24} ERRO no download: {e}")
        return 0

    iterator = islice(ds, offset, None) if streaming else iter(ds)
    t0 = time.time()

    async with semaforo:
        try:
            async with AsyncSurreal(DB_URL) as db:
                await db.signin({"user": "root", "pass": "root"})
                await db.use(NS, DB_NAME)

                lote = []
                i    = offset

                for raw in iterator:
                    try:
                        rec = mapper(raw)
                        if rec and rec.get("texto", "").strip():
                            lote.append(rec)
                    except Exception:
                        pass

                    i += 1

                    if len(lote) >= BATCH:
                        try:
                            await db.query(
                                f"INSERT INTO {tabela} $lote",
                                {"lote": lote}
                            )
                            count += len(lote)
                        except Exception as e:
                            print(f"\n   ! {ds_id} INSERT erro (lote={len(lote)}): {e}")
                        finally:
                            lote = []

                        _save_ckpt(ds_id, False, count, i)

                        if count % 20_000 < BATCH:
                            elapsed = time.time() - t0
                            vel = count / elapsed if elapsed > 0 else 0
                            print(f"   📊 {ds_id:<24} {count:>8,} reg | {vel:.0f} reg/s")

                # flush final
                if lote:
                    try:
                        await db.query(
                            f"INSERT INTO {tabela} $lote",
                            {"lote": lote}
                        )
                        count += len(lote)
                    except Exception as e:
                        print(f"\n   ! {ds_id} flush final erro: {e}")

        except Exception as e:
            print(f"   ✗  {ds_id:<24} ERRO na ingestão: {e}")
            _save_ckpt(ds_id, False, count, i if 'i' in dir() else offset)
            return count

    _save_ckpt(ds_id, True, count, i)
    elapsed = time.time() - t0
    print(f"   ✅ {ds_id:<24} {count:>8,} registros | {elapsed/60:.1f} min")
    return count


# ─── MAIN ─────────────────────────────────────────────────────────────────────
async def main() -> None:
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║       LYRA — GÊNESIS DA MEMÓRIA NEURAL  v2.1            ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print("║  Ring 0: offline, local, soberania total                ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    # Pré-voo obrigatório
    if not await _preflight():
        sys.exit(1)

    # --apenas=id1,id2 restringe a execução a datasets específicos (ex.: os novos)
    # e implica modo retomar — nunca apaga dados existentes das outras bases.
    apenas_arg = next((a for a in sys.argv if a.startswith("--apenas=")), None)
    datasets_alvo = DATASETS
    if apenas_arg:
        ids_pedidos = set(apenas_arg.split("=", 1)[1].split(","))
        datasets_alvo = [c for c in DATASETS if c["id"] in ids_pedidos]
        print(f"   Modo --apenas: {[c['id'] for c in datasets_alvo]}\n")

    retomar = "--retomar" in sys.argv or bool(apenas_arg)
    if retomar:
        print("   Modo RETOMAR — pulando datasets já concluídos\n")
    else:
        await limpar_banco()

    semaforo = asyncio.Semaphore(MAX_CONC)
    t_inicio = time.time()
    total    = 0

    # ── FASE 1: Wikipedia (streaming, sequencial) ─────────────────────────────
    wiki_cfg = next((c for c in datasets_alvo if c["id"] == "wiki_ptbr"), None)
    if wiki_cfg:
        print("━" * 62)
        print("  FASE 1 — Wikipedia PT-BR (streaming)")
        print("━" * 62)
        total += await ingerir(wiki_cfg, semaforo)

    # ── FASE 2: Demais datasets em paralelo ───────────────────────────────────
    outros = [c for c in datasets_alvo if c["id"] != "wiki_ptbr"]
    print()
    print("━" * 62)
    print("  FASE 2 — Demais datasets (paralelo)")
    print("━" * 62)
    resultados = await asyncio.gather(
        *[ingerir(c, semaforo) for c in outros],
        return_exceptions=True   # ← não aborta se um falhar
    )

    for cfg, res in zip(outros, resultados):
        if isinstance(res, Exception):
            print(f"   ✗ {cfg['id']}: {res}")
        else:
            total += res

    # ── Resumo ────────────────────────────────────────────────────────────────
    elapsed = time.time() - t_inicio
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  GÊNESIS CONCLUÍDO                                      ║")
    print(f"║  Total registros : {total:>10,}                           ║")
    print(f"║  Tempo total     : {elapsed / 60:>10.1f} min                       ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print("║  Próximo:  python vetorizar_bge_m3.py  (vetoriza)       ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    # ── Contagem final por tabela ─────────────────────────────────────────────
    try:
        async with AsyncSurreal(DB_URL) as db:
            await db.signin({"user": "root", "pass": "root"})
            await db.use(NS, DB_NAME)
            print("  Registros por tabela:")
            for t in TABELAS:
                try:
                    res = await db.query(f"SELECT count() FROM {t} GROUP ALL")
                    n   = res[0]["result"][0].get("count", 0) \
                          if res and res[0].get("result") else 0
                    print(f"    {t:<35} {n:>10,}")
                except Exception:
                    print(f"    {t:<35}      (erro ao contar)")
    except Exception:
        pass
    print()


if __name__ == "__main__":
    asyncio.run(main())
