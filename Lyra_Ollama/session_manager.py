"""session_manager.py — conversation state for cerebro_maestro.

All mutable session state that previously lived as ~10 module-level globals
in cerebro_maestro.py (historico_recente, sessao_atual, _session_briefing,
_sessao_titulo_ok, _contador_turnos, _comprimindo, locks) now lives here,
protected by asyncio.Lock / asyncio.Event.
"""

import asyncio
import datetime
import json
import uuid
from typing import Callable

from config import GROQ_MODEL, MAX_HISTORY_MSGS
from surreal_client import SurrealClient


class SessionManager:
    """Manages conversation history, session identity, and startup sync.

    Thread-safety contract:
        - append_user/append_assistant/snapshot always acquire _lock.
        - Callers must never touch _history directly — use snapshot() to read.
        - wait_ready() blocks until load_initial_state() finished; the /chat
          endpoint awaits it so the first message never races the startup
          restore (bug: sessao None + histórico vazio nos primeiros segundos).

    Attributes:
        session_id: active session UUID (SurrealDB 'sessao' table) or None.
        briefing:   dynamic system-prompt suffix built at startup.
    """

    def __init__(self, surreal: SurrealClient, get_groq: Callable, log: Callable):
        self._surreal = surreal
        self._get_groq = get_groq   # lazy Groq client getter (briefing/compression)
        self._log = log
        self._history: list[dict] = []
        self._lock = asyncio.Lock()
        self._ready = asyncio.Event()
        self._compressing = False
        self._turn_counter = 0
        self.session_id: str | None = None
        self.briefing = ""
        self._title_ok = False  # True quando a sessão ativa já ganhou título

    # ── History access ───────────────────────────────────────────────────────

    async def append_user(self, text: str) -> tuple[int, int]:
        """Append a user message; atomically increment the turn counter.

        Returns:
            (turn_number, history_size) — size lets the caller decide whether
            to schedule compression without re-acquiring the lock.
        """
        async with self._lock:
            self._turn_counter += 1
            self._history.append({"role": "user", "content": text})
            return self._turn_counter, len(self._history)

    async def append_assistant(self, text: str, **meta) -> None:
        """Append an assistant message with optional metadata (fontes_rag,
        divergencia_draft). Metadata is stripped by sanitized_messages()."""
        async with self._lock:
            self._history.append({"role": "assistant", "content": text, **meta})

    async def snapshot(self) -> list[dict]:
        """Point-in-time shallow copy of the history (items shared, list not)."""
        async with self._lock:
            return list(self._history)

    async def sanitized_messages(self) -> list[dict]:
        """History copy reduced to role/content only — extra metadata keys make
        Groq reject the request with 400 'unsupported property'."""
        async with self._lock:
            return [{"role": m["role"], "content": m["content"]} for m in self._history]

    @property
    def turn_counter(self) -> int:
        """Current turn number (plain int read — atomic in CPython)."""
        return self._turn_counter

    @property
    def history_len(self) -> int:
        return len(self._history)

    # ── Startup ──────────────────────────────────────────────────────────────

    async def wait_ready(self) -> None:
        """Block until load_initial_state() has finished."""
        await self._ready.wait()

    async def load_initial_state(self) -> None:
        """Restore session + history from SurrealDB, build the briefing, run
        Goal Drift and Session Replay. Always signals _ready at the end, even
        on partial failure — chat must not deadlock because startup broke."""
        try:
            await self._load_impl()
        finally:
            self._ready.set()

    async def _load_impl(self) -> None:
        await asyncio.sleep(4)  # aguarda _init() terminar e serviços subirem
        log = self._log
        surreal = self._surreal

        # 0. Sessões: retoma a mais recente; se não houver, cria a primeira.
        try:
            result = await surreal.query_result(
                "SELECT sessao_id, timestamp FROM evento "
                "WHERE sessao_id IS NOT NONE ORDER BY timestamp DESC LIMIT 1")
            if result and result[0].get("sessao_id"):
                self.session_id = result[0]["sessao_id"]
                self._title_ok = True
                log(f"[INIT] Sessão retomada: {self.session_id}")
        except Exception as e:
            log(f"[INIT] Falha ao retomar sessão: {e}")
        if not self.session_id:
            self.session_id = str(uuid.uuid4())
            try:
                await surreal.query("CREATE sessao CONTENT " + json.dumps(
                    {"id": self.session_id,
                     "criada": datetime.datetime.now().isoformat(), "titulo": ""}))
                log(f"[INIT] Primeira sessão criada: {self.session_id}")
            except Exception as e:
                log(f"[INIT] Falha ao criar sessão inicial: {e}")

        # 1. Restaura histórico do SurrealDB
        try:
            if self._title_ok:  # sessão retomada — restaura só as msgs dela
                query = ("SELECT ator, texto, timestamp FROM evento "
                         f"WHERE sessao_id = {json.dumps(self.session_id)} "
                         "ORDER BY timestamp DESC LIMIT 20")
            else:               # pré-migração — últimas msgs gerais
                query = "SELECT ator, texto, timestamp FROM evento ORDER BY timestamp DESC LIMIT 20"
            eventos = await surreal.query_result(query, timeout=10)
            eventos = sorted(eventos, key=lambda e: e.get("timestamp", ""))
            historico_novo = [
                {"role": "user" if ev.get("ator") == "Antônio" else "assistant",
                 "content": ev.get("texto", "")}
                for ev in eventos[-10:]
            ]
            if historico_novo:
                async with self._lock:
                    self._history = historico_novo
                log(f"[INIT] Histórico restaurado: {len(historico_novo)} msgs do SurrealDB.")
        except Exception as e:
            log(f"[INIT] Falha ao carregar histórico: {e}")

        # 2. Briefing da sessão anterior via Groq (rápido, gratuito)
        try:
            client = self._get_groq()
            hist = await self.snapshot()
            if client and hist:
                resumo_msgs = "\n".join(
                    f"{'Antônio' if m['role'] == 'user' else 'Lyra'}: {m['content'][:300]}"
                    for m in hist[-10:]
                )
                resp = await client.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=[
                        {"role": "system", "content":
                            "Você é a Lyra. Em até 4 linhas, resuma o contexto da última "
                            "conversa abaixo para ser injetado no seu system prompt. Foque "
                            "no que foi feito/decidido. Seja direta, sem saudações."},
                        {"role": "user", "content": resumo_msgs},
                    ],
                    max_tokens=150, temperature=0.2,
                )
                briefing = resp.choices[0].message.content.strip()
                self.briefing = f"\n\n[ÚLTIMA SESSÃO]\n{briefing}"
                log(f"[INIT] Briefing: {briefing[:120]}...")
        except Exception as e:
            log(f"[INIT] Falha ao gerar briefing: {e}")

        # 3. Innovation 1 — Goal Drift: objetivos recentes não concluídos
        try:
            objetivos = await surreal.query_result(
                "SELECT id, texto, timestamp FROM evento "
                "WHERE intencao = 'objetivo' ORDER BY timestamp DESC LIMIT 10;", timeout=5)
            if objetivos:
                linhas = [f"- [{ev.get('timestamp','')[:16]}] {ev.get('texto','')[:120]}"
                          for ev in objetivos[:5]]
                self.briefing += "\n\n[OBJETIVOS RECENTES]\n" + "\n".join(linhas)
                log(f"[INIT] {len(objetivos)} objetivos recentes no contexto.")
        except Exception as e:
            log(f"[INIT] Goal Drift falhou: {e}")

        # 4. Innovation 3 — Session Replay: tópicos + ferramentas das últimas 24h
        try:
            import re as _re
            ontem = (datetime.datetime.now() - datetime.timedelta(hours=24)).isoformat()
            topicos = await surreal.query_result(
                f"SELECT out AS topico, count() AS freq FROM sobre "
                f"WHERE in.timestamp >= '{ontem}' GROUP BY out ORDER BY freq DESC LIMIT 6;",
                timeout=5)
            nomes = [str(t.get("topico", "")).split(":")[-1] for t in topicos if t.get("topico")]
            nomes = [n for n in nomes if n][:6]
            if nomes:
                self.briefing += "\n\n[TÓPICOS ATIVOS (24h)]\n" + ", ".join(nomes)
            evs_t = await surreal.query_result(
                f"SELECT texto FROM evento WHERE ator = 'Lyra' "
                f"AND texto CONTAINS '_[Executando:' AND timestamp >= '{ontem}' LIMIT 20;",
                timeout=5)
            tools_usadas: set[str] = set()
            for ev in evs_t:
                for m in _re.findall(r"_\[Executando: ([^\]]+)\]_", ev.get("texto", "")):
                    tools_usadas.add(m.strip())
            if tools_usadas:
                self.briefing += "\n[FERRAMENTAS RECENTES]\n" + ", ".join(sorted(tools_usadas)[:8])
            if nomes or tools_usadas:
                log(f"[INIT] Session Replay: tópicos={nomes}, tools={sorted(tools_usadas)}")
        except Exception as e:
            log(f"[INIT] Session Replay falhou: {e}")

    # ── Session title ────────────────────────────────────────────────────────

    async def ensure_title(self, texto: str) -> None:
        """Set the session title from the first user utterance (sidebar label).
        No-op once the title exists."""
        if not self.session_id or self._title_ok:
            return
        self._title_ok = True
        titulo = " ".join(texto.split())[:60]
        try:
            await self._surreal.query(
                f'UPDATE type::record("sessao", {json.dumps(self.session_id)}) '
                f"SET titulo = {json.dumps(titulo)}")
        except Exception as e:
            self._log(f"[SESSAO] Falha ao definir título: {e}")

    # ── History compression ──────────────────────────────────────────────────

    async def compress_if_needed(self) -> None:
        """When history exceeds MAX_HISTORY_MSGS, compress the 8 oldest
        messages into a Groq summary, keeping the recent tail intact.
        Guarded by _compressing so two compressions never run at once."""
        if self._compressing or len(self._history) <= MAX_HISTORY_MSGS:
            return
        self._compressing = True
        async with self._lock:
            a_comprimir = self._history[:8]
            self._history = self._history[8:]
        try:
            client = self._get_groq()
            if not client:
                return
            bloco = "\n".join(
                f"{'Antônio' if m['role'] == 'user' else 'Lyra'}: {m['content'][:400]}"
                for m in a_comprimir
            )
            resp = await client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content":
                        "Você é a Lyra. Comprima as mensagens abaixo em até 5 linhas "
                        "preservando fatos, decisões e código relevante. Sem saudações."},
                    {"role": "user", "content": bloco},
                ],
                max_tokens=200, temperature=0.1,
            )
            resumo = resp.choices[0].message.content.strip()
            async with self._lock:
                self._history.insert(0, {
                    "role": "user",
                    "content": f"[RESUMO DE CONTEXTO ANTERIOR]\n{resumo}",
                })
                self._history.insert(1, {
                    "role": "assistant",
                    "content": "Contexto anterior registrado.",
                })
            self._log("[HIST] Histórico comprimido: 8 msgs → 2 (sumário via Groq).")
        except Exception as e:
            self._log(f"[HIST] Falha na compressão: {e}")
            async with self._lock:
                self._history = self._history[-10:]
        finally:
            self._compressing = False

    # ── Session switching ────────────────────────────────────────────────────

    async def new_session(self) -> dict:
        """Create a fresh session, make it active, wipe the in-memory history
        (SurrealDB/Qdrant untouched — long-term memory keeps working via RAG)."""
        novo_id = str(uuid.uuid4())
        try:
            await self._surreal.query("CREATE sessao CONTENT " + json.dumps(
                {"id": novo_id, "criada": datetime.datetime.now().isoformat(), "titulo": ""}))
        except Exception as e:
            return {"erro": f"Falha ao criar sessão: {e}"}
        async with self._lock:
            self.session_id = novo_id
            self._title_ok = False
            self._history = []
        self._compressing = False
        self._log(f"[SESSAO] Nova sessão ativa: {novo_id}")
        return {"ok": True, "sessao_id": novo_id}

    async def activate_session(self, sessao_id: str) -> dict:
        """Switch to another session and reload its recent messages.

        Returns the full message list (with timestamps) for the frontend,
        or {"erro": ...} on failure. 'legado' is read-only and rejected."""
        if sessao_id == "legado":
            return {"erro": "A sessão 'legado' é somente leitura."}
        try:
            eventos = await self._surreal.query_result(
                "SELECT ator, texto, timestamp FROM evento "
                f"WHERE sessao_id = {json.dumps(sessao_id)} ORDER BY timestamp ASC LIMIT 300")
        except Exception as e:
            return {"erro": f"Falha ao ativar sessão: {e}"}
        async with self._lock:
            self.session_id = sessao_id
            self._title_ok = True
            self._history = [
                {"role": "assistant" if ev.get("ator", "").lower() == "lyra" else "user",
                 "content": ev.get("texto", "")}
                for ev in eventos[-10:]
            ]
        self._compressing = False
        self._log(f"[SESSAO] Sessão ativada: {sessao_id} ({len(eventos)} msgs)")
        mensagens = [
            {"role": "assistant" if ev.get("ator", "").lower() == "lyra" else "user",
             "content": ev.get("texto", ""), "timestamp": ev.get("timestamp", "")}
            for ev in eventos
        ]
        return {"ok": True, "sessao_id": sessao_id, "total": len(mensagens),
                "mensagens": mensagens}

    async def rename_session(self, sessao_id: str, titulo: str) -> dict:
        """Overwrite a session's sidebar title (user-triggered rename, unlike
        ensure_title() which only fires once automatically)."""
        try:
            await self._surreal.query(
                f'UPDATE type::record("sessao", {json.dumps(sessao_id)}) '
                f"SET titulo = {json.dumps(titulo[:60])}")
        except Exception as e:
            return {"erro": f"Falha ao renomear: {e}"}
        if sessao_id == self.session_id:
            self._title_ok = True
        return {"ok": True}

    async def favorite_session(self, sessao_id: str, favorita: bool) -> dict:
        """Marca/desmarca uma sessão como favorita (LYRA_NUCLEO.md
        §5.4). Campo `favorita` é aditivo — SurrealDB é schemaless,
        sessões antigas sem o campo simplesmente respondem False quando lidas
        (ver SessionsRouter.sessoes_listar)."""
        try:
            await self._surreal.query(
                f'UPDATE type::record("sessao", {json.dumps(sessao_id)}) '
                f"SET favorita = {json.dumps(favorita)}")
        except Exception as e:
            return {"erro": f"Falha ao favoritar: {e}"}
        return {"ok": True, "favorita": favorita}

    async def delete_session(self, sessao_id: str) -> dict:
        """Delete a session and its events. If it was the active session,
        switches to a fresh one so the caller always has somewhere to land."""
        if sessao_id == "legado":
            return {"erro": "A sessão 'legado' não pode ser deletada."}
        try:
            await self._surreal.query(f'DELETE type::record("sessao", {json.dumps(sessao_id)})')
            await self._surreal.query(f"DELETE evento WHERE sessao_id = {json.dumps(sessao_id)}")
        except Exception as e:
            return {"erro": f"Falha ao deletar: {e}"}
        if sessao_id == self.session_id:
            return await self.new_session()
        return {"ok": True}

    async def clear_history(self) -> None:
        """Wipe the in-memory history only (does not touch SurrealDB/Qdrant)."""
        async with self._lock:
            self._history = []
        self._compressing = False
