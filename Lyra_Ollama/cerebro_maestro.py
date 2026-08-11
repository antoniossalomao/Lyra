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
from fastapi import FastAPI, UploadFile, File, WebSocket
from fastapi.responses import StreamingResponse
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


@app.post("/chat")
async def chat_endpoint(msg: MensagemUsuario):
    _t0_req = time.monotonic()

    # Espera o startup terminar de restaurar sessão/briefing — sem isso, um
    # /chat nos primeiros segundos corria com sessão None e histórico vazio.
    await _session.wait_ready()

    _, tamanho_hist = await _session.append_user(msg.texto)

    # Registra a fala do usuário com classificação de intenção (Innovation 1)
    asyncio.create_task(registrar_evento(fonte="chat", ator="Antônio", texto=msg.texto,
                                         intencao=_classificar_intencao("Antônio", msg.texto)))

    if tamanho_hist > cfg.MAX_HISTORY_MSGS:
        asyncio.create_task(_session.compress_if_needed())

    contexto_str = ""
    # Sem acento — matching de keyword não pode depender do usuário digitar
    # certinho ("saude" vs "saúde"), já causou a Lyra inventar CPU/RAM em vez
    # de chamar a ferramenta porque "saude" sem acento não casava com "saúde".
    msg_lower = _sem_acento(msg.texto.lower())

    # Detecta se é pergunta sobre memória/histórico pessoal (controla top_k maior)
    keywords_memoria = [_sem_acento(k) for k in ["lembra", "quando", "qual foi", "primeira pergunta",
                        "quantas vezes", "me perguntei", "você já", "há quanto tempo",
                        "ontem", "semana passada"]]
    eh_pergunta_memoria = any(kw in msg_lower for kw in keywords_memoria)

    # Detecta pergunta factual genérica (não só memória pessoal) — a base wiki_
    # conhecimento foi ingerida exatamente pra isso: a Lyra deve CONSULTAR a
    # memória em vez de confiar só no conhecimento interno do modelo pequeno
    # (que erra/recusa fatos triviais) ou inventar. Só pula RAG em conversa
    # puramente casual (sem "?" nem palavra interrogativa) — mas saudações tipo
    # "tudo bem?"/"como vai?" têm "?" sem ser pergunta de conhecimento, então
    # essas ficam de fora mesmo com "?" pra não pagar o custo do RAG à toa.
    saudacoes_casuais = [_sem_acento(s) for s in ["tudo bem", "como vai", "como você está",
                         "e aí", "oi,", "olá,", "bom dia", "boa tarde",
                         "boa noite", "tudo certo", "tudo joia", "suave"]]
    eh_saudacao_casual = any(s in msg_lower for s in saudacoes_casuais) and len(msg.texto) < 40
    palavras_interrogativas = [_sem_acento(p) for p in ["qual", "quem", "quando", "onde", "como",
                               "por que", "porque", "quanto", "quantos", "quantas", "o que",
                               "que é", "quais"]]
    eh_pergunta_factual = (not eh_saudacao_casual) and (
        "?" in msg.texto or any(p in msg_lower for p in palavras_interrogativas))

    # A busca híbrida (BM25 + vetorial sobre ~2,2M registros) custa 5-10s sozinha
    # — inaceitável rodar em toda mensagem casual ("oi", "tudo bem?"). Mas pular
    # ela inteira fazia a Lyra recusar/errar fatos triviais que estão na wiki
    # ingerida — então só pula mesmo em conversa casual, não em perguntas.
    ids_rag: list[str] = []  # IDs Qdrant usados no RAG desta mensagem (Innovation 5)
    if cerebro_ativo and _rag.active and (eh_pergunta_memoria or eh_pergunta_factual):
        try:
            # to_thread: _rag.search é síncrona (httpx.post bloqueante em embed/
            # rerank + BM25 em CPU) — sem isso, travava o event loop inteiro do
            # uvicorn por 5-10s, inclusive /health e o WS de voz.
            # top_k ajustado dinamicamente pela carga cognitiva (Innovation 4)
            resultados = await asyncio.to_thread(_rag.search, msg.texto, top_k=_top_k_ajustado(5))
            ids_rag = [str(r.get("id", "")) for r in resultados if r.get("id")]

            # Atualiza last_accessed_at e retrieval_count nos vetores recuperados
            asyncio.create_task(_rag.update_access(resultados))

            # Filtro de episódio + formatação + suplemento de grafo vivem em
            # RAGEngine.build_context — ver docstring lá pro racional.
            contexto_str = await _rag.build_context(msg.texto, resultados, eh_pergunta_memoria)
        except Exception as e:
            log(f"[FALHA RAG] {e}")

    # Snapshot sanitizado (role/content só) — metadados extras fazem o Groq
    # rejeitar a request com 400 "unsupported property".
    mensagens = await _session.sanitized_messages()
    
    # Prepara o contexto de realidade (Data/Hora) para evitar alucinações temporais
    agora = datetime.datetime.now()
    dia_semana = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"][agora.weekday()]
    data_hora_str = f"[SISTEMA] Hoje é {dia_semana}, {agora.strftime('%d/%m/%Y as %H:%M')}."

    # Exceção consciente à Diretiva Nº 2 (decidida com Antônio em 24/06/2026):
    # se o usuário pedir explicitamente pra usar o Claude, a aprovação já está
    # dada nessa mesma mensagem — não precisa o modelo perguntar de novo.
    _KEYWORDS_CLOUD_APROVADO = ["faça isso com o claude", "faz isso com o claude",
                                "usa o claude", "use o claude", "chama o claude",
                                "chame o claude", "pede ajuda pro claude",
                                "peça ajuda pro claude", "manda pro claude",
                                "envia pro claude", "pede pro claude"]
    eh_aprovacao_cloud_explicita = any(_sem_acento(kw) in msg_lower for kw in _KEYWORDS_CLOUD_APROVADO)

    # Câmara de Eco Heurística (02/07/2026) — confirmação explícita de uma ação
    # de alto risco bloqueada por _executar_tool_segura(). Frases pareadas com
    # verbo de ação (não "sim"/"confirmo" soltos) — reduz colisão com confirmações
    # de outro assunto (ex: confirmar um compromisso de calendário). Duas travas
    # combinadas: só aprova a ação EXATA que está pendente (_ultima_acao_bloqueada,
    # nunca uma diferente) e só no turno IMEDIATAMENTE seguinte ao bloqueio
    # (índice de historico_recente igual ao registrado no momento do bloqueio) —
    # a janela de 10min sozinha não bastaria pra evitar aprovação fora de contexto.
    _KEYWORDS_RISCO_APROVADO = [_sem_acento(k) for k in [
        "confirmo, pode executar", "confirmo, executa", "sim, executa mesmo assim",
        "sim, pode executar", "autorizo, pode fazer", "autorizo a executar",
        "pode continuar mesmo assim", "manda ver, confirmado", "pode fazer mesmo assim",
        "executa mesmo assim", "confirmado, pode rodar"]]
    eh_aprovacao_risco_explicita = False
    aviso_risco_str = ""
    if _ultima_acao_bloqueada is not None:
        dentro_da_janela = (time.time() - _ultima_acao_bloqueada["ts"]) < 600  # 10min
        eh_proximo_turno = _session.turn_counter == _ultima_acao_bloqueada["turno_bloqueio"] + 1
        if dentro_da_janela and eh_proximo_turno and any(kw in msg_lower for kw in _KEYWORDS_RISCO_APROVADO):
            eh_aprovacao_risco_explicita = True
            _h = _ultima_acao_bloqueada["hash"]
            with _lock_risco:
                _confirmacoes_risco[_h] = time.time()
            aviso_risco_str = (f"\n\n[SISTEMA] O usuário confirmou explicitamente a ação de risco pendente "
                               f"({_ultima_acao_bloqueada['nome']}: {_ultima_acao_bloqueada['motivo']}). "
                               f"Chame a MESMA ferramenta de novo com os MESMOS parâmetros de antes.")

    if len(mensagens) > 0:
        # Bug real corrigido 02/07/2026: usar mensagens[-1]["content"] assume
        # que a última entrada de historico_recente É a mensagem desta
        # requisição — mas entre o append do usuário (linha ~1376) e aqui,
        # o código faz vários await (RAG híbrido, grafo SurrealDB), cedendo
        # o event loop. Se uma segunda requisição /chat concorrente também
        # der append nesse intervalo, mensagens[-1] pode ser a pergunta de
        # OUTRA requisição, não a desta — a resposta sai contaminada/trocada
        # entre sessões concorrentes. msg.texto é local a esta requisição,
        # imune a mutação concorrente — sempre a fonte correta.
        ultima_msg = msg.texto
        aviso_cloud_str = ""
        if eh_aprovacao_cloud_explicita:
            aviso_cloud_str = ("\n\n[SISTEMA] O usuário autorizou explicitamente o uso do Claude "
                               "(nuvem) nesta mensagem. Chame consultar_especialista com "
                               "nivel='cloud' e aprovado=True diretamente, sem perguntar de novo.")
        aviso_cloud_str += aviso_risco_str
        if contexto_str:
            # A instrução rígida de "diga que não tem registro" só faz sentido
            # quando a pergunta É sobre memória — caso contrário, qualquer match
            # fraco/irrelevante do RAG fazia a Lyra recusar conversa casual
            # ("oi, tudo bem?") tratando-a como pergunta de memória sem resposta.
            if eh_pergunta_memoria:
                aviso_bloco = f"\n\n[AVISO CRÍTICO]\n- Use timestamps das memórias acima (NUNCA invente datas)\n- Se não encontrar, diga: 'Não tenho registro disso'{aviso_cloud_str}"
            else:
                aviso_bloco = aviso_cloud_str
            mensagens[-1] = {
                "role": "user",
                "content": f"{data_hora_str}\n\n[MEMÓRIAS DO CÉREBRO]\n{contexto_str}{aviso_bloco}\n\nUsuário: {ultima_msg}"
            }
        else:
            mensagens[-1] = {
                "role": "user",
                "content": f"{data_hora_str}{aviso_cloud_str}\n\nUsuário: {ultima_msg}"
            }

    # Roteador de Intenção — ativa ferramentas só com keyword no início de palavra
    # (regex \b, compilada em _TOOL_KEYWORDS_RE no módulo). Evita falsos positivos.
    precisa_tools = bool(_TOOL_KEYWORDS_RE.search(msg_lower))
    ferramentas = lyra_tools.TOOLS_SCHEMA if precisa_tools else None
    if eh_aprovacao_cloud_explicita:
        precisa_tools = True
        ferramentas = lyra_tools.TOOLS_SCHEMA
    if eh_aprovacao_risco_explicita:
        precisa_tools = True
        ferramentas = lyra_tools.TOOLS_SCHEMA

    # Enxame de Especialistas (MoE roteado) — proposta formalizada em
    # LYRA_TECNICO.md 10.9, implementada em 02/07/2026. Antes disso a ordem
    # da cascata vinha de um if/elif solto (eh_pergunta_codigo). Generaliza
    # pra uma lista declarativa: cada especialista tem categoria + trigger +
    # ordem de andares. Adicionar um especialista novo = uma entrada na lista,
    # não editar lógica de roteamento espalhada. Comportamento idêntico ao
    # anterior pros 2 especialistas existentes (código, geral) — só reorganiza.
    especialista = _rotear_especialista(msg_lower, msg.texto)

    async def stream():
        global _ultima_latencia_ms
        resposta_completa = ""
        tier_usado = None

        # Speculative Decoding (Fase 3) — dispara o draft (qwen3:0.6b) já aqui,
        # em paralelo com a cascata principal, pra não somar latência. Só faz
        # sentido comparar quando a resposta é texto puro: se ferramentas forem
        # chamadas, o andar principal vê dados que o draft nunca vê (clima,
        # hora, resultado de busca) — divergência ali seria falso-positivo.
        draft_task = asyncio.create_task(_rodar_draft(list(mensagens))) if not precisa_tools else None

        _MAPA_TIERS = {"groq": ("Groq", _stream_groq), "gemini": ("Gemini", _stream_gemini),
                       "claude": ("Claude", _stream_claude_cli), "local": ("Local", _stream_local)}

        if msg.modelo in _MAPA_TIERS:
            # Seletor manual do painel — só esse andar, sem fallback (o
            # usuário escolheu de propósito, melhor falhar visivelmente do
            # que cair pra outro modelo escondido).
            andares = [_MAPA_TIERS[msg.modelo]]
        else:
            andares = [_MAPA_TIERS[nome] for nome in especialista["andares"]]

        for nome_tier, gerador_fn in andares:
            try:
                gerador = gerador_fn(list(mensagens), ferramentas)
                gerador_pronto = await _primeiro_chunk_ou_falha(gerador)
            except StopAsyncIteration:
                log(f"[CASCATA] {nome_tier} retornou vazio — tentando próximo andar.")
                _registrar_tier(nome_tier, falhou=True)
                continue
            except Exception as e:
                log(f"[CASCATA] {nome_tier} falhou: {e}")
                _registrar_tier(nome_tier, falhou=True)
                continue

            tier_usado = nome_tier
            # Manda a fonte como campo estruturado ("tier"), não como texto
            # no meio da resposta — o frontend mostra isso discreto no painel
            # lateral em vez de no balão de chat (pedido do usuário).
            yield f"data: {json.dumps({'tier': nome_tier})}\n\n"
            if nome_tier == "Local":
                log("[CASCATA] Todas as APIs de nuvem falharam — usando qwen3:8b local.")

            try:
                async for chunk in gerador_pronto:
                    yield f"data: {json.dumps({'text': chunk})}\n\n"
                    resposta_completa += chunk
            except Exception as e:
                log(f"[CASCATA] {nome_tier} falhou no meio do stream: {e}")
                yield f"data: {json.dumps({'text': chr(10) + '_(conexao interrompida)_'})}\n\n"
            break  # comprometido com esse andar (sucesso ou falha no meio) -- nao tenta outro

        if tier_usado is None:
            log("[CASCATA] Todos os 4 andares falharam.")
            if draft_task is not None:
                draft_task.cancel()
            yield f"data: {json.dumps({'text': 'Todas as fontes de resposta falharam (Groq, Gemini, Claude e o modelo local). Tente novamente em alguns segundos.'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        # Speculative Decoding: compara a resposta final com o draft (se deu
        # tempo de terminar). Divergência alta = log de alerta, não bloqueia
        # nem altera a resposta — é só um sinal de possível alucinação.
        divergencia_draft = None
        if draft_task is not None and resposta_completa:
            try:
                draft_texto = await asyncio.wait_for(draft_task, timeout=8)
            except Exception:
                draft_texto = None
            if draft_texto:
                try:
                    vetor_final, vetor_draft = await asyncio.gather(
                        asyncio.to_thread(_embed, resposta_completa.strip()),
                        asyncio.to_thread(_embed, draft_texto),
                    )
                    if vetor_final and vetor_draft:
                        divergencia_draft = round(1 - _cosine_sim(vetor_final, vetor_draft), 4)
                        if divergencia_draft > LIMIAR_DIVERGENCIA_ALUCINACAO:
                            log(f"[SPEC-DECODE] divergência alta ({divergencia_draft}) entre {tier_usado} "
                                f"e draft qwen3:0.6b — possível alucinação. Draft: {draft_texto[:150]!r}")
                except Exception as e:
                    log(f"[SPEC-DECODE] falha ao comparar draft: {e}")
        elif draft_task is not None:
            draft_task.cancel()

        if resposta_completa:
            resposta_limpa = resposta_completa.strip()
            await _session.append_assistant(resposta_limpa,
                                            fontes_rag=ids_rag or None,  # Innovation 5
                                            divergencia_draft=divergencia_draft)
            asyncio.create_task(registrar_evento(fonte="chat", ator="Lyra", texto=resposta_limpa,
                                                  fontes_rag=ids_rag or None,
                                                  divergencia_draft=divergencia_draft))

            # Filtra blocos de codigo e fala em voz alta
            try:
                texto_falado = re.sub(r'```.*?```', '', resposta_limpa, flags=re.DOTALL)
                texto_falado = re.sub(r'`.*?`', '', texto_falado)
                texto_falado = texto_falado.replace('*', '').replace('#', '')
                if texto_falado.strip() and 'audio_manager' in globals() and not _tts_mudo:
                    asyncio.create_task(audio_manager.falar(texto_falado.strip()))
            except Exception as e:
                log(f"[ERRO TTS] {e}")

        _ultima_latencia_ms = round((time.monotonic() - _t0_req) * 1000)
        # Telemetria: registra sucesso do andar que respondeu + latência
        if tier_usado:
            _telemetria["total_chats"] += 1
            _registrar_tier(tier_usado, latencia_ms=_ultima_latencia_ms)
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/")
def raiz():
    """Endpoint raiz — usado pelo frontend pra checar se o cérebro responde."""
    return {"servico": "Lyra cerebro_maestro", "ativo": cerebro_ativo, "versao": "2.1"}


