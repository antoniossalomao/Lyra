# LYRA — Referência Técnica

> Consolidado em 30/09/2026 (último registro de trabalho: 12/08/2026). Só o que
> vale hoje: regras, arquitetura, API, gotchas. Visão/decisões/roadmap:
> [LYRA_NUCLEO.md](LYRA_NUCLEO.md) · Operação: [README.md](../README.md)

---

## 1. Stack

| Camada | Tecnologia | Porta / notas |
|---|---|---|
| Orquestrador | `cerebro_maestro.py` (FastAPI, POO) | 8000 |
| Embedding + rerank | `embed_service.py` — BAAI/bge-m3 1024d + bge-reranker-v2-m3 (GPU) | 8001 |
| Hub WS (v1) | `Lyra_Core/Front_end_Lyra/lyra_app.py` | 8765 |
| Vetores | Qdrant standalone **v1.17.1 (fixado)** — `lyra_memory_v2` | 6333 |
| Grafo + documentos | SurrealDB 3.0.5, engine `surrealkv://`, ns `lyra_core`, db `Db_CORTEX` (case-sensitive) | 8090 |
| LLM local | Ollama `qwen3:8b` (+ `qwen3:0.6b` draft, `qwen2.5-coder:7b`, `llava-phi3`) | 11434 |
| LLM cloud | Groq `openai/gpt-oss-120b` → Gemini `gemini-3.5-flash` → Claude (CLI) → local | — |
| STT | faster-whisper "small" CPU int8 + Silero VAD | — |
| TTS | Gemini TTS (voz Leda) → edge-tts Francisca → silêncio | — |
| Frontends | v1 pywebview + Three.js · v2 React/Vite · v3 SvelteKit/Tauri 2 | — |
| IDE | Eclipse Theia (Electron) — "Lyra IDE" | — |

Python 3.12 **global** (sem venv; `venv_embed` aposentado em 30/06). torch
2.6.0+cu124 (bge-m3 exige ≥2.6, pesos só em `.bin`). Rollback do upgrade:
`bin/backup_pip_freeze_python312_30-06-2026.txt` (fora do git).

## 2. Regras críticas (não quebrar)

**Rede e processos**
- **`127.0.0.1`, nunca `localhost`**, em toda chamada interna: o resolver do Windows
  tenta IPv6 primeiro e paga ~2s por chamada (`/buscar` 5.6s → 1.26s ao corrigir).
- **Todo serviço faz bind em `127.0.0.1`.** Qdrant: `QDRANT__SERVICE__HOST=127.0.0.1`
  (default é `0.0.0.0`); SurrealDB: `--bind 127.0.0.1:8090`. Em 04/08 ambos estavam na
  LAN (inclusive via Radmin VPN). Conferir com `netstat` após qualquer mudança de boot.
- **Self-healing chama os próprios `start_*.bat`** (`lyra_seguranca._RESTART_CMDS`),
  nunca comandos inline duplicados — a versão inline subia o Qdrant num storage
  vazio (memória "zerada" silenciosamente) e o SurrealDB com engine errada.
  Sucesso medido por polling de até 20s (Qdrant leva 5-8s para carregar).
- `qdrant.exe` não está no PATH e `NoDefaultCurrentDirectoryInExePath=1` está
  setado: sempre caminho absoluto no `.bat`.
- Porta: teste de socket (`TcpClient.ConnectAsync().Wait(300)`, ~13ms), nunca
  `Test-NetConnection` (~7s por chamada).

**Dados**
- **Nunca atualizar o binário do Qdrant sem backup de `qdrant_data/`** — 1.17.1 →
  1.18.2 descartou ~666k vetores e reverter não os trouxe de volta.
- **Embedding único: BGE-M3 1024d via `:8001/embed`.** Trocar exige re-vetorizar tudo.
- Todo `PointStruct` tem `categoria` e `fonte` no payload (filtros dependem disso).
- IDs do Qdrant: `uuid.uuid5(uuid.NAMESPACE_URL, chave)` — determinístico e idempotente.
- Ingestão (SurrealDB) e vetorização (Qdrant) são desacopladas: comparar
  `SELECT count() FROM <tabela> GROUP ALL` com a contagem por categoria.
