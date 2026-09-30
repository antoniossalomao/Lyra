# Lyra

IA pessoal local — identidade feminina, técnica, não-servil. Roda no PC do
Antônio (Ryzen 7 3700X · RTX 2060 Super 8GB · 64GB RAM), sem Docker, no
Windows.

> **Licença:** projeto proprietário, todos os direitos reservados — ver
> [LICENSE](LICENSE). Público como portfólio, não como software livre.

> Documentação viva em `Memorias Do Projeto/`:
> [LYRA_NUCLEO](Memorias%20Do%20Projeto/LYRA_NUCLEO.md) ·
> [LYRA_TECNICO](Memorias%20Do%20Projeto/LYRA_TECNICO.md) ·
> [LYRA_AGENTES_E_PLANOS](Memorias%20Do%20Projeto/LYRA_AGENTES_E_PLANOS.md) ·
> [LYRA_IDE_PLANO](Memorias%20Do%20Projeto/LYRA_IDE_PLANO.md)

---

## Arquitetura

```
 ┌─────────────────────────────────────────────────────────────┐
 │  Frontends (ver tabela "Frontends")  ──ws:8765 / HTTP──┐     │
 │  v1 pywebview · v2 React (/ui) · v3 Svelte (/ui-novo)  │     │
 └──────────────────────────────────────────────┼───────────────┘
                                                 │ HTTP :8000
 ┌───────────────────────────────────────────────▼──────────────┐
 │  cerebro_maestro.py  (FastAPI :8000)                          │
 │   • Cascata cloud-first: Groq → Gemini → Claude(CLI) → qwen3  │
 │   • RAG híbrido: BM25 + Qdrant denso + RRF + recência         │
 │   • Grafo de memória (SurrealDB RELATE)                       │
 │   • Telemetria, health, enxame de sub-agentes                 │
 └───┬──────────────┬───────────────┬───────────────┬───────────┘
     │              │               │               │
 ┌───▼───┐   ┌──────▼─────┐   ┌─────▼─────┐   ┌─────▼──────┐
 │Qdrant │   │ SurrealDB  │   │  Ollama   │   │ APIs cloud │
 │ :6333 │   │  :8090     │   │  :11434   │   │ Groq/Gemini│
 │vetores│   │ episódico  │   │ qwen3:8b  │   │  /Claude   │
 └───────┘   └────────────┘   └───────────┘   └────────────┘
```

| Serviço | Porta | Papel |
|---------|-------|-------|
| cerebro_maestro (FastAPI) | 8000 | Orquestrador, cascata, RAG, endpoints, MCP (`/mcp`) |
| embed_service (FastAPI) | 8001 | Embedding BGE-M3 1024d + reranker bge-reranker-v2-m3. O cérebro depende dele. |
| ws hub (lyra_app) | 8765 | Ponte frontend ↔ cérebro |
| Qdrant | 6333 | Vetores (`lyra_memory_v2`, BGE-M3 1024d) |
| SurrealDB | 8090 | Memória episódica + grafo (ns `lyra_core`, db `Db_CORTEX`) |
| Ollama | 11434 | qwen3:8b local (último andar da cascata) |

> **Cascata cloud-first:** o chat tenta Groq, Gemini e Claude antes do
> `qwen3:8b` local — o local só responde se os três falharem. Sem as chaves
> de API, a Lyra funciona 100% offline (só o último andar).

> **Importante (Windows):** todas as chamadas internas entre serviços usam
> `127.0.0.1`, nunca `localhost` — o resolver IPv6 do `localhost` adiciona
> ~2s por chamada.

---

## Requisitos

- Windows 10/11, Python 3.12
- GPU NVIDIA com CUDA 12.4 (BGE-M3 + reranker rodam na GPU)
- Ollama instalado (`qwen3:8b` puxado localmente)
- CLI `claude` no PATH (cascata usa Claude via CLI, sem key extra)
- Chaves `GROQ_API_KEY` e `GEMINI_API_KEY` (cascata de chat)

## Como subir

Os serviços têm `.bat` em `bin/startup/` (sobem só se a porta estiver livre):

```bat
bin\startup\start_qdrant.bat
bin\startup\start_surreal.bat
bin\startup\start_ollama.bat
bin\startup\start_embed.bat     :: embed_service BGE-M3 + reranker :8001
bin\startup\start_cerebro.bat   :: espera 6333/8090/11434/8001 e sobe o FastAPI
```