@app.get("/dashboard")
def dashboard():
    """Dashboard de monitoramento standalone — abre em qualquer navegador
    (http://localhost:8000/dashboard). Polla /health, /stats e /metrics."""
    from fastapi.responses import HTMLResponse
    caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except Exception as e:
        return HTMLResponse(f"<h1>Dashboard indisponível</h1><p>{e}</p>", status_code=500)


@app.get("/status")
def status():
    return {"cerebro_ativo": cerebro_ativo,
            "qdrant": _rag.active,
            "embedder": _embed_service_ok(),  # embed_service :8001 (BGE-M3)
            "tts_mudo": _tts_mudo,
            "carga_cognitiva": _carga_cognitiva}  # Innovation 4


@app.get("/stats")
def stats():
    """Telemetria da cascata: distribuição de uso, latência média e taxa de falha por andar."""
    tiers_out = {}
    for nome, t in _telemetria["tiers"].items():
        usos = t.get("usos", 0)
        falhas = t.get("falhas", 0)
        lat_total = t.get("latencia_total_ms", 0)
        total_tentativas = usos + falhas
        tiers_out[nome] = {
            "usos": usos,
            "falhas": falhas,
            "latencia_media_ms": round(lat_total / usos) if usos else None,
            "taxa_sucesso": round(usos / total_tentativas * 100, 1) if total_tentativas else None,
        }
    total = _telemetria.get("total_chats", 0)
    return {
        "total_chats": total,
        "iniciado_em": _telemetria.get("iniciado_em"),
        "tiers": tiers_out,
        "distribuicao_pct": {
            nome: round(t["usos"] / total * 100, 1) if total else 0
            for nome, t in _telemetria["tiers"].items()
        },
    }