- Mudança de schema sempre aditiva; snapshot antes.

**SurrealDB**
- Paginação por cursor (`WHERE id > $cursor ORDER BY id LIMIT N`), nunca `LIMIT/START` (full scan).
- SDK v1.x: `query()` devolve lista direta — nunca `res[0].get("result")`.
- HTTP `/sql`: headers `surreal-ns`/`surreal-db` (não `NS`/`DB`).
- `ORDER BY` em campo que não está no `SELECT` → 400 (`Idiom missing here`).
- Record id vem escapado com crase (`sessao:\`uuid\``): escrever com
  `type::record("sessao", $id)`, nunca montando o id na mão.
- Tabela que nunca teve `CREATE` devolve status `ERR` com `result` = string, e
  `SurrealClient.result()` não distingue OK de ERR: checar `isinstance(dados[0], dict)`.
- Tabela `topico` não existe: tópicos são ids implícitos `topico:x` vindos de `sobre.out`.
- Credencial `root/root` aceita só porque o bind é local.

**Python no Windows**
- `import pyarrow` **antes** de `torch`/`qdrant_client`/`sentence_transformers` —
  senão access violation `0xc0000005` sem traceback.
- `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` logo após `import sys`
  em todo script que imprime unicode com saída redirecionada.
- Scripts com `sentence_transformers`: `log()` grava no arquivo antes de tentar `print()`.
- `pyttsx3.runAndWait()` trava o event loop — TTS async via subprocess.
- pywebview: `url=` com caminho absoluto; `SetProcessDPIAware()` antes de `GetSystemMetrics`.
- PowerShell 5.1 emite na codepage OEM (850): prefixar
  `$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8;` e
  escapar apóstrofo como `''`.

**Async e APIs**
- Chamada síncrona dentro de `async def` (RAG, tools, `httpx.post`) sempre via
  `await asyncio.to_thread(...)` — uvicorn tem um event loop só; bloquear trava tudo.
- Mensagens enviadas aos provedores: sanitizar para `{role, content}` — o Groq
  rejeita campos extras (`fontes_rag`, `divergencia_draft`).
- Usar a variável local da requisição (`msg.texto`), nunca `mensagens[-1]` do
  estado global (race entre `/chat` concorrentes).
- Clientes HTTP reutilizáveis (keep-alive) para health checks.

**Ambiente de desenvolvimento**
- Git Bash não enxerga processos Windows nativos — matar via PowerShell
  `Get-CimInstance … | Stop-Process` (ver README).
- `BASE_PATH=/ui-novo npm run build` no Git Bash quebra (MSYS converte o path) —
  usar PowerShell `$env:BASE_PATH = "/ui-novo"`.
- `ELECTRON_RUN_AS_NODE=1` herdado da sessão impede Electron de abrir janela —
  remover a variável e lançar `electron.exe` via PowerShell.
- BM25 é carregado com `mmap=True` no startup: rebuild com
  `build_bm25_index.py --novo` (grava em `bm25s_index_new/`) e trocar as pastas com
  o cérebro parado.
- `cargo` com antivírus: `CARGO_BUILD_JOBS=1` (evita `os error 32`).
- Editar arquivo não afeta o `cerebro_maestro.py` rodando; restart só quando pedido.

**GPU**
- Cérebro não carrega modelo de embedding (usa `:8001`). Vetorização em lote na GPU:
  `ENCODE_BATCH=32`, `MAX_SEQ_LEN=512`, checar VRAM com
  `torch.cuda.memory_allocated()` (não `memory_reserved()`). ~88k vetores/30min.
- `embed_service`: idle 600s estaciona o BGE-M3 na RAM (`.to('cpu')`, reativa em
  0.32s); reranker descarrega por completo.

## 3. Backend (`Lyra_Ollama/`)

### 3.1 Organização

