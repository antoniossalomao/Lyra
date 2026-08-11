# LYRA — NÚCLEO DO PROJETO
> Consolidado em 22/06/2026. Atualizado em 30/06/2026.

---

## 1. Quem é o arquiteto

Antônio — estudante de ADS na UNIMAR (Marília-SP). Arquiteto único do projeto Lyra (IA pessoal local). Entendimento técnico sólido, prefere explicações diretas e sem enrolação. Treina bateria, frequenta academia.

- **Hardware:** Ryzen 7 3700X | RTX 2060 SUPER 8GB VRAM | 64GB RAM | 2.73TB HD
- **Email:** antonio.assuino.salomao@gmail.com

---

## 2. O que é a Lyra

IA pessoal local, identidade feminina, voz suave/técnica/clínica, não-servil. Não é um chatbot — é pensada como organismo cognitivo: hardware como corpo, modelos como córtex, SurrealDB+Qdrant como memória.

## 3. Ring 0 — Princípios Invioláveis

1. **Antônio é o Administrador Supremo.** Protocolo de Sobrescrita (voz ou terminal) anula qualquer raciocínio da máquina.
2. **`core.py` é somente leitura.**
3. **100% offline.** Zero envio de biometria, áudio, tela ou código para nuvem sem aprovação explícita. **Exceções conscientes já aprovadas:** cascata de modelos cloud (Groq→Gemini→Claude→local) para toda mensagem padrão desde 25/06/2026; TTS pode ser online; `consultar_especialista(nivel="cloud")` delega pro Claude Code (Sonnet, full agent) sem aprovação por ação.
4. **Hardware-Bound Logic Gates.** Telemetria da placa-mãe/RTX/RAM funciona como chave física — HD clonado para outro PC recusa iniciar.
5. **Toda auto-modificação de código requer aprovação explícita de Antônio** antes de entrar em produção.
6. **Ações de execução de alto risco** (deleção em massa, formatação, desligamento do sistema, etc.) **exigem confirmação explícita no chat antes de rodar** — trava automática via Câmara de Eco Heurística (seção 4.4), não é uma diretiva nova formal, é a aplicação em runtime do mesmo espírito do princípio 1.

---

## 4. Arquitetura de Cognição e Memória

### 4.1 Camadas de memória

| Camada | Tecnologia | Função |
|---|---|---|
| RAM (volátil) | Contexto do LLM + cache quente (últimas msgs) | Working memory |
| Qdrant (vetores) | BAAI/bge-m3, 1024 dims (`lyra_memory_v2`), via embed_service :8001 | Memória semântica |
| SurrealDB (grafos+docs) | Tabelas + relações `->` | Memória episódica/temporal |
| Cold storage | Arquivos comprimidos em disco | Memória arquivada |

Base atual: ~3.27M registros no SurrealDB somando todas as tabelas. Funil de Eventos no `cerebro_maestro.py` intercepta toda mensagem, gera timestamp, grava no SurrealDB (log cronológico) e no Qdrant (vetor pesquisável); últimas 10 msgs ficam em RAM.

### 4.2 Shadow Thoughts — Ciclo de Sono (✅ IMPLEMENTADO, 01/07/2026)
Baseado em SCM/MyGO/LightMem, em `lyra_shadow_thoughts.py`, agendado automaticamente a cada 3h no `loop_proativo` (`POST /shadow_thoughts` pra disparo manual):
- **WAKE:** registra episódios novos (`tag new_memory`)
- **NREM:** dedup/compressão de memórias semelhantes — primeira execução real encontrou 28 duplicatas
- **REM:** cruza informações desconexas via grafo, ex: `RELATE wiki_conhecimento:uml -> inspira -> base_codigo:design_pattern`
- **DEEP SLEEP:** auto-destilação — comprime logs antigos em "arquivos de sabedoria", libera espaço

Detalhes técnicos e histórico de execução em `LYRA_TECNICO.md` seções "lyra_shadow_thoughts.py" e 10.11.

### 4.3 Memória em grafos nativos (SurrealDB)
**Status real (26/06/2026):** grafo IMPLEMENTADO. `_grafo_salvar_relacoes()` cria, a cada evento, arestas `RELATE evento -> precedeu -> evento` (threading cronológico) e `RELATE evento -> sobre -> topico:keyword` (indexação por tópico via `_extrair_keywords`). `buscar_grafo_surreal()` faz traversal `<-sobre<-evento` e complementa o RAG vetorial em perguntas de memória. Exposto em `GET /grafo`. Próximo passo: relações semânticas mais ricas (Shadow Thoughts / REM, seção 4.2).