@app.get("/stats/historico")
def stats_historico(limite: int = 200):
    """Série temporal de telemetria — snapshots tirados a cada ~5min pelo
    loop_proativo. Usado pelo gráfico do painel lateral (distinto do /stats,
    que só mostra o acumulado desde o último restart)."""
    return {"snapshots": _ler_telemetria_historico(limite)}


@app.get("/health")
async def health():
    """Health check completo com latência real de todos os serviços."""
    import time as _time

    async def _ping(url: str, timeout: float = 3.0) -> tuple[bool, float | None]:
        t0 = _time.monotonic()
        try:
            await _http_health_client.get(url, timeout=timeout)
            return True, round((_time.monotonic() - t0) * 1000, 1)
        except Exception:
            return False, None

    async def _ping_post(url: str, data: str, headers: dict, auth, timeout=3.0):
        t0 = _time.monotonic()
        try:
            await _http_health_client.post(url, data=data, headers=headers, auth=auth, timeout=timeout)
            return True, round((_time.monotonic() - t0) * 1000, 1)
        except Exception:
            return False, None

    qdrant_ok, qdrant_ms   = await _ping(f"{cfg.QDRANT_URL}/healthz")
    surreal_ok, surreal_ms = await _ping_post(
        cfg.SURREAL_URL, "RETURN 1", cfg.SURREAL_HEADERS, cfg.SURREAL_AUTH)
    ollama_ok, ollama_ms   = await _ping(f"{cfg.OLLAMA_URL}/api/tags")

    # VRAM via nvidia-smi
    vram_info = {}
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        saida, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
        partes = saida.decode().strip().split(",")
        if len(partes) == 3:
            vram_info = {
                "usada_mb":  int(partes[0].strip()),
                "total_mb":  int(partes[1].strip()),
                "gpu_pct":   int(partes[2].strip()),
            }
    except Exception:
        pass

    # Vetores no Qdrant (coleção ativa em produção)
    qdrant_vetores = {}
    if _rag.active:
        try:
            qdrant_vetores[_COLECAO] = _rag.qdrant_client.count(_COLECAO).count
        except Exception:
            qdrant_vetores[_COLECAO] = None

    return {
        "cerebro":  {"ok": cerebro_ativo, "embedder": _embed_service_ok(), "bm25": _rag.bm25_index is not None},
        "qdrant":   {"ok": qdrant_ok,   "latencia_ms": qdrant_ms,   "vetores": qdrant_vetores},
        "surreal":  {"ok": surreal_ok,  "latencia_ms": surreal_ms},
        "ollama":   {"ok": ollama_ok,   "latencia_ms": ollama_ms},
        "vram":     vram_info,
        "latencia_ultimo_chat_ms": _ultima_latencia_ms,
    }