| Módulo | Papel |
|---|---|
| `cerebro_maestro.py` | Entrypoint: estado compartilhado, CORS, mounts (`/ui`, `/ui-novo`, `/imagens`), wiring dos routers, MCP |
| `config.py` | Portas, URLs, model IDs, `AUTH_*` |
| `llm_cascade.py` | `LLMCascade` — streaming (`/chat`) e batch (`run()`, agentes) por provedor |
| `rag_engine.py` | `RAGEngine` — `search()`, `record_event()`, `search_graph()`, utilitários de texto |
| `session_manager.py` | `SessionManager` — histórico, sessão ativa, briefing, contador de turnos (com locks) |
| `proactive_loop.py` | `ProactiveLoop` — lembretes, agendamentos, processos bg, enxames, self-healing, shadow thoughts, reconciliação |
| `surreal_client.py`, `logger.py` | Cliente SurrealDB único; logger com `atexit` |
| `routers/` | `system`, `sessions`, `memory`, `agents`, `misc`, `chat`, `auth`, `gateway`, `tools`, `logs`, `models_hub`, `prompts` |
| `models/` | Schemas Pydantic por domínio |
| `utils/` | `auth.py` (`PasswordHasher`, `JWTManager`, `UserRepository`, `CurrentUserDependency`), `secrets.py` (`resolve_secret`, `mask_secret`) |
| `tools/` | 16 módulos por domínio + `_registry.py`/`_lazy.py`/`_shared.py`; `lyra_tools.py` é shim |

Nomes antigos → novos: globals de sessão → `SessionManager`; `buscar_hibrido`/
`registrar_evento`/`buscar_grafo_surreal` → métodos de `RAGEngine` (wrappers com o
nome antigo mantidos); `_stream_*` → wrappers sobre `LLMCascade`.

### 3.2 Cascata e roteamento

- Andares: Groq → Gemini → Claude (CLI, sem tool-calling nativo) → Ollama local.
  `modelo: auto|groq|gemini|claude|local` no `/chat` força um andar sem fallback.
- **MoE roteado:** lista declarativa `ESPECIALISTAS` — `codigo` (trigger por
  keywords) → `claude, groq, gemini, local`; `geral` (catch-all, sempre por último)
  → `groq, gemini, claude, local`. Novo especialista = nova entrada na lista.
- Loop de tool-calling compartilhado, `_MAX_ITERACOES_TOOLS = 25`.
- Roteador de ferramentas: `_TOOL_KEYWORDS_RE` (regex com `\b`, prefixo de palavra).
- Compressão de histórico: >14 mensagens → as 8 mais antigas viram sumário (lock).
- Session briefing no startup: últimas mensagens + resumo + objetivos em aberto +
  tópicos/ferramentas das últimas 24h (via grafo).
- Telemetria: `telemetria.json` (acumulado) + `telemetria_historico.jsonl`
  (snapshot a cada ~5min, últimas 2000 linhas).
- Ferramentas desligadas pelo usuário (`/tools/{nome}/toggle`): `set` em memória
  compartilhado por referência com o `ChatRouter`; lista vazia vira `None`.

### 3.3 API HTTP (:8000)

