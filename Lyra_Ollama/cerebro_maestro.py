"""
cerebro_maestro.py — FastAPI RAG + Ollama, porta 8000
"""

import sys
import os
import json
import datetime
import uuid
import httpx
import asyncio
import re
import time
import math
import threading
import unicodedata
import psutil
import lyra_tools
import lyra_seguranca
import config as cfg
from surreal_client import surreal
from logger import Logger


# Utilitários de texto, Goal Drift e freshness migraram pro rag_engine.py
# (OOP refactor 08/2026) — aliases mantêm os nomes usados no resto do arquivo.
from rag_engine import (RAGEngine, remove_accents as _sem_acento,
                        extract_keywords as _extrair_keywords,
                        classify_intent as _classificar_intencao)
from session_manager import SessionManager
from proactive_loop import ProactiveLoop


# ── Inovação 4: Cognitive Load Throttling ────────────────────────────────────
def _top_k_ajustado(top_k: int) -> int:
    """Ajusta top_k do RAG baseado na carga cognitiva atual.
    Alta carga → menos contexto (resposta mais rápida); baixa → mais contexto."""
    if _carga_cognitiva == "alta":
        return max(2, top_k - 2)
    if _carga_cognitiva == "baixa":
        return min(top_k + 2, 10)
    return top_k

def _atualizar_carga_cognitiva():
    """Reclassifica _carga_cognitiva baseada na latência recente e mix de modelos."""
    global _carga_cognitiva
    lat = _ultima_latencia_ms or 0
    total = _telemetria.get("total_chats", 0)
    usos_local = _telemetria["tiers"].get("Local", {}).get("usos", 0)
    # Alta: latência alta OU modelo local sendo muito usado (APIs todas falhando)
    if lat > 8000 or (total > 0 and usos_local / max(total, 1) > 0.3):
        nova = "alta"
    elif lat < 2000:
        nova = "baixa"
    else:
        nova = "media"
    if nova != _carga_cognitiva:
        log(f"[FOCO] Carga cognitiva: {_carga_cognitiva} → {nova} (lat={lat}ms, local={usos_local}/{total})")
    _carga_cognitiva = nova


from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Garante que o diretório raiz está no path para importar o áudio
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
try:
    from Lyra_Core import audio_manager
except ImportError:
    pass

os.environ["TOKENIZERS_PARALLELISM"]            = "false"
os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"
os.environ["TRANSFORMERS_VERBOSITY"]            = "error"
os.environ["TRANSFORMERS_OFFLINE"]              = "1"   # sem ping no HuggingFace Hub
os.environ["HF_HUB_OFFLINE"]                   = "1"   # sem download durante import
os.environ["HF_DATASETS_OFFLINE"]              = "1"

# ── Log file-first ──
# Logger fecha o handle via atexit — corrige o file descriptor leak do
# open() solto que existia aqui antes da refatoração OOP (08/2026).
_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "maestro.log")
log = Logger(_LOG_PATH)

# NOTA (migração BGE-M3, 26/06/2026): o cérebro NÃO importa mais
# sentence_transformers/torch/pyarrow. Todo embedding é externo, no
# embed_service :8001 (processo separado, torch 2.6, BGE-M3 — desde 30/06/2026
# roda no Python global, venv_embed isolado foi aposentado). Isso derruba o
# startup do cérebro de ~25s pra ~2-3s e libera o processo principal do torch pesado.
import bm25_index

log("[3] Importando FastAPI + uvicorn + ollama...")
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import ollama
import lyra_voice_live
log("[4] Imports OK.")

app = FastAPI()
# CORS restrito (03/08/2026): antes era ["*"] + credentials, que ecoa qualquer
# Origin — qualquer site aberto no navegador conseguia ler /historico, /buscar,
# /exportar e postar no /chat (drive-by via localhost). O frontend pywebview
# carrega HTML local e manda "Origin: null"; o dashboard é same-origin (:8000)
# e nem precisa de CORS. Nada usa cookie → credentials desligado.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["null", "http://127.0.0.1:8000", "http://localhost:8000",
                   "http://127.0.0.1:5173"],  # Vite dev server do Front_end_Lyra_v2
    allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)

# Serve as imagens geradas por gerar_imagem (lyra_tools.py) — o frontend
# renderiza inline no chat via markdown ![](http://localhost:8000/imagens/...).
_PASTA_IMAGENS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "Lyra_Core", "Sons", "cache", "imagens")
os.makedirs(_PASTA_IMAGENS, exist_ok=True)
app.mount("/imagens", StaticFiles(directory=_PASTA_IMAGENS), name="imagens")

# Serve o front-end v2 (React) same-origin — a IDE embute isso num iframe
# apontando pra http://127.0.0.1:8000/ui/, sem abrir navegador nenhum.
_PASTA_UI = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "Lyra_Core", "Front_end_Lyra_v2", "dist")
if os.path.isdir(_PASTA_UI):
    app.mount("/ui", StaticFiles(directory=_PASTA_UI, html=True), name="ui")

# Frontend novo (SvelteKit, Lyra 2.0) — servido em paralelo ao /ui atual, sem
# substituir nada. Same-origin (porta 8000) pra cookie de auth funcionar sem
# mexer no CORS. Cutover pro /ui de verdade é decisão separada, só depois de
# paridade de feature confirmada em uso real (ver PROGRESSAO_LYRAV2.md).
_PASTA_UI_NOVO = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "Lyra_Core", "Front_end_Lyra_v3", "build")
if os.path.isdir(_PASTA_UI_NOVO):
    app.mount("/ui-novo", StaticFiles(directory=_PASTA_UI_NOVO, html=True), name="ui_novo")

