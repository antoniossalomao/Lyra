"""llm_cascade.py — unified LLM fallback chain: Groq → Gemini → Claude CLI → local Ollama.

Consolidates three near-identical implementations that lived in
cerebro_maestro.py (streaming SSE), lyra_agent.py (batch ReAct) and
lyra_agentes.py (batch subtasks). One class, two usage modes:

  * Streaming — ``stream_groq/stream_gemini/stream_claude_cli/stream_local``:
    async generators yielding text chunks, with mid-stream tool execution.
    Used by cerebro_maestro's /chat SSE endpoint.
  * Batch — ``run()``: a non-streaming ReAct loop that tries providers in
    order and returns the final answer plus the tool-call trace. Used by
    lyra_agent (autonomous runs) and lyra_agentes (swarm subtasks).

Provider clients are lazy-initialized behind threading.Lock (double-checked)
so concurrent first calls never build two clients.
"""

import asyncio
import json
import re
import shutil
import threading
from typing import Any, AsyncGenerator, Callable

import ollama

from config import (GROQ_MODEL, GEMINI_MODEL, LOCAL_MODEL, OLLAMA_URL,
                    LLM_TIMEOUT_S, MAX_TOOL_ITERATIONS)


class ToolCall:
    """Normalized tool-call representation shared by every provider format."""
    __slots__ = ("id", "name", "args")

    def __init__(self, id, name, args):
        self.id, self.name, self.args = id, name, args


class _RoundCtx:
    """Per-round scratch state for the shared streaming tool loop.

    ``tool_calls`` is set by the provider's transmit function when the model
    requested tools; ``extra`` carries the provider-native raw payload needed
    to rebuild the conversation state (Groq deltas, Gemini parts, ...).
    """
    __slots__ = ("tool_calls", "extra")

    def __init__(self):
        self.tool_calls: list[ToolCall] | None = None
        self.extra = None