| Método | Rota | Descrição |
|---|---|---|
| GET | `/` | Ping `{servico, ativo, versao}` |
| GET | `/dashboard` | Dashboard HTML de monitoramento |
| GET | `/status` | Estado do cérebro (inclui `carga_cognitiva`, `tts_mudo`) |
| GET | `/health` | Latência de Qdrant/SurrealDB/Ollama/embedder + VRAM + contagem de vetores |
| GET | `/metrics` | CPU/RAM/GPU/VRAM + latência do último chat |
| GET | `/stats`, `/stats/historico?limite=` | Telemetria da cascata (acumulada / snapshots) |
| GET | `/integracoes` | Status de Telegram, Voice Live, mic, TTS, enxame, upload |
| POST | `/chat` | Chat SSE. Body `{texto, modelo}` |
| POST | `/tts/mudo`, `/tts/falar` | Voz global on/off; falar texto arbitrário |
| GET | `/buscar?q=&top_k=&categoria=` | Busca híbrida |
| GET | `/grafo?q=&limite=`, `/grafo/completo?limite=` | Traversal por keywords; grafo nodes+links |
| GET | `/memoria/categorias` | Composição da base por categoria |
| GET/DELETE | `/historico[?sessao=]` | Histórico (com `fontes_rag`/`divergencia_draft`); DELETE limpa só a RAM |
| GET | `/resumo_sessao`, `/exportar` | Briefing; exporta sessão em markdown |
| GET/POST | `/sessoes` | Lista (inclui `legado`) / cria sessão |
| POST | `/sessoes/ativar`, `/sessoes/{id}/favoritar` | Troca sessão; favorita |
| PATCH/DELETE | `/sessoes/{id}` | Renomeia / exclui |
| POST | `/upload` | Upload de imagem/áudio (filename sanitizado) |
| POST/GET | `/enxame`, `/enxames`, `/enxame/{id}`, `/enxame/{id}/consolidar` | Enxame de sub-agentes |
| POST/GET | `/agente`, `/agente/runs` | ReAct autônomo; execuções |
| POST | `/shadow_thoughts` | Dispara o ciclo de sono (background) |
| GET/POST | `/auth/status`, `/auth/setup`, `/auth/login`, `/auth/logout` | Auth mínimo |
| GET/POST | `/tools`, `/tools/{nome}/toggle` | Lista (58) / liga-desliga ferramenta |
| GET | `/logs?fonte=log\|err&linhas=N` | Últimas linhas de `maestro.log`/`.err` |
| GET/POST | `/ollama/models`, `/ollama/models/pull` | Modelos instalados; pull com progresso SSE |
| GET/POST/PATCH/DELETE | `/prompts`, `/prompts/{id}` | Biblioteca de prompts |
| WS | `/ws/voice` | Voice Live (Gemini Live) |
| WS | `/ws/gateway` | Gateway tipado `{action, payload}` (só leitura) |
| GET/POST | `/mcp` | Endpoints REST como ferramentas MCP (exclui `/chat`, `/dashboard`, `/upload`, `DELETE /historico`, `/tts/mudo` e destrutivos) |
| static | `/ui`, `/ui-novo`, `/imagens` | Build do v2, build do v3, imagens geradas |

`embed_service` (:8001): `GET /health` (inclui `estacionado_ram`), `POST /embed`
(`{texto|textos}`), `POST /rerank`, `POST /unload`.

### 3.4 Segurança em runtime

Todo dispatch de ferramenta passa por `_executar_tool_segura()`:

1. **Rate limit** (`lyra_seguranca.checar_rate_limit`, deque + lock): `executar_comando`
   20/5min · `iniciar_processo_bg` 5/5min · `escrever_arquivo` 30/60s ·
   `organizar_pasta` 3/5min · `criar_ferramenta` 5/10min ·
   `consultar_especialista` 3/10min · `navegar_web` 10/5min.
2. **Câmara de Eco Heurística** (`avaliar_risco_acao`, sem LLM): avalia só
   `executar_comando`/`iniciar_processo_bg` (deleção recursiva, `\bformat\s+[a-z]:`,
   `reg delete`, shutdown, `net user /delete`, kill forçado, download+execução,
   path de sistema + verbo destrutivo), `escrever_arquivo` (extensão executável ou
   fora dos diretórios de trabalho) e `organizar_pasta` (raiz de drive/sistema).
   Risco alto → `BLOQUEADO_RISCO`, grava hash SHA256 da ação exata. Aprovação só com
   frase de confirmação com verbo ("sim, executa mesmo assim"; nunca "sim" solto),
   **no turno imediatamente seguinte** (`_contador_turnos`) e dentro de 10min. Uso
   único. Quirk conhecido: Groq às vezes repete a mesma tool call → bloqueio
   "fantasma" que expira sozinho.
3. **Audit log** (`audit_log` no SurrealDB, buffer + thread de flush a cada 5s;
   `tool_filtro` validado por regex).