### 4.4 Outros mecanismos cognitivos (mistura de implementado e planejado)
- **Enxame de sub-agentes paralelos (`lyra_agentes.py`) — ✅ IMPLEMENTADO** (correção 30/06/2026: estava listado abaixo como "MoE roteado" planejado, descrição errada de algo que já existe). Decompõe uma tarefa em N sub-tarefas, roda em paralelo via `asyncio.Semaphore`, consolida via LLM. Ver detalhes completos em [[lyra_stack_ferramentas]] / `LYRA_AGENTES_E_PLANOS.md`.
- **Enxame de especialistas (MoE roteado) — ✅ IMPLEMENTADO (02/07/2026), item distinto do acima:** roteia a cascata do `/chat` por categoria (`codigo`/`geral`) via lista declarativa `ESPECIALISTAS`. Ver detalhes em `LYRA_TECNICO.md` seção 10.9.
- **Speculative Decoding — ✅ IMPLEMENTADO (02/07/2026):** não é o spec-decoding clássico (acelerar geração) — é um sidecar de detecção de alucinação: draft `qwen3:0.6b` roda em paralelo ao andar principal da cascata; divergência semântica alta = log de alerta. Ver `LYRA_TECNICO.md` seção 10.13 (inclui limitações conhecidas do método).
- **Câmara de Eco Heurística — ✅ IMPLEMENTADO (02/07/2026):** v1 heurística por padrões (sem LLM) — antes de rodar `executar_comando`/`iniciar_processo_bg`/`escrever_arquivo`/`organizar_pasta` de alto risco (deleção em massa, formatação, shutdown, etc.), bloqueia e exige confirmação explícita do usuário no turno seguinte. Ver `LYRA_TECNICO.md` seção 10.16 (design, travas contra aprovação fora de contexto, limitações conhecidas).

### 4.5 Protocolo Darwin — Auto-evolução (planejado, Fase 5+)
Archive de versões, geração de variantes validadas em sandbox RAM, nenhuma entra sem aprovação Ring 0, rollback automático em regressão. **ADAS (meta-agente):** cria agentes pra problemas recorrentes.

---

## 5. Interface / Front-end

Sem janelas padrão do Windows — tudo flutua sobre o desktop via pywebview + Three.js.

- **Esfera de Partículas:** núcleo azul central com 3 camadas de partículas (60 brilhantes + 240 médias + 300 pequenas), fundo espacial com nebulosas discretas, rotação suave, reage ao estado (idle/ouvindo/processando/falando) com tint de cor.
- **Painel Lateral:** conexões WS/Cérebro, estado, modelo, atividade (CPU/RAM/GPU/VRAM + sparkline), telemetria de tiers, serviços, botão de Grafo de Memória.
- **Chat:** modal flutuante, export .md, limpeza de histórico, anexo de imagem/áudio.
- **Grafo de Memória 3D:** overlay fullscreen com `3d-force-graph v1.73.4` + Three.js r128. Lyra no centro (fixada), tópicos na superfície esférica (Fibonacci + força radial), eventos como partículas menores. Linhas Lyra→tópico com curvatura orgânica (Bézier). Busca de nós, detalhe ao clicar. Fallback para mock quando backend offline. **Conectado às memórias reais do SurrealDB via `/grafo/completo`.**
- **Hardware Bloom:** brilho das partículas reage ao áudio/intensidade da conversa.

---

## 6. Voz, Sentidos e Telemetria (parte implementada, parte planejada)

- **Voz:** dois pipelines distintos, ambos implementados. (1) `mic_engine.py` (wake word "lyra" → Silero VAD → faster-whisper "small" → `/chat`), TTS pausado por decisão do usuário. (2) **Voz Live** (30/06/2026) — botão dedicado no frontend, voz bidirecional em tempo real via Gemini Live API (`WEBSOCKET /ws/voice`, `lyra_voice_live.py`, modelo `gemini-2.5-flash-native-audio-latest`). Ver detalhes técnicos em `LYRA_TECNICO.md`.
- **Emotion Engine (planejado):** análise paralinguística local, 40+ estados emocionais via pitch/tempo/tremor vocal.
- **Wi-Fi Sensing (802.11bf, planejado):** CSI via ESP32 como sonar passivo de presença/movimento.
- **Biometria passiva (planejado):** ritmo de digitação para detectar foco/burnout; EEG via OpenBCI ESP-EEG.
- **Visão Semântica (implementada):** `explicar_tela()` via Gemini Vision (fallback llava-phi3 local); `analisar_imagem()` para imagens em disco.

---

## 7. Stack Técnico Atual (canônico — 30/06/2026)

```
┌─────────────────────────────────────────────────────────────────┐
│ CAMADA          │ TECNOLOGIA                       │ LINGUAGEM  │
├─────────────────────────────────────────────────────────────────┤
│ Interface       │ Three.js + pywebview              │ TS/JS      │
│ WebSocket       │ ws://localhost:8765               │ Python     │
│ Backend/API     │ FastAPI :8000                     │ Python     │
│ LLM Engine      │ Ollama + cascata cloud             │ Go/C++     │
│ LLM Principal   │ Groq gpt-oss-120b / Gemini 3.5-flash / Claude Sonnet / qwen3:8b (fallback) │
│ Embedding       │ BAAI/bge-m3 (1024 dims) via embed_service :8001 — migração CONCLUÍDA │
│ Vector DB       │ Qdrant standalone :6333 (v1.17.1 fixado — não atualizar) │
│ Graph+Doc DB    │ SurrealDB 3.0.5 (:8090, NS "lyra_core", DB "Db_CORTEX") │
│ TTS             │ PAUSADO por decisão do usuário    │
│ STT             │ faster-whisper "small" (CPU int8) │ Python     │
│ Visão           │ Gemini Vision (primário) + llava-phi3 (fallback) │
└─────────────────────────────────────────────────────────────────┘
```