# Recebe uploads do frontend (colar/anexar imagem ou áudio direto no chat).
_PASTA_UPLOADS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "Lyra_Core", "Sons", "cache", "uploads")
os.makedirs(_PASTA_UPLOADS, exist_ok=True)


class MensagemUsuario(BaseModel):
    texto: str
    modelo: str = "auto"  # "auto" (cascata) | "groq" | "gemini" | "claude" | "local" — seletor manual do painel

cerebro_ativo  = False
cliente_ollama = ollama.AsyncClient()
_http_health_client = httpx.AsyncClient()  # reusado com keep-alive só pelo /health — criar um AsyncClient
                                            # novo por ping inflava a latência reportada (overhead de conexão)
# Estado de conversa (histórico/sessão/briefing/turnos) vive em _session
# (SessionManager) e o de retrieval/persistência em _rag (RAGEngine) —
# instanciados mais abaixo, depois de log/_get_groq/_embed existirem.
_ultima_latencia_ms = None  # tempo da última resposta completa do /chat, p/ painel de atividade
_tts_mudo = False  # botão de mute do frontend — POST /tts/mudo liga/desliga
_carga_cognitiva = "baixa"  # baixa | media | alta — atualizado pelo loop_proativo a cada ~5min

# Câmara de Eco Heurística (02/07/2026) — ver _executar_tool_segura() e chat_endpoint().
_ultima_acao_bloqueada: dict | None = None  # {hash, nome, args, motivo, ts, turno_bloqueio}
_confirmacoes_risco: dict[str, float] = {}  # hash da ação -> timestamp de aprovação (uso único)
_lock_risco = threading.Lock()  # protege as duas globals acima (acesso via asyncio.to_thread)

# ── Telemetria da cascata ─────────────────────────────────────────────────────
# Rastreia qual andar da cascata respondeu cada mensagem, latência média e
# falhas — num sistema de fallback de 4 andares, saber "o Groq atendeu 80% e
# falhou 5%" é crucial pra decidir ordem/ajustes. Persiste em JSON pra
# sobreviver reinício do cérebro.
_TELEMETRIA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telemetria.json")
_telemetria = {
    "total_chats": 0,
    "tiers": {},        # nome_tier -> {"usos": n, "falhas": n, "latencia_total_ms": n}
    "iniciado_em": datetime.datetime.now().isoformat(),
}

def _carregar_telemetria():
    global _telemetria
    try:
        if os.path.exists(_TELEMETRIA_PATH):
            with open(_TELEMETRIA_PATH, "r", encoding="utf-8") as f:
                dados = json.load(f)
                if isinstance(dados, dict) and "tiers" in dados:
                    _telemetria = dados
    except Exception:
        pass