4. **Keyring** (Windows Credential Manager): migra só `GROQ_API_KEY`,
   `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`; demais chaves ficam
   no `.env`. `migrar_chaves_para_keyring()` fora do `TOOLS_MAP` (admin).
5. **Self-healing** no loop proativo a cada ~5min: SurrealDB, Qdrant, embed_service,
   Ollama (via `asyncio.to_thread`; não checa o próprio FastAPI).

CORS: `allow_origins=["null", "http://127.0.0.1:8000", "http://localhost:8000",
"http://127.0.0.1:5173"]`, `allow_credentials=False`. Consequência: `npm run dev` do
v3 não consegue logar (cookie) — testar via build servido em `/ui-novo`.

Auth: PBKDF2-SHA256 (stdlib, 260k iterações), JWT HS256, cookie httpOnly
`samesite=lax`, 30 dias, secret em `AUTH_JWT_SECRET`.

## 4. Memória e RAG

### 4.1 Base vetorial (`lyra_memory_v2`, ~3.09M pontos)

| Categoria | Pontos |
|---|---|
| `conhecimento_geral` (Wikipedia PT) | 1.112.246 |
| `conversa_geral` | 1.001.379 |
| `raciocinio_matematico` | 402.473 |
| `instrucao_ptbr` | 325.410 |
| `programacao` | 238.857 |
| `conhecimento_qa` | 6.828 |
| `referencia_database/frontend/webdev/llm` (docs curadas, `ingest_webdocs.py`) | 1.480 |
| `episodio` (conversas) | cresce em runtime |

Índice de payload `categoria: keyword` criado.

### 4.2 Busca híbrida (`RAGEngine.search`, `GET /buscar`)

BM25 (`bm25s`, índice em `bm25s_index/` + `bm25s_meta.pkl`) + denso (Qdrant) →
RRF → reranker cross-encoder → freshness. `score_final = relevância·0.94 +
freshness·0.06`, meia-vida por categoria: `programacao`/`documentacao` 180d,
`conhecimento_geral` 3650d, `raciocinio_matematico`/`episodio` sem penalidade.
Sem decaimento temporal genérico (removido — ver NUCLEO §4). `retrieval_count` e
`last_accessed_at` continuam gravados, fora do ranking. `top_k` ajustado por
carga cognitiva (alta −2, baixa +2). Se o embed_service cair, só BM25.
Latência `/buscar` quente ~630-660ms.

### 4.3 Grafo (SurrealDB)

`record_event()` grava o evento no SurrealDB e no Qdrant (não atômico) e cria
`RELATE evento->precedeu->evento` e `RELATE evento->sobre->topico:keyword`.
`search_graph()` faz traversal `<-sobre<-evento`. `/grafo/completo` filtra links
órfãos antes de responder (link para nó fora da janela `limite` derrubava o
3d-force-graph).

### 4.4 Shadow Thoughts (`lyra_shadow_thoughts.py`)

A cada ~3h (180 iterações do loop) ou `POST /shadow_thoughts`. NREM: dedup só em
`categoria=episodio`, paginado por cursor; marca `duplicado=True`. REM: arestas
cross-domain via grafo. DEEP: resume eventos com mais de 4 semanas. 1ª execução:
28 duplicatas, 2.5s.

### 4.5 Innovations (01/07)

1. **Goal Drift Detector** — `classify_intent` (`objetivo|conclusao|passo|resposta`),
   gravado no evento; objetivos em aberto entram no briefing.
2. **Freshness Tags** — §4.2.
3. **Session Replay** — tópicos dominantes + ferramentas das últimas 24h no briefing.
4. **Cognitive Load Throttling** — `baixa|media|alta` por latência e % de uso do local.
5. **Response Provenance** — IDs Qdrant das fontes em `fontes_rag` (histórico, SurrealDB, payload). Sem UI.

### 4.6 Speculative Decoding (sidecar)