@app.post("/tts/mudo")
def definir_tts_mudo(payload: dict):
    """Liga/desliga a resposta por voz (audio_manager.falar) globalmente —
    botão de mute no frontend. Estado vive em memória, não persiste reinício
    do cérebro (o frontend reaplica via localStorage assim que reconecta)."""
    global _tts_mudo
    _tts_mudo = bool(payload.get("mudo", False))
    return {"ok": True, "tts_mudo": _tts_mudo}


@app.post("/tts/falar")
async def tts_falar(payload: dict):
    """Dispara TTS pra um texto arbitrário — usado pelo frontend pra reler uma
    resposta ou falar uma notificação. Respeita o mute global."""
    texto = (payload.get("texto") or "").strip()
    if not texto:
        return {"ok": False, "erro": "texto vazio"}
    if _tts_mudo:
        return {"ok": False, "erro": "TTS mutado"}
    if "audio_manager" not in globals():
        return {"ok": False, "erro": "audio_manager indisponível"}
    asyncio.create_task(audio_manager.falar(texto[:500]))
    return {"ok": True}


@app.get("/exportar")
async def exportar_conversa():
    """Exporta o histórico em memória como markdown — pra salvar/compartilhar a sessão."""
    hist = await _session.snapshot()
    linhas = [f"# Conversa com a Lyra — {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}", ""]
    for m in hist:
        autor = "**Antônio**" if m["role"] == "user" else "**Lyra**"
        linhas.append(f"{autor}: {m['content']}")
        linhas.append("")
    return {"markdown": "\n".join(linhas), "total_msgs": len(hist)}