No boot do Windows, `bin/startup/lyra_boot.vbs` (atalho em Startup) sobe
qdrant + surreal + embed + cerebro; o Ollama tem atalho próprio.

## Frontends

| Pasta | Stack | Como abre | Estado |
|-------|-------|-----------|--------|
| `Lyra_Core/Front_end_Lyra/` | pywebview + Three.js | `python Lyra_Core/Front_end_Lyra/lyra_app.py` (hub WS :8765) | v1, produção |
| `Lyra_Core/Front_end_Lyra_v2/` | React + Vite + TS | `npm run build` → servido pelo backend em `http://127.0.0.1:8000/ui/` | usado pela IDE (Theia) e pelo `Lyra_Desktop` |
| `Lyra_Core/Front_end_Lyra_v3/` | SvelteKit + Tauri 2 | `npm run build` → `http://127.0.0.1:8000/ui-novo/`; casca nativa em `src-tauri/` | Lyra 2.0 — login, chat, grafo, hub de modelos. Cutover pendente |
| `Lyra_Core/Lyra_Desktop/` | Electron puro | `npx electron .` — carrega `/ui/` | casca desktop do v2 |

`Lyra_Core/Lyra_IDE/` (Eclipse Theia) é um repo git próprio e fica fora
deste repositório. Andamento do Lyra 2.0: [PROGRESSAO_LYRAV2.md](PROGRESSAO_LYRAV2.md)
(plano em [PLANEJAMENTO_LYRA2.0.md](PLANEJAMENTO_LYRA2.0.md)).

## Dependências

```
python -m pip install -r requirements.txt   # Python principal (3.12) — inclui torch 2.6+cu124 (bge-m3)
```

> `venv_embed` foi aposentado em 01/07/2026 — o `embed_service.py` (BGE-M3)
> roda no mesmo Python principal agora, não mais num venv isolado.

`.env` na raiz do `Lyra_Ollama/` — copie de `.env.example` e preencha:
- `GROQ_API_KEY`, `GEMINI_API_KEY` — obrigatórias pra cascata de chat.
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS` — opcionais, só pro bot
  Telegram (`lyra_telegram.py`).

## Segurança — estado atual

- Todos os serviços escutam só em `127.0.0.1`.
- **Auth:** backend pronto (`routers/auth.py`, PBKDF2-SHA256 + JWT em cookie httpOnly), mas
  **as rotas ainda não exigem login** — gating só depois do cutover pro v3.
- **CORS** aceita a origem `"null"` (necessária pro pywebview do v1). Toda
  página com iframe sandboxed também manda `Origin: null`, então hoje um site
  aberto no navegador consegue falar com `/chat`. Corrigir junto com o gating
  de auth.
- **`/mcp`** expõe os endpoints REST como ferramentas MCP, sem autenticação.
- `executar_comando` roda PowerShell arbitrário; a contenção é rate limit
  (`lyra_seguranca.py`) + Câmara de Eco (confirmação no chat pra ações de
  alto risco).

Reporte de falhas: [SECURITY.md](SECURITY.md).

## Testes

```
python Lyra_Ollama/test_smoke.py            # valida todos os endpoints
python Lyra_Ollama/test_smoke.py --rapido   # pula o teste de chat (mais rápido)
python Lyra_Ollama/validador_cortical.py    # Hit Rate / MRR do RAG (baseline em LYRA_TECNICO.md)
```

Os dois precisam dos serviços no ar (Qdrant, SurrealDB, Ollama, embed,
cérebro). Não há testes unitários isolados nem CI.

## Dashboard de monitoramento

Com o cérebro no ar, abra no navegador: **http://localhost:8000/dashboard**
Mostra ao vivo: serviços (latência), CPU/RAM/GPU/VRAM, contagem de vetores e
telemetria da cascata (qual modelo respondeu mais, latência, taxa de
sucesso).

---

## Layout

```
Lyra_Ollama/               # backend — orquestrador, RAG, agentes, integrações
  cerebro_maestro.py         # orquestrador FastAPI :8000 — cascata, RAG, telemetria, todos os endpoints
  embed_service.py           # microserviço BGE-M3 :8001 (embedding 1024d + reranker)
  lyra_tools.py                # shim — re-exporta TOOLS_MAP/TOOLS_SCHEMA de tools/
  tools/                       # ferramentas (function-calling) por domínio: fs, web, os, git, memória, visão...
  llm_cascade.py               # cascata Groq → Gemini → Claude(CLI) → Ollama
  rag_engine.py                # RAG híbrido (BM25 + denso + RRF + reranker)
  surreal_client.py / session_manager.py   # SurrealDB e sessões de chat
  lyra_agent.py                # loop ReAct autônomo (POST /agente)
  lyra_agentes.py              # enxame de sub-agentes paralelos (POST /enxame)
  lyra_shadow_thoughts.py      # ciclo de sono NREM/REM/DEEP (dedup, grafo, compressão)
  lyra_seguranca.py            # sandboxing de comandos, gestão de chaves
  lyra_browser.py              # navegar_web — Playwright controlado por IA
  lyra_google_workspace.py     # Gmail + Google Calendar (OAuth2)
  lyra_telegram.py             # bot Telegram bidirecional
  lyra_voice_live.py           # Voice Live — Gemini Live API (/ws/voice)
  bm25_index.py / build_bm25_index.py   # índice BM25 esparso (bm25s) + fusão RRF
  reconciliar_episodios.py     # reconcilia gaps SurrealDB ↔ Qdrant
  validador_cortical.py        # Hit Rate / MRR do RAG (baseline)
  calibrar_pesos_rag.py        # calibração de pesos do RRF
  test_smoke.py                # suite de smoke test (todos os endpoints)
  routers/ · models/ · utils/  # FastAPI modularizado (routers por domínio, schemas Pydantic, auth, segredos)