Draft `qwen3:0.6b` (`keep_alive=300` — com `0` cada `/chat` pagava ~10s de reload)
roda em paralelo à cascata, só quando a pergunta não aciona ferramentas, com
`_SYSTEM_PROMPT_DRAFT` próprio (sempre arrisca palpite). `divergencia_draft = 1 −
cos(emb_final, emb_draft)`; acima de 0.45 loga alerta. Mede divergência de
**tópico**, não de fato ("Paris" vs "Lyon" = 0.13).

### 4.7 Reconciliação SurrealDB ↔ Qdrant

`reconciliar_episodios.py` (CLI ou `silencioso=True`) re-embeda eventos sem vetor.
Roda sozinho a cada ~1h no loop proativo; só loga se achar órfãos.

### 4.8 Datasets ingeridos

Schema: `{titulo, texto (≤3000), fonte, categoria}`. Reconstrução do zero em
`Lyra_Core/Memoria_Lyra/Scripts_Ingestao/`: `ingestao.py` (SurrealDB) +
`fix_faquad_brquad.py` (FaQuAD/br-quad, contorna o bloqueio da lib `datasets`) →
`vetorizar_bge_m3.py` (Qdrant). `ingest_webdocs.py` para docs curadas.

| Tabela | Datasets |
|---|---|
| `wiki_conhecimento` | wikimedia/wikipedia 20231101.pt (1.11M artigos) |
| `base_codigo` | Evol-Instruct-Code-80k, code_instructions_120k_alpaca, CodeAlpaca-20k, python_code_instructions_18k |
| `base_instrucoes_ptbr` | Canarim-Instruct-PTBR, aya_dataset (por) |
| `base_raciocinio` | gsm8k, MetaMathQA |
| `base_conversas` | OpenHermes-2.5 |
| `base_conhecimento_qa` | br-quad-2.0, faquad |
| `base_medicina_ptbr` | AKCIT/MedPT (384k pares) |

### 4.9 Validação do RAG

`validador_cortical.py`: gera perguntas sintéticas de eventos e mede Hit Rate/MRR
(precisa `_init()` explícito do cérebro e `think=False` no qwen3). **Baseline
oficial (n=100, 01/07): HR 10.0%, MRR 0.057.** Número baixo é limitação da
metodologia (exige o episódio exato contra 3M docs, e a wiki ganha). Próximo
passo: medir por categoria.

## 5. Agentes

**Enxame (`lyra_agentes.py`)** — tarefa → N subtarefas em paralelo
(`asyncio.Semaphore`, `max_paralelo=2` default, nunca >3; timeout 120s por
subtarefa; recusa com GPU >85% ou VRAM livre <1.5GB). Tabelas `enxame` e
`subtarefa` (`pendente|rodando|concluida|erro`). Denylist `TOOLS_BLOQUEADAS`:
execução de comando, escrita, `criar_ferramenta`, processos bg, agendamentos,
`salvar_memoria`, notificações, `consultar_especialista`, `*_enxame`. Loop proativo
consolida e notifica enxames concluídos.

**ReAct (`lyra_agent.py`)** — `executar_agente(objetivo, max_iteracoes,
ferramentas_bloqueadas)` via `LLMCascade.run()`, mesma denylist, persiste em
`agente_run`. `--self-test` (3 casos) passa nos 3 andares, incluindo o local.

## 6. Voz, visão e integrações

- **Wake-word** (`mic_engine.py`): "lyra" → Silero VAD → faster-whisper → `/chat`.
- **Voice Live** (`lyra_voice_live.py`, `/ws/voice`): modelo
  `gemini-2.5-flash-native-audio-latest`, `response_modalities=["AUDIO"]` (uma
  modalidade só) + `output_audio_transcription`. Protocolo: PCM16 16kHz mono →
  servidor; PCM16 24kHz mono ← servidor; JSON texto/done/erro.
- **TTS** (`audio_manager.py`): Gemini `gemini-2.5-flash-preview-tts` voz Leda
  (free tier 3 req/min, ~4s/frase) → edge-tts Francisca → silêncio. Pipeline
  automático pausado.
- **Visão:** Gemini Vision → fallback `llava-phi3` (falha do Gemini é logada).
  `moondream` descartado.
