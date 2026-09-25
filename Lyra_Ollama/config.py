"""config.py — single source of truth for ports, URLs, model IDs, and limits.

Every hardcoded value previously scattered across the codebase (127 magic
strings counted during the OOP refactor of 2026-08-07) is defined here once.
All services bind to 127.0.0.1 only (project rule: nothing listens on 0.0.0.0).
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ── Service ports ────────────────────────────────────────────────────────────
CEREBRO_PORT = 8000   # cerebro_maestro FastAPI
EMBED_PORT   = 8001   # embed_service (BGE-M3)
SURREAL_PORT = 8090   # SurrealDB HTTP
QDRANT_PORT  = 6333   # Qdrant HTTP
OLLAMA_PORT  = 11434  # Ollama local models

# ── Derived URLs (one definition, used everywhere) ───────────────────────────
CEREBRO_URL = f"http://127.0.0.1:{CEREBRO_PORT}"
SURREAL_URL = f"http://127.0.0.1:{SURREAL_PORT}/sql"
EMBED_URL   = f"http://127.0.0.1:{EMBED_PORT}/embed"
RERANK_URL  = f"http://127.0.0.1:{EMBED_PORT}/rerank"
EMBED_HEALTH_URL = f"http://127.0.0.1:{EMBED_PORT}/health"
QDRANT_URL  = f"http://127.0.0.1:{QDRANT_PORT}"
OLLAMA_URL  = f"http://127.0.0.1:{OLLAMA_PORT}"

# ── SurrealDB connection parameters ──────────────────────────────────────────
SURREAL_NS      = "lyra_core"
SURREAL_DB      = "Db_CORTEX"
SURREAL_AUTH    = (os.getenv("SURREAL_USER", "root"), os.getenv("SURREAL_PASS", "root"))
SURREAL_HEADERS = {
    "Accept": "application/json",
    "surreal-ns": SURREAL_NS,
    "surreal-db": SURREAL_DB,
}

# ── Model identifiers ────────────────────────────────────────────────────────
GROQ_MODEL       = "openai/gpt-oss-120b"   # llama-3.3-70b deprecated 17/jun/2026
GEMINI_MODEL     = "gemini-3.5-flash"
LOCAL_MODEL      = "Lyra"                  # qwen3:8b local — last cascade tier
DRAFT_MODEL      = "qwen3:0.6b"            # hallucination-detection sidecar

# ── Memory / Qdrant ──────────────────────────────────────────────────────────
QDRANT_COLLECTION = "lyra_memory_v2"       # BGE-M3 1024d (migration 26/06/2026)
EMBED_DIM         = 1024

# ── Auth (Lyra 2.0 — proteção de acesso mínima, ver PLANEJAMENTO_LYRA2.0.md §5) ─
# JWT em cookie httpOnly, expiração longa (app pessoal, sem refresh token).
# AUTH_JWT_SECRET tem default só pra não quebrar em dev sem .env — TROCAR em
# produção via variável de ambiente (mesma convenção de SURREAL_USER/PASS acima).
AUTH_JWT_SECRET       = os.getenv("AUTH_JWT_SECRET", "lyra-dev-secret-trocar-no-.env")
AUTH_COOKIE_NAME      = "lyra_session"
AUTH_COOKIE_MAX_AGE_S = 60 * 60 * 24 * 30  # 30 dias

# ── Operational limits ───────────────────────────────────────────────────────
MAX_TOOL_ITERATIONS = 25    # safety cap on tool-calling rounds per chat
MAX_HISTORY_MSGS    = 14    # history length that triggers compression
LLM_TIMEOUT_S       = 120   # per-call timeout for batch LLM requests
SURREAL_TIMEOUT_S   = 10    # default SurrealDB request timeout