@app.post("/upload")
async def upload_arquivo(file: UploadFile = File(...)):
    """Recebe imagem/áudio colado ou anexado no chat do frontend. Salva em
    Sons/cache/uploads e devolve o path — o frontend então manda esse path
    numa mensagem de chat normal, e o modelo decide chamar analisar_imagem
    ou transcrever_audio dependendo do tipo de arquivo."""
    nome_seguro = re.sub(r"[^a-zA-Z0-9_.-]", "_", file.filename or "arquivo")
    destino = os.path.join(_PASTA_UPLOADS, f"{int(time.time())}_{nome_seguro}")
    conteudo = await file.read()
    with open(destino, "wb") as f:
        f.write(conteudo)
    return {"ok": True, "path": destino, "nome": nome_seguro, "bytes": len(conteudo)}


_gpu_cache: dict = {}
_gpu_cache_ts: float = 0.0

@app.get("/metrics")
async def metrics():
    global _gpu_cache, _gpu_cache_ts
    dados = {
        "latencia_ms": _ultima_latencia_ms,
        "cpu_pct":     psutil.cpu_percent(interval=None),
        "ram_pct":     psutil.virtual_memory().percent,
        "gpu_pct":     None,
        "vram_pct":    None,
    }
    # GPU via nvidia-smi com cache de 4s — evita 1 subprocesso por poll do frontend
    agora_t = time.monotonic()
    if agora_t - _gpu_cache_ts > 4:
        try:
            proc = await asyncio.create_subprocess_exec(
                "nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            saida, _ = await asyncio.wait_for(proc.communicate(), timeout=2)
            parts = saida.decode().strip().split(",")
            if len(parts) == 3:
                _gpu_cache = {
                    "gpu_pct":  int(parts[0].strip()),
                    "vram_pct": round(int(parts[1].strip()) / int(parts[2].strip()) * 100),
                }
                _gpu_cache_ts = agora_t
        except Exception:
            pass
    dados.update(_gpu_cache)
    return dados


import lyra_agentes as _agentes


class EnxameRequest(BaseModel):
    objetivo:     str
    subtarefas:   list[str]
    max_paralelo: int = 3


@app.post("/enxame")
async def enxame_criar(req: EnxameRequest):
    return await _agentes.criar_enxame(req.objetivo, req.subtarefas, req.max_paralelo)


@app.get("/enxames")
async def enxames_listar(limite: int = 20):
    return await _agentes.listar_enxames(limite)


@app.get("/enxame/{enxame_id}")
async def enxame_status(enxame_id: str):
    return await _agentes.status_enxame(enxame_id)


@app.post("/enxame/{enxame_id}/consolidar")
async def enxame_consolidar(enxame_id: str):
    resultado = await _agentes.consolidar_enxame(enxame_id)
    # Notifica proativamente quando consolidação termina
    if "resumo" in resultado:
        lyra_tools.notificar_usuario(
            titulo="Enxame consolidado",
            mensagem=resultado["resumo"][:200],
            urgencia="normal",
        )
    return resultado


import lyra_agent as _agent_module


class AgenteRequest(BaseModel):
    objetivo:      str
    max_iteracoes: int = 10


@app.post("/agente")
async def agente_executar(req: AgenteRequest):
    """Loop ReAct autônomo (lyra_agent.py) — recebe objetivo, itera com ferramentas
    e retorna resultado final. Não usa streaming; aguarda conclusão antes de responder."""
    return await _agent_module.executar_agente_async(req.objetivo, req.max_iteracoes)


@app.get("/agente/runs")
async def agente_runs(limite: int = 20):
    """Lista execuções recentes do agente autônomo (tabela agente_run no SurrealDB)."""
    runs = await surreal.query_result(
        f"SELECT id, objetivo, sucesso, iteracoes, criado_em FROM agente_run "
        f"ORDER BY criado_em DESC LIMIT {min(limite, 100)};")
    return {"total": len(runs), "runs": runs}


@app.get("/historico")
async def historico_get(sessao: str | None = None):
    """Sem parâmetro: histórico em memória (comportamento original).
    Com ?sessao=<id>: mensagens daquela sessão direto do SurrealDB
    ('legado' = eventos gravados antes da migração de sessões)."""
    if not sessao:
        hist = await _session.snapshot()
        return {"total": len(hist), "mensagens": hist}
    cond = "sessao_id IS NONE" if sessao == "legado" else f"sessao_id = {json.dumps(sessao)}"
    try:
        dados = await _sql_surreal(
            f"SELECT ator, texto, timestamp FROM evento WHERE {cond} "
            "ORDER BY timestamp ASC LIMIT 300")
        eventos = _surreal_result(dados)
    except Exception as e:
        return {"erro": f"Falha ao ler sessão: {e}", "total": 0, "mensagens": []}
    mensagens = [
        {"role": "assistant" if ev.get("ator", "").lower() == "lyra" else "user",
         "content": ev.get("texto", ""), "timestamp": ev.get("timestamp", "")}
        for ev in eventos
    ]
    return {"total": len(mensagens), "mensagens": mensagens, "sessao": sessao}


class SessaoAtivar(BaseModel):
    sessao_id: str


@app.get("/sessoes")
async def sessoes_listar():
    """Lista as sessões de conversa pra sidebar do frontend (mais recentes
    primeiro). Inclui uma entrada sintética 'legado' se existirem eventos
    gravados antes da migração de sessões."""
    itens = []
    try:
        dados = await _sql_surreal("SELECT id, criada, titulo FROM sessao ORDER BY criada DESC LIMIT 40")
        for r in _surreal_result(dados):
            sid = _sessao_id_limpo(r.get("id", ""))
            itens.append({
                "sessao_id": sid,
                "titulo": r.get("titulo") or "conversa sem título",
                "criada": r.get("criada", ""),
                "ativa": sid == _session.session_id,
            })
    except Exception as e:
        return {"erro": f"Falha ao listar sessões: {e}", "sessoes": []}
    try:
        dados = await _sql_surreal("SELECT count() FROM evento WHERE sessao_id IS NONE GROUP ALL")
        legado = _surreal_result(dados)
        if legado and legado[0].get("count", 0) > 0:
            itens.append({"sessao_id": "legado", "titulo": "conversas antigas (pré-sessões)",
                          "criada": "", "ativa": False, "somente_leitura": True})
    except Exception:
        pass  # contagem de legado é cosmética — a lista principal já foi montada
    return {"total": len(itens), "sessoes": itens, "ativa": _session.session_id}


@app.post("/sessoes")
async def sessao_nova():
    """Cria uma nova sessão de conversa e a torna ativa. O histórico em
    memória é zerado — a Lyra começa a conversa limpa (SurrealDB/Qdrant
    seguem intactos, memória de longo prazo continua via RAG)."""
    return await _session.new_session()


@app.post("/sessoes/ativar")
async def sessao_ativar(req: SessaoAtivar):
    """Torna outra sessão a ativa e recarrega o histórico com as últimas
    mensagens dela ('legado' é somente leitura — use GET /historico)."""
    return await _session.activate_session(req.sessao_id)


class SessaoRenomear(BaseModel):
    titulo: str


@app.patch("/sessoes/{sessao_id}")
async def sessao_renomear(sessao_id: str, req: SessaoRenomear):
    return await _session.rename_session(sessao_id, req.titulo)


@app.delete("/sessoes/{sessao_id}")
async def sessao_deletar(sessao_id: str):
    return await _session.delete_session(sessao_id)


@app.delete("/historico")
async def historico_limpar():
    """Limpa o histórico em memória (não apaga SurrealDB/Qdrant)."""
    await _session.clear_history()
    log("[HIST] Histórico em memória limpo via DELETE /historico.")
    return {"ok": True, "mensagem": "Histórico em memória limpo."}


@app.get("/grafo")
async def grafo_buscar(q: str, limite: int = 5):
    """Traversal de grafo SurrealDB: retorna eventos ligados aos tópicos da query."""
    if not q.strip():
        return {"erro": "Parâmetro 'q' obrigatório."}
    eventos = await buscar_grafo_surreal(q, limite=min(limite, 20))
    return {
        "query": q,
        "keywords": _extrair_keywords(q, n=3),
        "total": len(eventos),
        "eventos": [
            {
                "ator":      ev.get("ator", "?"),
                "texto":     ev.get("texto", "")[:400],
                "timestamp": ev.get("timestamp", ""),
            }
            for ev in eventos
        ],
    }


@app.get("/grafo/completo")
async def grafo_completo(limite: int = 300):
    """Retorna o grafo completo de memória para visualização 3D.
    Formato {nodes, links} compatível com 3d-force-graph."""
    try:
        async def _sql(q):
            result = await surreal.query_result(q)
            return result if isinstance(result, list) else []

        eventos  = await _sql(f"SELECT id, texto, ator, timestamp FROM evento ORDER BY timestamp DESC LIMIT {limite};")
        sobre    = await _sql(f"SELECT in, out FROM sobre LIMIT {limite * 4};")
        precedeu = await _sql(f"SELECT in, out FROM precedeu LIMIT {limite};")

        nodes, links = [], []
        ids_vistos: set[str] = set()

        # Eventos
        for ev in eventos:
            eid = str(ev.get("id", ""))
            if eid and eid not in ids_vistos:
                nodes.append({
                    "id":    eid,
                    "tipo":  "evento",
                    "label": (ev.get("texto") or eid)[:90],
                    "ator":  ev.get("ator", ""),
                    "ts":    ev.get("timestamp", ""),
                })
                ids_vistos.add(eid)

        # Tópicos extraídos das relações "sobre" (não há tabela topico separada)
        for a in sobre:
            src = str(a.get("in", ""))
            dst = str(a.get("out", ""))
            if not src or not dst:
                continue
            links.append({"source": src, "target": dst, "rel": "sobre"})
            if dst not in ids_vistos and dst.startswith("topico:"):
                label = dst.split(":", 1)[-1]
                nodes.append({"id": dst, "tipo": "topico", "label": label})
                ids_vistos.add(dst)

        for a in precedeu:
            src, dst = str(a.get("in", "")), str(a.get("out", ""))
            if src and dst:
                links.append({"source": src, "target": dst, "rel": "precedeu"})

        # "sobre"/"precedeu" podem referenciar eventos fora da janela dos
        # `limite` mais recentes (a query de evento tem LIMIT, a de link não
        # é sincronizada com ela) — link órfão apontando pra um nó que não
        # está em `nodes` crasha o 3d-force-graph no frontend (erro não
        # tratado que derruba o grafo inteiro). Descarta aqui, na origem.
        links = [l for l in links if l["source"] in ids_vistos and l["target"] in ids_vistos]

        return {"nodes": nodes, "links": links,
                "total_nodes": len(nodes), "total_links": len(links)}

    except Exception as e:
        log(f"[GRAFO/COMPLETO] Erro: {e}")
        return {"nodes": [], "links": [], "erro": str(e)}


@app.get("/resumo_sessao")
async def resumo_sessao():
    """Retorna o briefing da sessão atual + histórico recente em memória."""
    hist = await _session.snapshot()
    return {
        "briefing": _session.briefing.strip(),
        "historico": [
            {"role": m["role"], "preview": m["content"][:200]}
            for m in hist
        ],
        "total_msgs": len(hist),
    }


@app.get("/buscar")
def buscar(q: str, top_k: int = 5, categoria: str = ""):
    if not cerebro_ativo:
        return {"erro": "Cérebro não inicializado"}
    try:
        resultados = buscar_hibrido(q, top_k=top_k, categoria=categoria)
        return {"query": q, "categoria_filtro": categoria or "todas", "resultados": [
            {"id":            str(r.get("id", "")),
             "score_final":   round(r.get("score_final", 0), 4),
             "rerank_score":  round(r["rerank_score"], 4) if r.get("rerank_score") is not None else None,
             "rrf_score":     r["rrf_score"],
             "dense_score":   round(r["dense_score"], 4) if r["dense_score"] is not None else None,
             "bm25_score":    round(r["bm25_score"], 4) if r["bm25_score"] is not None else None,
             "freshness_factor": r.get("freshness_factor"),  # Innovation 2
             "titulo":        r["payload"].get("titulo", ""),
             "categoria":     r["payload"].get("categoria", ""),
             "trecho":        r["payload"].get("texto", "")[:300]}
            for r in resultados]}
    except Exception as e:
        return {"erro": str(e)}


@app.get("/memoria/categorias")
async def memoria_categorias():
    """Composição da base de conhecimento por categoria, via facet do Qdrant
    (distinct counts exatos e eficientes). Mostra o que a Lyra 'sabe'."""
    if not cerebro_ativo or not _rag.active:
        return {"erro": "Cérebro não inicializado"}
    total_colecao = 0
    try:
        total_colecao = _rag.qdrant_client.count(_COLECAO).count
    except Exception:
        pass
    por_categoria = {}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{cfg.QDRANT_URL}/collections/{_COLECAO}/facet",
                json={"key": "categoria", "limit": 50, "exact": False},
                timeout=30,
            )
            resp.raise_for_status()
            hits = resp.json().get("result", {}).get("hits", [])
            por_categoria = {h["value"]: h["count"] for h in hits}
    except Exception as e:
        return {"total_colecao": total_colecao, "erro": f"facet falhou: {e}"}
    return {"total_colecao": total_colecao, "categorias_distintas": len(por_categoria),
            "por_categoria": por_categoria}