- **`navegar_web`** (`lyra_browser.py`): browser-use 0.13.1 com
  `browser_use.llm.google.chat.ChatGoogle` (`gemini-2.5-flash`; o 2.0 tem quota zero).
- **Telegram** (`lyra_telegram.py`): consome `/chat` via SSE; default-deny sem allowlist.
- **Google Workspace** (`lyra_google_workspace.py`): Gmail + Calendar via OAuth2.
- **`gerar_imagem`**: Pollinations.ai (Flux, sem key).
- **Clima**: wttr.in (default Marília-SP).

## 7. Frontends

### 7.1 v1 — pywebview + Three.js (produção)

`Lyra_Core/Front_end_Lyra/` (`index.html`, `script.js`, `style.css`, `ui.js`,
`ui.css`, `vendor/`). Esfera de partículas reativa ao estado
(idle/ouvindo/processando/falando), sidebar com views (início/chat/memória/
integrações/configurações), sessões, grafo de memória 3D (`3d-force-graph 1.73.4` +
Three.js r128, links órfãos filtrados), voz live, drag & drop, histórico ↑/↓.
**100% offline:** three.js, 3d-force-graph e Inter vendorizados. Tokens: `--neon
#00DDFF`, `--danger #FF4466`, Inter 200/300/500, sentence case,
`prefers-reduced-motion` respeitado. `-webkit-app-region: no-drag` obrigatório abaixo
da faixa de arraste (52px).

### 7.2 v2 — React + Vite + TS (`/ui`)

`Lyra_Core/Front_end_Lyra_v2/`, build com `base: '/ui/'`, servido same-origin.
Chat SSE com stop/retry/copiar, markdown sanitizado (DOMPurify), sessões, busca,
settings em 7 abas, anexo, atalhos `Ctrl+K`/`Ctrl+Shift+O`. Dark-only, sem CDN.
Usado pela IDE e pelo Lyra Desktop até o cutover.

### 7.3 v3 — SvelteKit (Lyra 2.0)

`Lyra_Core/Front_end_Lyra_v3/`, Svelte 5 runes, `adapter-static` (SPA,
`fallback: 'index.html'`, `ssr = false`). `vite.config.ts`: `paths.base =
process.env.BASE_PATH ?? ''` — build canônico sem base; preview com
`BASE_PATH=/ui-novo`.

| Arquivo | Papel |
|---|---|
| `lib/api.ts` | fetch com `credentials: 'include'`; `streamChat()` lê o SSE do `POST /chat` na mão |
| `lib/shell.ts` | Contrato `LyraShell` + `BrowserShell`/`TheiaShell`/`TauriShell` |
| `lib/settings.svelte.ts` | Preferências em `localStorage` (mesmas chaves do v2). Rune `$state` só funciona em `.svelte`/`.svelte.ts` — `svelte-check` e build não pegam isso |
| `lib/voiceLive.ts` | `VoiceLiveSession` (getUserMedia + ScriptProcessorNode, resample 16kHz, fila de playback) |
| `components/Chat.svelte`, `Sidebar.svelte`, `MessageContent.svelte` | Chat, sessões, preview de artifacts |
| `components/SettingsModal.svelte`, `SearchOverlay.svelte`, `SystemPanel.svelte` | Configurações, busca, monitor/logs/tools |
| `components/GraphPanel.svelte` | Força em Canvas 2D: `alpha` decai ×0.985 e para <0.01; velocidade limitada a 8px/frame |
| `components/Orb.svelte` | 64 pontos Fibonacci, 3 vizinhos ligados, cor esmaece com a profundidade; congela com "reduzir movimento" |
| `components/ModelHubPanel.svelte`, `PromptLibraryPanel.svelte` | Hub Ollama; biblioteca de prompts |
| `styles/tokens.css` | `--bg #0b0b0d`, `--accent #4fc3d9`; `[data-reduce-motion="1"]` desliga animações |

Atalhos: `Ctrl+K` busca, `Ctrl+Shift+O` nova conversa, `Esc` fecha o painel mais recente.