---

## 8. Roadmap por Fases (consolidado)

| Fase | Item | Status |
|---|---|---|
| 0-1 | Ingestão de datasets, vetorização Qdrant, Modelfile, commands.py, audio_manager.py, mic_engine.py, webcam.py, frontend pywebview, Funil de Memória | ✅ Concluído |
| 2 | `lyra_tools.py` (acesso total ao PC), auto-extensão, upgrade Qwen3.5 9B | ✅ Concluído |
| 2 | Cascata de modelos cloud (Groq→Gemini→Claude→local) | ✅ Concluído (25/06/2026) |
| 2 | Grafo de Memória 3D (visualizador interativo das memórias reais) | ✅ Concluído (30/06/2026) |
| 2 | `lyra_agent.py` (loop ReAct completo + self-testing) | ✅ Concluído (30/06/2026) + integrado ao backend `POST /agente` (01/07/2026) + andar local (`_rodar_local`/Ollama) validado ao vivo (02/07/2026) |
| 2 | Hybrid RAG (BM25 + dense + reranker cross-encoder) | ✅ Concluído (26/06/2026, doc corrigida 30/06/2026) |
| 2 | Geração de imagens (`gerar_imagem()` via Pollinations.ai API) | ✅ Concluído (já em produção) |
| 2 | Enxame de sub-agentes paralelos (`lyra_agentes.py`) | ✅ Concluído (26/06/2026, roadmap corrigido 30/06/2026) |
| 3 | Shadow Thoughts (ciclo de sono no SurrealDB) | ✅ Concluído (01/07/2026) — primeira execução real: 28 duplicatas NREM. Agendado automático a cada 3h no loop_proativo. Endpoint `POST /shadow_thoughts` para disparo manual. |
| 3 | Goal Drift Detector (Innovation 1) | ✅ Concluído (01/07/2026) — classifica intenção de cada mensagem (`objetivo/conclusao/passo/resposta`), injeta objetivos pendentes no briefing de startup. |
| 3 | Knowledge Freshness Tags (Innovation 2) | ✅ Concluído (01/07/2026) — meia-vida por categoria no RAG: código 180d, wiki 3650d, matemática/episódio sem penalidade. Peso máximo de 6% no score. |
| 3 | Session Replay cognitivo (Innovation 3) | ✅ Concluído (01/07/2026) — startup reconstrói tópicos dominantes + ferramentas usadas das últimas 24h via grafo SurrealDB, injeta no system prompt. |
| 3 | Cognitive Load Throttling (Innovation 4) | ✅ Concluído (01/07/2026) — `_carga_cognitiva` ajusta top_k do RAG dinamicamente (±2 docs); exposto em `/status`. |
| 3 | Response Provenance (Innovation 5) | ✅ Concluído (01/07/2026) — IDs Qdrant dos docs do RAG gravados em SurrealDB + `/historico`. Cada resposta da Lyra é rastreável à fonte. |
| 3 | Speculative Decoding (draft Qwen 0.5B) | ✅ Concluído (02/07/2026) — ver detalhes técnicos em `LYRA_TECNICO.md` |
| 4 | Emotion Engine (voz paralinguística) | ⏳ |
| 4 | Wi-Fi Sensing via ESP32 (802.11bf) | ⏳ |
| 5 | Protocolo Darwin (auto-reescrita supervisionada) | ⏳ |
| 2 | Visualizador de grafos de memória 3D (Three.js / 3d-force-graph) | ✅ Concluído (30/06/2026) |
| 6 | BCI OpenBCI ESP-EEG, Protocolo Narciso (digital twin) | ⏳ Futuro |

---

## 9. Visão de Longo Prazo (conceitual, não no roadmap ativo)

- **Sistema de Arquivos Líquido:** hard links que fazem arquivos relevantes "brotarem" conforme contexto.
- **Total Recall:** OCR contínuo de tela indexado.
- **Telepatia de Clipboard:** intercepta Ctrl+C, corrige/age antes do Ctrl+V.
- **DNA de Projeto:** versionamento semântico que guarda a intenção, não só o diff.
- **OPSEC avançado:** esteganografia de núcleo, sandbox de hipertempo em RAM, honeypot USB, criptografia pós-quântica (CRYSTALS-Kyber).
- **Soberania acadêmica:** mentor de UML/Java, resumidor automático de PDFs de aula.
- **Sensor Fusion:** unifica Wi-Fi CSI + microfone + teclado + câmera num modelo de estado global.
- **Ghost OS Level 2:** isolamento via namespace/eBPF.

---

*"Não é uma IA. É uma extensão do sistema nervoso."*