class ShadowRequest(BaseModel):
    fases: str = "nrem,rem,deep"  # fases separadas por vírgula


@app.post("/shadow_thoughts")
async def shadow_thoughts_disparar(req: ShadowRequest = ShadowRequest()):
    """Dispara o ciclo de Shadow Thoughts em background (NREM/REM/DEEP).
    Retorna imediatamente — progresso aparece no maestro.log."""
    import lyra_shadow_thoughts as _st
    fases = [f.strip().lower() for f in req.fases.split(",") if f.strip() in {"nrem", "rem", "deep"}]
    if not fases:
        return {"erro": "Fases inválidas. Use 'nrem,rem,deep' ou subconjunto."}
    asyncio.create_task(_st.ciclo_completo(fases))
    log(f"[SHADOW] Ciclo disparado manualmente — fases: {fases}")
    return {"ok": True, "fases_disparadas": fases, "mensagem": "Ciclo iniciado em background — veja maestro.log."}


# ── Voz bidirecional (Gemini Live API) ───────────────────────────────────────
_voice_live_ativas = 0  # sessões /ws/voice abertas agora — exposto em /integracoes

@app.websocket("/ws/voice")
async def voice_ws(websocket: WebSocket):
    global _voice_live_ativas
    _voice_live_ativas += 1
    try:
        await lyra_voice_live.voice_session(websocket, GEMINI_API_KEY)
    finally:
        _voice_live_ativas -= 1