### 7.4 Tauri (`Front_end_Lyra_v3/src-tauri/`)

4 comandos Rust (`get_secret`, `set_setting`, `start_backend`, `open_ide`);
settings/segredos em JSON no diretório de config do app. `cargo check`/`clippy`
limpos. Ícones placeholder na paleta do v3.

### 7.5 Lyra Desktop (`Lyra_Core/Lyra_Desktop/`)

Electron puro (`main.js`) reaproveitando o Electron da IDE; carrega `/ui/`, sem menu
bar, single-instance, `setWindowOpenHandler` nega `window.open`/`_blank`.

## 8. Lyra IDE (Eclipse Theia)

Local: `Lyra_Core/Lyra_IDE/` (fork do Theia Blueprint, repo git próprio, fora deste
repo). Node **22.14.0 portátil** em `.toolchain/node22` (o Node do sistema é 24).

- **Build nativo no Windows:** exige VS Build Tools (workload C++) +
  `Microsoft.VisualStudio.Component.VC.Runtimes.x86.x64.Spectre` (MSB8040).
- `@theia/ffmpeg` neutralizado via `patches/@theia+ffmpeg+1.74.1.patch`
  (inclui skip do `checkFfmpeg`), reaplicado no `postinstall`.
- `@vscode/windows-ca-certs`: stub manual em `node_modules` (classe `Crypt32` vazia
  + `build/Release/crypt32.node` vazio). **Não persistente** — recriar após reinstalar.
- Fluxo: `yarn build:extensions` → `yarn build` (browser ou electron). Plugins:
  `yarn download:plugins` (97 extensões via Open VSX).
- **Branding:** ícone oficial = estrela de 4 pontas cyan (`Front_end_Lyra/lyra.ico`,
  não o raio do favicon antigo do v2); wordmark "LYRA IDE"; splash; Inter vendorizada
  via `--theia-ui-font-family`; tema "Default Dark Modern" editado para Lyra Dark
  (`#00DDFF` sobre preto) dentro de `plugins/` (**some** num `download:plugins` limpo);
  update-checker desligado; ícone da janela setado em runtime também no `win32`
  (`icon-contribution.ts`); `productName` LyraIDE, `appId` `com.lyra.ide`.
- **Painel Lyra:** extensão `theia-extensions/lyra-chat/` — `LyraChatWidget` com
  iframe para `http://127.0.0.1:8000/ui/?shell=theia`, comando "View: Toggle Lyra".
- O Theia Blueprint já traz `@theia/ai-*` (chat, code-completion, MCP, providers
  Anthropic/Ollama/…): candidato a plugar a Lyra como provider.

## 9. Avaliações registradas

- **SurrealDB 3.0 vetorial (HNSW/DISKANN) vs Qdrant — não migrar:** índice quente em
  RAM estimado em 15-20GB para 3.08M×1024, reescrita do RAG, Qdrant estável. Se
  revisitar, testar numa coleção pequena (`episodio`).
- **Mem0/Kore — não adotar:** Kore é conceitualmente o que a Lyra já faz; a resolução
  de conflitos por LLM do Mem0 é problema do REM do Shadow Thoughts.
- **A2A — não adotar:** resolve interoperabilidade entre fornecedores; ideias
  reaproveitáveis: estado `input-required` e capacidades declaradas (já refletidas em
  `ESPECIALISTAS`).
- **C++/Rust no backend — não faz sentido:** partes pesadas já são nativas (Ollama,
  Qdrant, SurrealDB); gargalo é modelo/VRAM.
- **Modelos de referência (8GB VRAM):** `qwen3:8b` segue o melhor local da faixa;
  Qwen3-VL-7B candidato a VLM local; SmolVLM 2B e MiniCPM-V 2.6 como alternativas;
  vídeo só LTX-2 FP8 (não simultâneo ao LLM); áudio MusicGen Small/AudioLDM2.
  Groq deprecou `llama-3.x` em 17/06/2026 — cascata já usa `gpt-oss-120b`.