class LLMCascade:
    """Manages the LLM fallback chain: Groq → Gemini → Claude CLI → Local Ollama.

    Why one class: the ReAct loop ("call model → collect tool_calls → execute
    → reinject → repeat") was triplicated across the codebase with only the
    per-provider message format changing. Here each provider contributes a
    transmit + apply pair and everything else is shared.

    Attributes:
        tool_executor: sync callable ``(name, args) -> str`` that runs a tool
            and returns its JSON result. Injected by the consumer (the cerebro
            wraps it with rate-limit/risk checks; agents use a sandboxed map).
        log:    callable for diagnostics (defaults to print).
        notify: optional callable(titulo=, mensagem=, urgencia=) used before
            falling back to the Claude CLI tier.
    """

    def __init__(self, api_keys: dict[str, str],
                 tool_executor: Callable[[str, dict], str] | None = None,
                 log: Callable = print,
                 notify: Callable | None = None):
        self.groq_key = api_keys.get("groq", "")
        self.gemini_key = api_keys.get("gemini", "")
        self.tool_executor = tool_executor or (lambda nome, args: json.dumps(
            {"erro": f"'{nome}' indisponível: cascade sem tool_executor."}))
        self.log = log
        self.notify = notify
        self._groq_client = None
        self._gemini_client = None
        self._ollama_client = None
        self._gemini_tools_cache: dict[int, list] = {}
        self._lock = threading.Lock()

    # ── Lazy provider clients (thread-safe, double-checked) ──────────────────

    def _get_groq(self):
        """Return the AsyncGroq client, initializing it on first call."""
        if self._groq_client is None and self.groq_key:
            with self._lock:
                if self._groq_client is None:
                    from groq import AsyncGroq
                    self._groq_client = AsyncGroq(api_key=self.groq_key)
        return self._groq_client

    def _get_gemini(self):
        """Return the google-genai client, initializing it on first call."""
        if self._gemini_client is None and self.gemini_key:
            with self._lock:
                if self._gemini_client is None:
                    from google import genai
                    self._gemini_client = genai.Client(api_key=self.gemini_key)
        return self._gemini_client

    def _get_ollama(self):
        """Return the shared AsyncClient for the local Ollama instance."""
        if self._ollama_client is None:
            with self._lock:
                if self._ollama_client is None:
                    self._ollama_client = ollama.AsyncClient(host=OLLAMA_URL)
        return self._ollama_client

    def gemini_tools(self, tools_schema: list) -> list:
        """Convert OpenAI-format tool schema to Gemini FunctionDeclaration format.

        Cached per schema identity — the schema list does not change at runtime,
        so id() is a stable cache key for the process lifetime.
        """
        key = id(tools_schema)
        cached = self._gemini_tools_cache.get(key)
        if cached is None:
            with self._lock:
                cached = self._gemini_tools_cache.get(key)
                if cached is None:
                    from google.genai import types
                    decls = [
                        types.FunctionDeclaration(
                            name=t["function"]["name"],
                            description=t["function"].get("description", ""),
                            parametersJsonSchema=t["function"].get(
                                "parameters", {"type": "object", "properties": {}}),
                        )
                        for t in tools_schema
                    ]
                    cached = [types.Tool(function_declarations=decls)]
                    self._gemini_tools_cache[key] = cached
        return cached

    # ═════════════════════════════ STREAM MODE ══════════════════════════════
    # Contract (same as the original cerebro implementation): each stream_*
    # method is an async generator yielding clean text chunks, including the
    # "_[Executando: x]_" markers when a tool runs mid-stream. It must raise
    # BEFORE yielding anything if the provider fails, so the caller can fall
    # through to the next tier.

    async def _run_stream_loop(self, state, tools, provider_name,
                               transmit, apply_tool_calls):
        """Shared streaming ReAct loop: transmit one round, execute requested
        tools, reinject results, repeat (bounded by MAX_TOOL_ITERATIONS)."""
        for _ in range(MAX_TOOL_ITERATIONS):
            ctx = _RoundCtx()
            async for chunk in transmit(state, tools, ctx):
                yield chunk
            if not ctx.tool_calls:
                return
            results = []
            for tc in ctx.tool_calls:
                self.log(f"[TOOL {provider_name}] {tc.name}({tc.args})")
                yield f"\n_[Executando: {tc.name}]_\n"
                res_str = await asyncio.to_thread(self.tool_executor, tc.name, tc.args)
                results.append((tc, res_str))
            state = apply_tool_calls(state, ctx.tool_calls, results, ctx.extra)

    # ── Groq ─────────────────────────────────────────────────────────────────

    async def _groq_transmit(self, msgs, tools, ctx):
        client = self._get_groq()
        if not client:
            raise RuntimeError("GROQ_API_KEY não configurada")
        kwargs = {"model": GROQ_MODEL, "messages": msgs, "stream": True, "temperature": 0.4}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = await client.chat.completions.create(**kwargs)
        tool_calls_acc: dict[int, dict] = {}
        async for chunk in resp:
            delta = chunk.choices[0].delta
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    acc = tool_calls_acc.setdefault(tc.index, {"id": None, "name": "", "arguments": ""})
                    if tc.id:
                        acc["id"] = tc.id
                    if tc.function and tc.function.name:
                        acc["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        acc["arguments"] += tc.function.arguments
            if delta.content:
                yield delta.content

        if not tool_calls_acc:
            return
        calls = [v for _, v in sorted(tool_calls_acc.items())]
        ctx.extra = calls
        ctx.tool_calls = []
        for v in calls:
            try:
                args = json.loads(v["arguments"] or "{}")
            except Exception:
                args = {}
            if not isinstance(args, dict):
                # Groq sometimes sends the literal "null" as arguments —
                # json.loads yields None and **None would break the call.
                args = {}
            ctx.tool_calls.append(ToolCall(v["id"], v["name"], args))

    @staticmethod
    def _groq_apply(msgs, tool_calls, results, raw_calls):
        msgs.append({
            "role": "assistant", "content": None,
            "tool_calls": [{"id": v["id"], "type": "function",
                            "function": {"name": v["name"], "arguments": v["arguments"]}}
                           for v in raw_calls],
        })
        for tc, res_str in results:
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": res_str})
        return msgs

    async def stream_groq(self, messages: list, tools, system_prompt: str) -> AsyncGenerator:
        """Stream a Groq response token by token (OpenAI format, native tools)."""
        state = [{"role": "system", "content": system_prompt}] + messages
        async for chunk in self._run_stream_loop(state, tools, "groq",
                                                 self._groq_transmit, self._groq_apply):
            yield chunk

    # ── Gemini ───────────────────────────────────────────────────────────────

    async def stream_gemini(self, messages: list, tools, system_prompt: str) -> AsyncGenerator:
        """Stream a Gemini response, handling its native function-call format."""
        from google.genai import types

        async def transmit(contents, tools_, ctx):
            client = self._get_gemini()
            if not client:
                raise RuntimeError("GEMINI_API_KEY não configurada")
            cfg_kwargs = {"system_instruction": system_prompt, "temperature": 0.4}
            if tools_:
                cfg_kwargs["tools"] = self.gemini_tools(tools_)
            cfg = types.GenerateContentConfig(**cfg_kwargs)
            resp_stream = await client.aio.models.generate_content_stream(
                model=GEMINI_MODEL, contents=contents, config=cfg)

            function_calls = []
            model_parts_acc = []
            async for chunk in resp_stream:
                if not chunk.candidates:
                    continue
                for part in chunk.candidates[0].content.parts:
                    if getattr(part, "function_call", None):
                        function_calls.append(part)
                        model_parts_acc.append(part)
                    elif getattr(part, "text", None):
                        yield part.text
                        model_parts_acc.append(part)

            if not function_calls:
                return
            ctx.extra = model_parts_acc
            ctx.tool_calls = [ToolCall(None, p.function_call.name,
                                       dict(p.function_call.args or {}))
                              for p in function_calls]

        def apply(contents, tool_calls, results, model_parts_acc):
            contents.append(types.Content(role="model", parts=model_parts_acc))
            resp_parts = []
            for tc, res_str in results:
                try:
                    res_obj = json.loads(res_str)
                except Exception:
                    res_obj = {"resultado": res_str}
                resp_parts.append(types.Part(
                    function_response=types.FunctionResponse(name=tc.name, response=res_obj)))
            contents.append(types.Content(role="user", parts=resp_parts))
            return contents

        contents = [
            types.Content(role=("model" if m["role"] == "assistant" else "user"),
                          parts=[types.Part(text=m["content"] or "")])
            for m in messages
        ]
        async for chunk in self._run_stream_loop(contents, tools, "gemini", transmit, apply):
            yield chunk

    # ── Claude CLI ───────────────────────────────────────────────────────────

    async def stream_claude_cli(self, messages: list, tools, system_prompt: str) -> AsyncGenerator:
        """Claude (Sonnet) via headless CLI — third-tier fallback.

        Unlike the other tiers there is no function-calling here: Claude Code
        is a full agent with native file/shell access in C:\\Lyra_Project, so
        "tools" are its own, not ours. Yields the whole answer as one chunk.
        """
        claude_path = shutil.which("claude")
        if not claude_path:
            raise RuntimeError("CLI 'claude' não encontrado no PATH.")

        ultima = messages[-1]["content"] if messages else ""
        # Extrai só a pergunta real do usuário, sem o wrapper "[SISTEMA]/..."
        # — testado: o Claude reage ao wrapper como se fosse a tarefa.
        match = re.search(r"Usuário:\s*(.*)$", ultima, re.DOTALL)
        pergunta_real = match.group(1).strip() if match else ultima

        if self.notify:
            self.notify(
                titulo="Lyra → Claude (fallback)",
                mensagem="Usando Claude Code (prioridade pra código, ou rede de segurança se Groq/Gemini falharem).",
                urgencia="normal",
            )
        # Prefixo PARENTÉTICO de propósito — uma instrução imperativa faz o
        # Claude tratar como configuração de papel e nunca responder a pergunta.
        prefixo = "(Responda como a Lyra, em PT-BR, direto e sem rodeios.) "
        proc = await asyncio.create_subprocess_exec(
            claude_path, "-p", f"{prefixo}{pergunta_real}",
            "--model", "sonnet", "--allow-dangerously-skip-permissions",
            cwd=r"C:\Lyra_Project",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("Claude CLI excedeu o tempo limite (2min) no fallback.")
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode(errors="replace").strip() or "Claude CLI retornou erro.")
        texto = stdout.decode(errors="replace").strip()
        if not texto:
            raise RuntimeError("Claude CLI retornou vazio.")
        yield texto

    # ── Local Ollama ─────────────────────────────────────────────────────────

    async def _local_transmit(self, msgs, tools, ctx):
        s = await self._get_ollama().chat(
            model=LOCAL_MODEL, messages=msgs, stream=True,
            tools=tools, think=False, keep_alive=0)

        tool_calls_buffer = None
        async for chunk in s:
            msg_obj = chunk.get("message", {})
            if msg_obj.get("tool_calls"):
                tool_calls_buffer = msg_obj["tool_calls"]
                continue
            texto_chunk = msg_obj.get("content", "")
            if texto_chunk:
                yield texto_chunk

        if not tool_calls_buffer:
            return
        ctx.extra = tool_calls_buffer
        ctx.tool_calls = [
            ToolCall(None, tc["function"]["name"], tc["function"].get("arguments") or {})
            for tc in tool_calls_buffer
        ]

    @staticmethod
    def _local_apply(msgs, tool_calls, results, tool_calls_buffer):
        msgs.append({"role": "assistant", "content": "", "tool_calls": tool_calls_buffer})
        for tc, res_str in results:
            msgs.append({"role": "tool", "name": tc.name, "content": res_str})
        return msgs

    async def stream_local(self, messages: list, tools, system_prompt: str) -> AsyncGenerator:
        """qwen3:8b local via Ollama — last-resort tier. keep_alive=0 unloads
        the model from VRAM right after answering (cloud is the main path)."""
        state = [{"role": "system", "content": system_prompt}] + messages
        async for chunk in self._run_stream_loop(state, tools, "local",
                                                 self._local_transmit, self._local_apply):
            yield chunk

    @staticmethod
    async def first_chunk_or_fail(gen):
        """Consume the generator's first chunk — if it fails (exception or
        empty generator) BEFORE that chunk, the caller falls through to the
        next tier. On success returns a generator that replays the chunk and
        continues (full commit to this tier from then on)."""
        first = await gen.__anext__()

        async def _continuation():
            yield first
            async for chunk in gen:
                yield chunk

        return _continuation()

    # ═════════════════════════════ BATCH MODE ═══════════════════════════════

    async def run(self, goal: str = "", tools_schema: list | None = None,
                  tool_executor: Callable[[str, dict], str] | None = None,
                  max_iterations: int = 10,
                  providers: list[str] | None = None,
                  system_prompt: str = "",
                  messages: list | None = None,
                  temperature: float = 0.3,
                  max_tokens: int = 1500) -> dict:
        """Execute a non-streaming ReAct loop, trying providers in order.

        Args:
            goal:           Natural-language objective (ignored when messages given).
            tools_schema:   OpenAI-format tool definitions (may be empty).
            tool_executor:  Override for the instance-level executor.
            max_iterations: Maximum tool-call rounds per provider.
            providers:      Provider order (default ["groq", "gemini", "local"]).
            system_prompt:  System instruction for the run.
            messages:       Full message list override (role system handled).
            temperature:    Sampling temperature.
            max_tokens:     Response token cap (Groq only; Gemini/local unbounded).

        Returns:
            Dict with keys: resposta_final (str), passos (list), iteracoes_usadas
            (int), sucesso (bool), provider (str|None), erros (list[str]).
        """
        tools_schema = tools_schema or []
        executor = tool_executor or self.tool_executor
        if messages is None:
            messages = [{"role": "system", "content": system_prompt},
                        {"role": "user", "content": goal}]
        providers = providers or ["groq", "gemini", "local"]

        runners = {"groq": self._run_groq, "gemini": self._run_gemini,
                   "local": self._run_local}
        erros: list[str] = []
        for name in providers:
            if name == "groq" and not self.groq_key:
                continue
            if name == "gemini" and not self.gemini_key:
                continue
            try:
                result = await runners[name](messages, tools_schema, executor,
                                             max_iterations, temperature, max_tokens)
                result["provider"] = name
                result["erros"] = erros
                return result
            except Exception as e:
                erros.append(f"{name}: {e}")

        return {"resposta_final": "", "passos": [], "iteracoes_usadas": 0,
                "sucesso": False, "provider": None, "erros": erros}

    async def _run_groq(self, messages, tools_schema, executor,
                        max_iterations, temperature, max_tokens) -> dict:
        """Batch ReAct loop via Groq (OpenAI format). Raises on provider failure."""
        client = self._get_groq()
        msgs = list(messages)
        passos = []
        for _iter in range(max_iterations):
            kwargs = {"model": GROQ_MODEL, "messages": msgs,
                      "temperature": temperature, "max_tokens": max_tokens}
            if tools_schema:
                kwargs["tools"] = tools_schema
                kwargs["tool_choice"] = "auto"
            resp = await asyncio.wait_for(
                client.chat.completions.create(**kwargs), timeout=LLM_TIMEOUT_S)
            msg_llm = resp.choices[0].message
            tool_calls = getattr(msg_llm, "tool_calls", None) or []
            if not tool_calls:
                return {"resposta_final": (msg_llm.content or "").strip(),
                        "passos": passos, "iteracoes_usadas": _iter + 1, "sucesso": True}
            msgs.append({
                "role": "assistant", "content": msg_llm.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in tool_calls
                ],
            })
            for tc in tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    if not isinstance(args, dict):
                        args = {}
                except Exception:
                    args = {}
                res_str = await asyncio.to_thread(executor, tc.function.name, args)
                passos.append({"tool": tc.function.name, "args": args, "resultado": res_str[:2000]})
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": res_str})
        return {"resposta_final": "", "passos": passos,
                "iteracoes_usadas": max_iterations, "sucesso": False}

    async def _run_gemini(self, messages, tools_schema, executor,
                          max_iterations, temperature, max_tokens) -> dict:
        """Batch ReAct loop via Gemini (native FunctionCall/FunctionResponse)."""
        from google import genai  # noqa: F401 — garante SDK presente antes de usar types
        from google.genai import types as gtypes

        client = self._get_gemini()
        system_txt = next((m["content"] for m in messages if m["role"] == "system"), "")
        contents = [
            gtypes.Content(role=("model" if m["role"] == "assistant" else "user"),
                           parts=[gtypes.Part(text=m.get("content") or "")])
            for m in messages if m["role"] != "system"
        ]
        cfg_kwargs = {"system_instruction": system_txt, "temperature": temperature}
        if tools_schema:
            cfg_kwargs["tools"] = self.gemini_tools(tools_schema)
        cfg = gtypes.GenerateContentConfig(**cfg_kwargs)

        passos = []
        for _iter in range(max_iterations):
            resp = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=GEMINI_MODEL, contents=contents, config=cfg),
                timeout=LLM_TIMEOUT_S,
            )
            if not resp.candidates:
                return {"resposta_final": "", "passos": passos,
                        "iteracoes_usadas": _iter + 1, "sucesso": False}
            partes = resp.candidates[0].content.parts or []
            fcalls = [p for p in partes if getattr(p, "function_call", None)]
            if not fcalls:
                return {"resposta_final": (resp.text or "").strip(), "passos": passos,
                        "iteracoes_usadas": _iter + 1, "sucesso": True}
            contents.append(gtypes.Content(role="model", parts=partes))
            resp_parts = []
            for p in fcalls:
                nome = p.function_call.name
                args = dict(p.function_call.args or {})
                res_str = await asyncio.to_thread(executor, nome, args)
                passos.append({"tool": nome, "args": args, "resultado": res_str[:2000]})
                try:
                    res_obj = json.loads(res_str)
                except Exception:
                    res_obj = {"resultado": res_str}
                resp_parts.append(gtypes.Part(
                    function_response=gtypes.FunctionResponse(name=nome, response=res_obj)))
            contents.append(gtypes.Content(role="user", parts=resp_parts))
        return {"resposta_final": "", "passos": passos,
                "iteracoes_usadas": max_iterations, "sucesso": False}

    async def _run_local(self, messages, tools_schema, executor,
                         max_iterations, temperature, max_tokens) -> dict:
        """Batch ReAct loop via local Ollama (qwen3:8b) — last cascade tier.
        keep_alive=0: unload from VRAM right after (cloud is the main path)."""
        client = self._get_ollama()
        msgs = list(messages)
        passos = []
        for _iter in range(max_iterations):
            resp = await asyncio.wait_for(
                client.chat(model=LOCAL_MODEL, messages=msgs, tools=tools_schema,
                            think=False, keep_alive=0),
                timeout=LLM_TIMEOUT_S,
            )
            msg_obj = resp.get("message", {})
            tool_calls = msg_obj.get("tool_calls")
            if not tool_calls:
                return {"resposta_final": (msg_obj.get("content") or "").strip(),
                        "passos": passos, "iteracoes_usadas": _iter + 1, "sucesso": True}
            msgs.append({"role": "assistant", "content": "", "tool_calls": tool_calls})
            for tc in tool_calls:
                func = tc["function"]
                nome = func["name"]
                args = func.get("arguments", {})
                if not isinstance(args, dict):
                    args = {}
                res_str = await asyncio.to_thread(executor, nome, args)
                passos.append({"tool": nome, "args": args, "resultado": res_str[:2000]})
                msgs.append({"role": "tool", "name": nome, "content": res_str})
        return {"resposta_final": "", "passos": passos,
                "iteracoes_usadas": max_iterations, "sucesso": False}