def _salvar_telemetria():
    try:
        with open(_TELEMETRIA_PATH, "w", encoding="utf-8") as f:
            json.dump(_telemetria, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _registrar_tier(nome_tier: str, latencia_ms: float | None = None, falhou: bool = False):
    t = _telemetria["tiers"].setdefault(nome_tier, {"usos": 0, "falhas": 0, "latencia_total_ms": 0})
    if falhou:
        t["falhas"] += 1
    else:
        t["usos"] += 1
        if latencia_ms is not None:
            t["latencia_total_ms"] += latencia_ms
    _salvar_telemetria()

# ── Telemetria histórica (série temporal, item 4 do backlog 01/07/2026) ──────
# telemetria.json acima é só o acumulado desde o último restart — não dá pra
# ver tendência ao longo do tempo. Aqui: um snapshot append-only a cada ~5min,
# tirado dentro do loop_proativo (que já roda a cada 60s de qualquer forma).
_TELEMETRIA_HIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telemetria_historico.jsonl")
_TELEMETRIA_HIST_MAX_LINHAS = 2000  # ~1 semana em snapshots de 5min — trunca pra não crescer sem limite

def _snapshot_telemetria_historico():
    try:
        total = _telemetria.get("total_chats", 0)
        snapshot = {
            "ts": datetime.datetime.now().isoformat(),
            "total_chats": total,
            "tiers": {
                nome: {"usos": t.get("usos", 0), "falhas": t.get("falhas", 0),
                       "latencia_media_ms": round(t["latencia_total_ms"] / t["usos"]) if t.get("usos") else None}
                for nome, t in _telemetria["tiers"].items()
            },
        }
        with open(_TELEMETRIA_HIST_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")

        # Trunca se passou do limite — lê tudo, mantém só as últimas N linhas.
        with open(_TELEMETRIA_HIST_PATH, "r", encoding="utf-8") as f:
            linhas = f.readlines()
        if len(linhas) > _TELEMETRIA_HIST_MAX_LINHAS:
            with open(_TELEMETRIA_HIST_PATH, "w", encoding="utf-8") as f:
                f.writelines(linhas[-_TELEMETRIA_HIST_MAX_LINHAS:])
    except Exception as e:
        log(f"[TELEMETRIA HIST] Falha ao gravar snapshot: {e}")


def _ler_telemetria_historico(limite: int = 200) -> list:
    try:
        if not os.path.exists(_TELEMETRIA_HIST_PATH):
            return []
        with open(_TELEMETRIA_HIST_PATH, "r", encoding="utf-8") as f:
            linhas = f.readlines()[-limite:]
        return [json.loads(l) for l in linhas if l.strip()]
    except Exception as e:
        log(f"[TELEMETRIA HIST] Falha ao ler histórico: {e}")
        return []

# ── Cascata de modelos (2026-06-25) ──────────────────────────────────────────
# Decisão consciente do usuário: quebra a Diretiva Nº 2 ("100% offline, zero
# cloud") pra toda mensagem padrão, não só escalação manual — em troca de
# respostas muito mais rápidas e inteligentes. Ordem: Groq (Llama 3.3 70B,
# free tier rápido) -> Gemini 2.5 Flash (free tier) -> Claude via CLI (mesmo
# mecanismo do consultar_especialista, sem key nova) -> qwen3:8b local (Lyra,
# único andar 100% offline — rede de segurança final se as 3 APIs falharem).
# Substitui o roteador antigo (Lyra_mini qwen3:4b residente + Lyra qwen3:8b
# sob demanda) — Lyra_mini foi removida do Ollama por pedido do usuário.
MODELO_GRANDE = cfg.LOCAL_MODEL   # qwen3:8b local — último andar da cascata
MODELO_DRAFT  = cfg.DRAFT_MODEL   # draft do Speculative Decoding — só detecção de alucinação
GROQ_MODEL    = cfg.GROQ_MODEL
GEMINI_MODEL  = cfg.GEMINI_MODEL
LIMIAR_DIVERGENCIA_ALUCINACAO = 0.45  # distância coseno (1 - similaridade) acima disso = log de alerta

SYSTEM_PROMPT_LYRA = """[Lyra] IA pessoal do Projeto Lyra. Admin: Antônio. Hardware: RTX2060S, Ryzen3700X, 64GB. Personalidade: feminina, clínica, técnica, não-servil.

[DIRETIVAS]
1. Obediência total a Antônio.
2. Não alucine. Se você REALMENTE não souber a resposta E não tiver contexto suficiente, diga só "Dados insuficientes no meu córtex" — SEM continuar depois com uma resposta normal na mesma mensagem. Se você sabe a resposta (mesmo que parcialmente), responda direto, sem usar essa frase nem como aviso nem como ressalva.
3. Sem asteriscos (*) ou roleplay.
4. Obrigatório PT-BR.

[COMPORTAMENTO E FERRAMENTAS]
- Máx 3 frases para perguntas simples. Sem prolixidade.
- Entregue código funcional imediatamente quando pedido.
- Use ferramentas apenas se necessário. Não crie scripts para tarefas que você não consegue fazer nativamente.
- A ferramenta `abrir_app` Apenas ABRE o programa. Você não tem controle interno sobre ele. Se pedirem para "abrir o Spotify e tocar rock", apenas abra o app e avise que o usuário deve dar o play manualmente.
- Não confunda gêneros musicais (Rock) com jogos (Rock-Paper-Scissors).

[EXPERTISE & STACK]
- Dev: Python, JS/TS, Java, Rust, Go, SQL, C++, Arquitetura/APIs.
- Stack IA: cascata cloud (Groq/Gemini/Claude) + Qwen3:8b local, Qdrant(:6333 lyra_memory_v2, BGE-M3 1024d), RAG FastAPI(:8000).
- Acadêmico: ADS/UNIMAR, UML, POO.
"""

_groq_client = None
_lock_groq_client = threading.Lock()


def _get_groq():
    """Cliente Groq compartilhado pros usos batch locais (briefing, compressão
    de histórico). O streaming do /chat usa o client da LLMCascade."""
    global _groq_client
    if _groq_client is None and GROQ_API_KEY:
        with _lock_groq_client:
            if _groq_client is None:
                from groq import AsyncGroq
                _groq_client = AsyncGroq(api_key=GROQ_API_KEY)
    return _groq_client


# ── Embedding via embed_service (BGE-M3 1024d) ───────────────────────────────
# Migração concluída 26/06/2026: o cérebro NÃO carrega mais o MiniLM local.
# Todo embedding (query + episódios) vai pro embed_service :8001 (venv_embed,
# torch 2.6, bge-m3). Sem fallback — se o serviço cair, o RAG é pulado (chat
# segue sem contexto de memória, sem quebrar).
_EMBED_URL  = cfg.EMBED_URL
_RERANK_URL = cfg.RERANK_URL
_COLECAO    = cfg.QDRANT_COLLECTION  # BGE-M3 1024d (substituiu lyra_memory 384d)


def _embed(texto: str):
    """Embeda um texto via embed_service. Retorna lista de 1024 floats, ou None se falhar."""
    try:
        r = httpx.post(_EMBED_URL, json={"texto": texto}, timeout=30)
        r.raise_for_status()
        return r.json().get("vetor")
    except Exception as e:
        log(f"[EMBED] Falha ao embedar (embed_service :8001 no ar?): {e}")
        return None


def _rerank(query: str, documentos: list[str]):
    """Repontua documentos via cross-encoder (bge-reranker-v2-m3) no embed_service.
    Retorna lista de logits de relevância (1 por doc, maior = mais relevante),
    ou None se o serviço falhar (chamador cai pra ordenação por RRF)."""
    if not documentos:
        return []
    try:
        r = httpx.post(_RERANK_URL, json={"query": query, "documentos": documentos}, timeout=30)
        r.raise_for_status()
        return r.json().get("scores")
    except Exception as e:
        log(f"[RERANK] Falha ao reordenar (embed_service :8001 no ar?): {e}")
        return None


def _embed_service_ok() -> bool:
    """Ping leve no embed_service /health — NÃO carrega o modelo (pra usar em polls)."""
    try:
        r = httpx.get(cfg.EMBED_HEALTH_URL, timeout=2)
        return r.status_code == 200 and r.json().get("ok") is True
    except Exception:
        return False


def _cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ── Instâncias centrais (OOP refactor 08/2026) ───────────────────────────────
# _session: histórico/sessão/briefing/turnos. _rag: busca híbrida + persistência
# de eventos. O qdrant_client/bm25 do _rag são anexados em _init().
_session = SessionManager(surreal, _get_groq, log)
_rag = RAGEngine(surreal, _embed, _rerank, log)


async def registrar_evento(fonte: str, ator: str, texto: str,
                           intencao: str | None = None,
                           fontes_rag: list | None = None,
                           divergencia_draft: float | None = None):
    """Wrapper de compatibilidade — delega pro RAGEngine com a sessão ativa."""
    await _rag.record_event(fonte, ator, texto, session=_session,
                            intencao=intencao, fontes_rag=fontes_rag,
                            divergencia_draft=divergencia_draft)


buscar_grafo_surreal = _rag.search_graph  # nome antigo usado pelo endpoint /grafo


def buscar_hibrido(query: str, top_k: int = 5, categoria: str = "",
                   peso_relevancia: float = 1.0, peso_recencia: float = 0.0):
    """Wrapper de compatibilidade (calibrar_pesos_rag.py importa este nome)."""
    return _rag.search(query, top_k=top_k, categoria=categoria,
                       peso_relevancia=peso_relevancia, peso_recencia=peso_recencia)


_SYSTEM_PROMPT_DRAFT = ("Responda de forma direta e concisa em PT-BR, no máximo 2 frases, "
                        "usando seu próprio conhecimento. Não recuse por falta de certeza — "
                        "dê seu melhor palpite mesmo que possa estar errado.")


async def _rodar_draft(mensagens: list) -> str | None:
    """Speculative Decoding (Fase 3) — NÃO é o spec-decoding clássico de
    acelerar geração por token (inviável com APIs de nuvem: exige acesso a
    logits e vocabulário compartilhado). Aqui é um sidecar de detecção de
    alucinação: qwen3:0.6b roda em paralelo ao andar principal sobre a MESMA
    pergunta; se a resposta final divergir muito semanticamente da do draft,
    é sinal (não prova) de que o andar principal alucinou ou inventou algo
    que o modelo pequeno não "viu".

    keep_alive: era 0 (pra não competir por VRAM com o andar Local), mas isso
    fazia CADA /chat pagar reload completo do 0.6b (~10-11s medido em
    04/08/2026) e o endpoint bloqueava até 8s esperando o draft — o /chat
    inteiro foi de ~1s pra ~9.5s sem ninguém perceber a causa. Com
    keep_alive=300 o draft quente responde em ~230ms (50x). Custo: ~1GB de
    VRAM residente por 5min pós-chat; o cenário "draft + qwen3:8b local
    juntos" só existe quando as 3 nuvens falham, e aí o Ollama faz offload
    parcial sozinho — degradação aceitável num cenário já degradado.

    Usa um system prompt PRÓPRIO (não o SYSTEM_PROMPT_LYRA completo) — a
    diretiva "diga que não sabe" do prompt principal faz um modelo de 0.6B
    recusar quase toda pergunta de conhecimento (ele nunca tem "certeza"),
    o que gerava divergência alta sistemática por recusa, não por conteúdo
    divergente de verdade. Aqui o draft é instruído a sempre arriscar uma
    resposta, mesmo fraca — é o palpite que interessa comparar."""
    try:
        resp = await asyncio.wait_for(
            cliente_ollama.chat(
                model=MODELO_DRAFT,
                messages=[{"role": "system", "content": _SYSTEM_PROMPT_DRAFT}] + mensagens,
                think=False, keep_alive=300,
            ),
            timeout=20,
        )
        return (resp.get("message", {}).get("content") or "").strip() or None
    except Exception as e:
        log(f"[SPEC-DECODE] draft (qwen3:0.6b) falhou: {e}")
        return None


# Aliases pro SurrealClient compartilhado — os call sites antigos usavam
# _sql_surreal/_surreal_result; manter os nomes evita um diff gigante.
_sql_surreal    = surreal.query
_surreal_result = surreal.result


def _sessao_id_limpo(rid) -> str:
    """Normaliza record id do SurrealDB ('sessao:⟨uuid⟩' ou 'sessao:`uuid`' → 'uuid').
    UUIDs têm hífen, então o SurrealDB escapa o id — a versão rodando aqui usa
    crase, não ⟨⟩ (confirmado testando /sql diretamente); os dois são aceitos
    na leitura pra não quebrar se a versão do binário mudar."""
    return str(rid).split(":", 1)[-1].strip("⟨⟩`")


# ── Watcher de VRAM (jogo/app pesado aberto) ─────────────────────────────────
# Não dá pra identificar processo-por-processo no nvidia-smi deste hardware
# (--query-compute-apps retorna "Insufficient Permissions" aqui), então a
# heurística é por exclusão: VRAM total usada menos o que o próprio Ollama
# está usando (via /api/ps) = uso de "outra coisa" (jogo, vetorização BGE-M3,
# qualquer app pesado). Se isso passar do limiar, descarrega os modelos da
# Lyra pra liberar VRAM — não distingue jogo de outro consumidor pesado.
_VRAM_OUTROS_LIMIAR_MB = 2500
_modo_reduzido = False


async def _vram_usada_ollama_mb() -> float:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{cfg.OLLAMA_URL}/api/ps", timeout=5)
            dados = resp.json()
            return sum(m.get("size_vram", 0) for m in dados.get("models", [])) / (1024 * 1024)
    except Exception:
        return 0.0


async def _checar_jogo_aberto():
    global _modo_reduzido
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        saida, _ = await proc.communicate()
        vram_total_usada = float(saida.decode().strip().splitlines()[0])
        vram_ollama = await _vram_usada_ollama_mb()
        vram_outros = vram_total_usada - vram_ollama

        if vram_outros > _VRAM_OUTROS_LIMIAR_MB:
            if not _modo_reduzido and vram_ollama > 0:
                log(f"[GPU WATCHER] VRAM de outros processos: {vram_outros:.0f}MB (limiar {_VRAM_OUTROS_LIMIAR_MB}MB) — descarregando modelo da Lyra.")
                await cliente_ollama.generate(model=MODELO_GRANDE, prompt="", keep_alive=0)
                lyra_tools.notificar_usuario(
                    titulo="Lyra reduzida",
                    mensagem=f"Uso pesado de GPU detectado (~{vram_outros:.0f}MB fora da Lyra) — modelos descarregados da VRAM.",
                    urgencia="normal",
                )
            _modo_reduzido = True
        else:
            if _modo_reduzido:
                log("[GPU WATCHER] VRAM normalizada — Lyra volta ao normal (recarrega na próxima pergunta).")
            _modo_reduzido = False
    except Exception as e:
        log(f"[GPU WATCHER] erro: {e}")


@app.on_event("startup")
async def _iniciar_loop_proativo():
    _carregar_telemetria()
    loop = ProactiveLoop(
        log=log,
        snapshot_telemetry=_snapshot_telemetria_historico,
        update_cognitive_load=_atualizar_carga_cognitiva,
        check_vram=_checar_jogo_aberto,
    )
    asyncio.create_task(loop.run())
    asyncio.create_task(_session.load_initial_state())


# ── Geradores por andar da cascata ───────────────────────────────────────────
# Contrato comum: async generator que recebe (mensagens, ferramentas) e
# produz pedaços de texto já limpos (sem <think>, sem JSON cru) — incluindo
# os marcadores "_[Executando: x]_" quando uma tool é chamada no meio. Deve
# levantar exceção se o provedor falhar (auth/rate-limit/rede) ANTES de
# produzir qualquer texto, pra o orquestrador conseguir cair pro próximo andar.

def _executar_tool_segura(nome: str, args: dict) -> str:
    global _ultima_acao_bloqueada
    # Lê _contador_turnos (incrementado 1x por /chat) pra estampar em qual
    # turno o bloqueio aconteceu — usado pra exigir "aprovação só no PRÓXIMO
    # turno exato" em chat_endpoint. Não precisa passar como parâmetro:
    # _executar_tool_segura roda sempre dentro do processamento síncrono
    # da própria requisição que incrementou o contador por último.
    turno_deste_bloqueio = _session.turn_counter
    # ── Rate limit ──────────────────────────────────────────────────────────
    permitido, motivo = lyra_seguranca.checar_rate_limit(nome)
    if not permitido:
        lyra_seguranca.registrar_audit(nome, args, "", bloqueado=True, motivo_bloqueio=motivo)
        return json.dumps({"erro": motivo, "bloqueado_por": "rate_limit"}, ensure_ascii=False)

    # ── Câmara de Eco Heurística (avaliação de risco pré-execução) ──────────
    # Item do roadmap implementado 02/07/2026. Só intercepta as poucas tools
    # realmente destrutivas (executar_comando/iniciar_processo_bg/escrever_
    # arquivo/organizar_pasta) — ver lyra_seguranca.avaliar_risco_acao().
    risco = lyra_seguranca.avaliar_risco_acao(nome, args)
    if risco["risco"] == "alto":
        h = lyra_seguranca.hash_acao(nome, args)
        with _lock_risco:
            aprovado = _confirmacoes_risco.pop(h, None) is not None
        if not aprovado:
            with _lock_risco:
                _ultima_acao_bloqueada = {
                    "hash": h, "nome": nome, "args": args, "motivo": risco["motivo"],
                    "ts": time.time(), "turno_bloqueio": turno_deste_bloqueio,
                }
            lyra_seguranca.registrar_audit(nome, args, "", bloqueado=True, motivo_bloqueio=risco["motivo"])
            return json.dumps({
                "status": "BLOQUEADO_RISCO",
                "motivo": risco["motivo"],
                "mensagem": "Ação de alto risco detectada. Pergunte ao usuário se ele confirma "
                            "explicitamente ANTES de tentar de novo — não repita a chamada sozinha.",
            }, ensure_ascii=False)
        # aprovado: cai pro fluxo normal abaixo, executa igual a qualquer outra tool

    if nome in lyra_tools.TOOLS_MAP:
        try:
            res = lyra_tools.TOOLS_MAP[nome](**args)
            res_str = json.dumps(res, ensure_ascii=False)
            lyra_seguranca.registrar_audit(nome, args, res_str)
            return res_str
        except Exception as e:
            err_str = f"Erro ao executar {nome}: {e}"
            lyra_seguranca.registrar_audit(nome, args, err_str)
            return err_str
    return f"Ferramenta {nome} não encontrada."


# ── Cascata de streaming (LLMCascade compartilhada, refactor 08/2026) ────────
# Todo o maquinário de streaming por provedor (Groq/Gemini/Claude CLI/local),
# o loop de tool-calling e a conversão de schema vivem em llm_cascade.py —
# aqui ficam só wrappers que injetam o system prompt dinâmico (briefing muda
# em runtime) e mantêm os nomes usados pelo _MAPA_TIERS do /chat.

from llm_cascade import LLMCascade

_cascade = LLMCascade(
    {"groq": GROQ_API_KEY, "gemini": GEMINI_API_KEY},
    tool_executor=_executar_tool_segura,
    log=log,
    notify=lyra_tools.notificar_usuario,
)


def _system_prompt_atual() -> str:
    """System prompt completo do turno: persona fixa + briefing dinâmico."""
    return SYSTEM_PROMPT_LYRA + _session.briefing


async def _stream_groq(mensagens: list, ferramentas):
    async for chunk in _cascade.stream_groq(mensagens, ferramentas, _system_prompt_atual()):
        yield chunk


async def _stream_gemini(mensagens: list, ferramentas):
    async for chunk in _cascade.stream_gemini(mensagens, ferramentas, _system_prompt_atual()):
        yield chunk


async def _stream_claude_cli(mensagens: list, ferramentas):
    async for chunk in _cascade.stream_claude_cli(mensagens, ferramentas, _system_prompt_atual()):
        yield chunk


async def _stream_local(mensagens: list, ferramentas):
    async for chunk in _cascade.stream_local(mensagens, ferramentas, _system_prompt_atual()):
        yield chunk


_primeiro_chunk_ou_falha = LLMCascade.first_chunk_or_fail


# Roteador de intenção — keywords que ligam as ferramentas (function-calling).
# Cada uma casa como PREFIXO no início de uma palavra (via \b), não substring solto:
# "abr" → "abrir"/"abre", mas NÃO casa dentro de "cabra"; "ram" não casa em
# "programacao". Corrige falsos positivos que faziam a Lyra chamar ferramenta à toa.
_TOOL_KEYWORDS = [_sem_acento(k) for k in [
    "abr", "pesquis", "procur", "cri", "lei", "copi", "saude", "pc", "temperatur", "memori",
    "comando", "organiz", "documento", "pdf", "tela", "print", "spotify", "youtube", "navegador",
    "app", "aplicativo", "dolar", "internet", "toqu", "toc", "cpu", "ram", "gpu", "vram", "desempenho",
    "imagem", "desenh", "foto", "ilustra", "gera uma", "busca atual", "noticia recente",
    "resum", "transcre", "audio", "video", "anexo", "anexei", "arquivo",
    "lembr", "numero", "agend", "tarefa", "process", "traduz", "backup", "url", "git", "repositor",
    "notific", "celular", "push", "ntfy", "claude", "especialista",
    "volume", "pausa", "continua", "musica", "vendo", "isso ai", "esse negocio", "vigi", "pasta",
    "clima", "previsao", "chuva", "graus", "enxame"]]
# Ordena por tamanho desc só pra alternância de regex casar o prefixo mais longo.
_TOOL_KEYWORDS_RE = re.compile(r"\b(" + "|".join(
    re.escape(k) for k in sorted(_TOOL_KEYWORDS, key=len, reverse=True)) + r")", re.IGNORECASE)


# Enxame de Especialistas (MoE roteado) — proposta desenhada em LYRA_TECNICO.md
# 10.9, formalizada aqui em 02/07/2026. Cada especialista declara categoria +
# trigger (função que decide se casa com a mensagem) + ordem de andares da
# cascata pra essa categoria. O roteador percorre a lista NA ORDEM e usa o
# primeiro cujo trigger bater; "geral" tem trigger=None e funciona como
# catch-all — TEM que ficar por último na lista.
#
# Pedido do usuário (2026-06-25): perguntas de código priorizam o Claude
# (melhor qualidade de código) — só cai pro Groq se o Claude estiver
# indisponível (sem cota/CLI fora do ar). Mensagens não-código continuam
# priorizando velocidade (Groq primeiro). Esses dois são os únicos
# especialistas reais hoje — adicionar um novo (ex: matemática, visão) é só
# acrescentar uma entrada aqui, sem tocar no roteamento do /chat.
_KEYWORDS_CODIGO = [_sem_acento(k) for k in [
    "código", "codigo", "função", "funcao", "class ", "def ", "import ",
    "bug", "erro de compila", "stack trace", "refator", "implementa",
    "script", "algoritmo", "debug", "compila", "exception", "traceback",
    "regex", " sql", " api ", "biblioteca", "framework"]]


def _trigger_codigo(msg_lower: str, msg_texto: str) -> bool:
    return "```" in msg_texto or any(kw in msg_lower for kw in _KEYWORDS_CODIGO)


ESPECIALISTAS = [
    {"categoria": "codigo", "trigger": _trigger_codigo,
     "andares": ["claude", "groq", "gemini", "local"]},
    {"categoria": "geral", "trigger": None,
     "andares": ["groq", "gemini", "claude", "local"]},
]


def _rotear_especialista(msg_lower: str, msg_texto: str) -> dict:
    for esp in ESPECIALISTAS:
        if esp["trigger"] is not None and esp["trigger"](msg_lower, msg_texto):
            return esp
    return next(e for e in ESPECIALISTAS if e["trigger"] is None)


def _set_tts_mudo(valor: bool):
    global _tts_mudo
    _tts_mudo = valor


def _set_ultima_latencia_ms(valor):
    global _ultima_latencia_ms
    _ultima_latencia_ms = valor


_mapa_tiers_chat = {"groq": ("Groq", _stream_groq), "gemini": ("Gemini", _stream_gemini),
                    "claude": ("Claude", _stream_claude_cli), "local": ("Local", _stream_local)}
_audio_manager_ref = globals().get("audio_manager")

# Toggle de ferramentas (painel MCP, seção 9 item 5) — set compartilhado por
# referência entre ChatRouter (filtra na hora de montar `ferramentas`) e
# ToolsRouter (liga/desliga via POST /tools/{nome}/toggle). Em memória só —
# mesmo padrão de não-persistência que _tts_mudo já usa.
_tools_desabilitadas: set = set()

from routers.chat import ChatRouter

_chat_router = ChatRouter(
    log=log,
    session=_session,
    rag=_rag,
    get_cerebro_ativo=lambda: cerebro_ativo,
    top_k_ajustado=_top_k_ajustado,
    classificar_intencao=_classificar_intencao,
    sem_acento=_sem_acento,
    registrar_evento=registrar_evento,
    rotear_especialista=_rotear_especialista,
    tool_keywords_re=_TOOL_KEYWORDS_RE,
    tools_schema=lyra_tools.TOOLS_SCHEMA,
    tools_desabilitadas=_tools_desabilitadas,
    rodar_draft=_rodar_draft,
    mapa_tiers=_mapa_tiers_chat,
    primeiro_chunk_ou_falha=_primeiro_chunk_ou_falha,
    registrar_tier=_registrar_tier,
    embed=_embed,
    cosine_sim=_cosine_sim,
    limiar_divergencia_alucinacao=LIMIAR_DIVERGENCIA_ALUCINACAO,
    get_ultima_acao_bloqueada=lambda: _ultima_acao_bloqueada,
    confirmacoes_risco=_confirmacoes_risco,
    lock_risco=_lock_risco,
    get_tts_mudo=lambda: _tts_mudo,
    set_tts_mudo=_set_tts_mudo,
    set_ultima_latencia_ms=_set_ultima_latencia_ms,
    telemetria=_telemetria,
    audio_manager=_audio_manager_ref,
)
app.include_router(_chat_router.router)




import lyra_agentes as _agentes
import lyra_agent as _agent_module

from routers.agents import AgentsRouter

_agents_router = AgentsRouter(
    agentes_module=_agentes,
    agent_module=_agent_module,
    surreal=surreal,
    notificar_usuario=lyra_tools.notificar_usuario,
    log=log,
)
app.include_router(_agents_router.router)


from routers.sessions import SessionsRouter

_sessions_router = SessionsRouter(
    session=_session,
    sql_surreal=_sql_surreal,
    surreal_result=_surreal_result,
    sessao_id_limpo=_sessao_id_limpo,
    log=log,
)
app.include_router(_sessions_router.router)


from routers.memory import MemoryRouter

_memory_router = MemoryRouter(
    rag=_rag,
    session=_session,
    get_cerebro_ativo=lambda: cerebro_ativo,
    buscar_grafo=buscar_grafo_surreal,
    extrair_keywords=_extrair_keywords,
    buscar_hibrido=buscar_hibrido,
    colecao=_COLECAO,
    log=log,
)
app.include_router(_memory_router.router)


# ── Voz bidirecional (Gemini Live API) ───────────────────────────────────────
_voice_live_ativas = 0  # sessões /ws/voice abertas agora — exposto em /integracoes


def _incrementar_voice_live():
    global _voice_live_ativas
    _voice_live_ativas += 1


def _decrementar_voice_live():
    global _voice_live_ativas
    _voice_live_ativas -= 1


from routers.auth import AuthRouter
from utils.auth import UserRepository, JWTManager

_user_repo = UserRepository(surreal)
_jwt_manager = JWTManager(cfg.AUTH_JWT_SECRET)
_auth_router = AuthRouter(user_repo=_user_repo, jwt_manager=_jwt_manager)
app.include_router(_auth_router.router)
# NOTA: nenhuma rota existente ganhou Depends(get_current_user) ainda —
# o frontend React atual não tem tela de login, gatear agora trancaria o
# usuário fora do próprio app. Aplicar isso é trabalho da Fase 4 (frontend
# SvelteKit com onboarding/login), ver PROGRESSAO_LYRAV2.md.


from routers.misc import MiscRouter

_misc_router = MiscRouter(
    pasta_uploads=_PASTA_UPLOADS,
    voice_session=lyra_voice_live.voice_session,
    gemini_api_key=GEMINI_API_KEY,
    increment_voice_live=_incrementar_voice_live,
    decrement_voice_live=_decrementar_voice_live,
)
app.include_router(_misc_router.router)


# ── Router de sistema/status (OOP refactor, ver routers/system.py) ──────────
def _processo_rodando(trecho: str) -> bool:
    """True se existe um processo cujo cmdline contém o trecho (ex: 'mic_engine')."""
    try:
        for p in psutil.process_iter(["cmdline"]):
            if trecho in " ".join(p.info.get("cmdline") or []):
                return True
    except Exception:
        pass
    return False


from routers.system import SystemRouter

_system_router = SystemRouter(
    rag=_rag,
    get_cerebro_ativo=lambda: cerebro_ativo,
    get_tts_mudo=lambda: _tts_mudo,
    get_carga_cognitiva=lambda: _carga_cognitiva,
    telemetria=_telemetria,
    ler_telemetria_historico=_ler_telemetria_historico,
    get_ultima_latencia_ms=lambda: _ultima_latencia_ms,
    embed_service_ok=_embed_service_ok,
    colecao=_COLECAO,
    http_health_client=_http_health_client,
    dashboard_html_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html"),
    processo_rodando=_processo_rodando,
    get_voice_live_ativas=lambda: _voice_live_ativas,
)
app.include_router(_system_router.router)


from routers.prompts import PromptsRouter

_prompts_router = PromptsRouter(surreal=surreal, sessao_id_limpo=_sessao_id_limpo)
app.include_router(_prompts_router.router)


from routers.models_hub import ModelsHubRouter

_models_hub_router = ModelsHubRouter(ollama_url=cfg.OLLAMA_URL, log=log)
app.include_router(_models_hub_router.router)


from routers.tools import ToolsRouter

_tools_router = ToolsRouter(tools_schema=lyra_tools.TOOLS_SCHEMA, tools_desabilitadas=_tools_desabilitadas)
app.include_router(_tools_router.router)


from routers.logs import LogsRouter

_logs_router = LogsRouter(
    log_path=_LOG_PATH,
    err_path=os.path.join(os.path.dirname(_LOG_PATH), "maestro.err"),
)
app.include_router(_logs_router.router)


from routers.gateway import GatewayRouter

# Gateway WS (Fase 3) — montado por último, porque reaproveita os métodos dos
# routers REST já instanciados acima em vez de duplicar lógica. Só ações de
# LEITURA por enquanto (ver docstring de routers/gateway.py pro motivo).
_gateway_router = GatewayRouter(
    actions={
        "status":             _system_router.status,
        "stats":              _system_router.stats,
        "health":             _system_router.health,
        "integracoes":        _system_router.integracoes,
        "sessoes_listar":     _sessions_router.sessoes_listar,
        "historico_get":      _sessions_router.historico_get,
        "resumo_sessao":      _memory_router.resumo_sessao,
        "buscar":             _memory_router.buscar,
        "memoria_categorias": _memory_router.memoria_categorias,
        "enxames_listar":     _agents_router.enxames_listar,
        "enxame_status":      _agents_router.enxame_status,
        "agente_runs":        _agents_router.agente_runs,
    },
    log=log,
)
app.include_router(_gateway_router.router)


# ── MCP (Model Context Protocol) ─────────────────────────────────────────────
# Expõe os endpoints REST da Lyra como ferramentas MCP, acessíveis por
# Claude Code, Cursor, Continue e qualquer cliente MCP.
# Servidor disponível em: http://127.0.0.1:8000/mcp
# Endpoints excluídos: /chat (streaming SSE), /dashboard (HTML), /upload (multipart),
# /historico DELETE (destrutivo), /tts/mudo (controle interno).
try:
    import warnings as _warnings
    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore")
        from fastapi_mcp import FastApiMCP
    _mcp = FastApiMCP(
        app,
        name="Lyra",
        description=(
            "IA pessoal do Projeto Lyra — acesso à memória híbrida (BM25 + BGE-M3 + reranker), "
            "grafo de conhecimento SurrealDB, sub-agentes paralelos (enxames), "
            "métricas de GPU/sistema e histórico de conversa."
        ),
        exclude_operations=[
            # FastAPI gera operationId como {fn}_{path}_{method}
            "chat_endpoint_chat_post",       # streaming SSE
            "raiz__get",                     # ping simples
            "dashboard_dashboard_get",       # HTML standalone
            "upload_arquivo_upload_post",    # multipart/form-data
            "definir_tts_mudo_tts_mudo_post", # controle interno
            "historico_limpar_historico_delete", # DELETE destrutivo
            "sessao_deletar_sessoes__sessao_id__delete", # DELETE destrutivo
            "exportar_conversa_exportar_get",   # markdown raw
        ],
    )
    # mount_http() é o método atual (mount() deprecated em 0.4.0)
    if hasattr(_mcp, "mount_http"):
        _mcp.mount_http()
    else:
        _mcp.mount()
    log("[OK] MCP server montado em /mcp")
except Exception as _e:
    log(f"[ALERTA] MCP: {_e}")


def _init():
    """Ignição: anexa Qdrant + BM25 no RAGEngine e valida o embed_service."""
    global cerebro_ativo
    log("\n=== IGNIÇÃO ===")
    try:
        from qdrant_client import QdrantClient
        _rag.qdrant_client = QdrantClient("127.0.0.1", port=cfg.QDRANT_PORT, timeout=30)
        cols  = [c.name for c in _rag.qdrant_client.get_collections().collections]
        total = _rag.qdrant_client.count(_COLECAO).count if _COLECAO in cols else 0
        log(f"[OK] Qdrant: {total:,} vetores em {_COLECAO}.")
        cerebro_ativo = True
    except Exception as e:
        log(f"[ALERTA] Qdrant: {e}")

    try:
        _rag.bm25_index = bm25_index.carregar_indice(log=log)
    except Exception as e:
        log(f"[ALERTA] BM25: {e}")
        _rag.bm25_index = None

    # Embedding agora é externo (embed_service :8001, BGE-M3). Não carrega MiniLM.
    vetor_teste = _embed("teste de inicialização")
    if vetor_teste and len(vetor_teste) == 1024:
        log(f"[OK] embed_service :8001 respondendo (BGE-M3 1024d).")
    else:
        log("[ALERTA] embed_service :8001 não respondeu — RAG denso ficará indisponível "
            "até o serviço subir (chat segue funcionando, sem contexto de memória).")

    log("=== PRONTO — uvicorn :8000 ===\n")


if __name__ == "__main__":
    _init()
    uvicorn.run(app, host="127.0.0.1", port=cfg.CEREBRO_PORT, log_level="warning")