# ── Integrações — status unificado pro painel do frontend ────────────────────
def _processo_rodando(trecho: str) -> bool:
    """True se existe um processo cujo cmdline contém o trecho (ex: 'mic_engine')."""
    try:
        for p in psutil.process_iter(["cmdline"]):
            if trecho in " ".join(p.info.get("cmdline") or []):
                return True
    except Exception:
        pass
    return False


@app.get("/integracoes")
async def integracoes_status():
    """Agrega o status das integrações num payload único pra view de
    integrações do frontend. Chaves casam com os ids dos cards no ui.js."""
    telegram_on = await asyncio.to_thread(_processo_rodando, "lyra_telegram")
    mic_on      = await asyncio.to_thread(_processo_rodando, "mic_engine")
    return {
        "telegram": {"online": telegram_on,
                     "status": "bot rodando" if telegram_on else "processo parado"},
        "voz_live": {"online": _voice_live_ativas > 0,
                     "status": f"{_voice_live_ativas} sessão(ões) ativa(s)"
                               if _voice_live_ativas else "pronta — clique no botão de voz live"},
        "mic":      {"online": mic_on,
                     "status": "escutando wake-word" if mic_on else "mic_engine.py parado"},
        "tts":      {"online": not _tts_mudo,
                     "status": "mudo" if _tts_mudo else "respondendo por voz"},
        "enxame":   {"online": True, "status": "disponível via /enxame"},
        "upload":   {"online": True, "status": "imagem · áudio · vídeo"},
    }


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