Lyra_Core/                 # frontend, voz, sentidos, memória bruta
  Front_end_Lyra/             # v1 — pywebview + Three.js (produção)
  Front_end_Lyra_v2/          # v2 — React + Vite, servido em /ui
  Front_end_Lyra_v2_mockups/  # mockups HTML do v2
  Front_end_Lyra_v3/          # v3 — SvelteKit + Tauri, servido em /ui-novo (Lyra 2.0)
  Lyra_Desktop/               # casca Electron que carrega /ui
  audio_manager.py            # TTS (edge-tts Francisca) — pipeline pausado por decisão do usuário
  mic_engine.py               # STT (faster-whisper + Silero VAD)
  webcam.py                   # visão via webcam
  commands.py                 # comandos locais por voz
  google_auth/                # credentials.json / token.json (OAuth2, gerado localmente)
  Sons/cache/                 # runtime (fora do git): cache TTS, screenshots, uploads, imagens
  Memoria_Lyra/
    db_cortex/                  # dados do SurrealDB (não mexer manualmente)
    Scripts_Ingestao/           # ingestão + vetorização dos datasets (pipeline_noturno.sh; checkpoint_*.json fora do git)
    backups/                    # snapshots de segurança pré-migração
    Documentos/                  # documentação gerada (PDFs)
bin/                        # binários locais + startup/*.bat + logs de boot
Memorias Do Projeto/        # documentação canônica do projeto (NUCLEO/TECNICO/AGENTES_E_PLANOS/IDE/ESTADO_ATUAL)
```

**Fora do git (gerado em runtime):** `Lyra_Core/Sons/cache/`,
`Lyra_Ollama/telemetria*.json*`, `Lyra_Ollama/lyra_tools_ext/` (ferramentas
auto-criadas), checkpoints de ingestão, `.env`, credenciais OAuth,
`qdrant_data/`, `db_cortex/`, `.claude/settings.local.json`. Os serviços
recriam as pastas no start.

---

## Pilares (Ring 0)

1. Antônio é o Administrador Supremo.
2. Auto-modificação de código exige aprovação explícita.
3. Offline por padrão — exceção consciente: cascata cloud
   (Groq/Gemini/Claude) para chat, aprovada em 25/06/2026.

Detalhes em [LYRA_NUCLEO](Memorias%20Do%20Projeto/LYRA_NUCLEO.md).

---

## Licença

Proprietário — todos os direitos reservados. Ver [LICENSE](LICENSE). Uso,
cópia ou redistribuição exigem autorização prévia por escrito.

Segurança: ver [SECURITY.md](SECURITY.md). Contribuição: ver
[CONTRIBUTING.md](CONTRIBUTING.md).
