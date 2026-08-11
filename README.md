# Lyra

IA pessoal local — identidade feminina, técnica, não-servil. Roda no PC do Antônio
(Ryzen 7 3700X · RTX 2060 Super 8GB · 64GB RAM), sem Docker, no Windows.

> Documentação viva em `Memorias Do Projeto/`:
> [LYRA_NUCLEO](Memorias%20Do%20Projeto/LYRA_NUCLEO.md) ·
> [LYRA_TECNICO](Memorias%20Do%20Projeto/LYRA_TECNICO.md) ·
> [LYRA_AGENTES_E_PLANOS](Memorias%20Do%20Projeto/LYRA_AGENTES_E_PLANOS.md)

---

## Arquitetura

```
 ┌─────────────────────────────────────────────────────────────┐
 │  Frontend (pywebview, Three.js)  ──ws:8765──┐                │
 │  Lyra_Core/Front_end_Lyra/                   │                │
 └──────────────────────────────────────────────┼───────────────┘
                                                 │ HTTP :8000
 ┌───────────────────────────────────────────────▼──────────────┐
 │  cerebro_maestro.py  (FastAPI :8000)                          │
 │   • Cascata: Groq → Gemini → Claude(CLI) → qwen3:8b local     │
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

> **Importante (Windows):** todas as chamadas internas entre serviços usam `127.0.0.1`, nunca `localhost` — o resolver IPv6 do `localhost` adiciona ~2s por chamada.

---

## Como subir

Os serviços têm `.bat` em `bin/startup/` (sobem só se a porta estiver livre):

```bat
bin\startup\start_qdrant.bat
bin\startup\start_surreal.bat
bin\startup\start_ollama.bat
bin\startup\start_embed.bat     :: embed_service BGE-M3 + reranker :8001
bin\startup\start_cerebro.bat   :: espera 6333/8090/11434/8001 e sobe o FastAPI
```

No boot do Windows, `bin/startup/lyra_boot.vbs` (atalho em Startup) sobe qdrant + surreal + embed + cerebro; o Ollama tem atalho próprio.

Frontend desktop:

```
python Lyra_Core/Front_end_Lyra/lyra_app.py
```

## Dependências

```
python -m pip install -r requirements.txt            # Python principal (3.12) — inclui torch 2.6+cu124 (bge-m3)
```

> `venv_embed` foi aposentado em 01/07/2026 — o `embed_service.py` (BGE-M3) roda no mesmo Python principal agora, não mais num venv isolado.

`.env` na raiz do `Lyra_Ollama/` — copie de `.env.example` e preencha:
- `GROQ_API_KEY`, `GEMINI_API_KEY` — obrigatórias pra cascata de chat.
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS` — opcionais, só pro bot Telegram (`lyra_telegram.py`).

Claude usa o CLI `claude` no PATH (sem key extra).

## Testes

```
python Lyra_Ollama/test_smoke.py            # valida todos os endpoints
python Lyra_Ollama/test_smoke.py --rapido   # pula o teste de chat (mais rápido)
python Lyra_Ollama/validador_cortical.py    # Hit Rate / MRR do RAG (baseline em LYRA_TECNICO.md)
```

## Dashboard de monitoramento

Com o cérebro no ar, abra no navegador: **http://localhost:8000/dashboard**
Mostra ao vivo: serviços (latência), CPU/RAM/GPU/VRAM, contagem de vetores e
telemetria da cascata (qual modelo respondeu mais, latência, taxa de sucesso).

---

## Layout

```
Lyra_Ollama/               # backend — orquestrador, RAG, agentes, integrações
  cerebro_maestro.py         # orquestrador FastAPI :8000 — cascata, RAG, telemetria, todos os endpoints
  embed_service.py           # microserviço BGE-M3 :8001 (embedding 1024d + reranker)
  lyra_tools.py               # ferramentas (function-calling): arquivo, web, mídia, memória, auto-extensão...
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
Lyra_Core/                 # frontend, voz, sentidos, memória bruta
  Front_end_Lyra/             # pywebview + Three.js (index.html, script.js, style.css, lyra_app.py)
  audio_manager.py            # TTS (edge-tts Francisca) — pipeline pausado por decisão do usuário
  mic_engine.py               # STT (faster-whisper + Silero VAD)
  webcam.py                   # visão via webcam
  commands.py                 # comandos locais por voz
  google_auth/                # credentials.json / token.json (OAuth2, gerado localmente)
  Sons/cache/                 # cache de áudio TTS + capturas de tela
  Memoria_Lyra/
    db_cortex/                  # dados do SurrealDB (não mexer manualmente)
    Scripts_Ingestao/           # ingestão + vetorização dos datasets (pipeline_noturno.sh)
    backups/                    # snapshots de segurança pré-migração
    Documentos/                  # documentação gerada (PDFs)
bin/                        # binários (qdrant.exe) + startup/*.bat + logs de boot
Memorias Do Projeto/        # documentação canônica do projeto (NUCLEO/TECNICO/AGENTES_E_PLANOS)
```

---

## Pilares (Ring 0)

1. Antônio é o Administrador Supremo.
2. Auto-modificação de código exige aprovação explícita.
3. Offline por padrão — exceção consciente: cascata cloud (Groq/Gemini/Claude) para chat, aprovada em 25/06/2026.

Detalhes em [LYRA_NUCLEO](Memorias%20Do%20Projeto/LYRA_NUCLEO.md).
