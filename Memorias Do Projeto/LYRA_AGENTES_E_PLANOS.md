# LYRA — Agentes Paralelos e Planos Futuros
> Consolidado em 25/06/2026 a partir de: LYRA_AGENTES_PLANO.md + LYRA_BACKLOG_IDEIAS.md. Atualizado em 30/06/2026.

---

## 1. Plano de Delegação Paralela (Sub-Agentes)

> **✅ Implementado em 26/06/2026** (`lyra_agentes.py`) — este era o plano original, escrito ANTES da implementação. Ver seção 3 abaixo ("Itens do Backlog Já Implementados") para o que foi construído de fato, que seguiu esse desenho de perto.

### Motivação

Hoje a Lyra resolve tarefas multi-etapa **sequencialmente**: uma chamada de ferramenta por vez no loop de `cerebro_maestro.py`. Dois limites:

1. **Velocidade:** "resuma esses 5 PDFs" ou "pesquise X em 3 fontes" — cada chamada roda atrás da outra, mesmo sendo independentes.
2. **Poluição de contexto:** resultados intermediários grandes (texto de 5 PDFs) entram no `historico_recente`, empurrando o contexto da conversa principal pra fora.

A ideia: dar à Lyra uma forma de **delegar pedaços de uma tarefa grande pra sub-execuções isoladas e paralelas**, parecido com o padrão de subagentes do Claude Code.

### Escopo do v1 (o que ENTRA)

- Disparar **N sub-tarefas em paralelo**, cada uma como uma chamada isolada ao LLM com seu próprio contexto curto.
- Sub-tarefas podem usar ferramentas existentes (`ler_documento`, `pesquisar_internet`, `buscar_url`, `traduzir_texto`) — sem criar ferramentas novas.
- Resultado resumido de cada sub-tarefa volta pro orquestrador, que consolida numa resposta única.
- Persistência em SurrealDB (tabelas `enxame` + `subtarefa`), reaproveita padrão de `processo_bg`.
- Limite de concorrência configurável (`max_paralelo=2` por padrão, proteção de VRAM).

### Escopo do v1 (o que NÃO entra — fica pra v2+)

- Sub-agentes com personas/system-prompts diferentes entre si.
- Comunicação entre sub-agentes (A2A) — v1 é só fan-out/fan-in.
- `criar_ferramenta` dentro de sub-tarefas — desabilitado por padrão.
- Interface visual de acompanhamento em tempo real.

### Arquitetura proposta

**Novo módulo:** `C:\Lyra_Project\Lyra_Ollama\lyra_agentes.py`

```python
def criar_enxame(objetivo: str, subtarefas: list[str], modelo: str = "Lyra",
                 max_paralelo: int = 2) -> dict:
    """Cria enxame, persiste em SurrealDB, dispara em background."""

def status_enxame(enxame_id: str) -> dict:
    """Progresso: quantas concluídas/pendentes/com erro + resultados disponíveis."""

def consolidar_enxame(enxame_id: str) -> dict:
    """Junta resultados num resumo único via LLM. Só funciona quando todas terminaram."""
```

**Tabelas SurrealDB:**
- `enxame`: objetivo, total_subtarefas, max_paralelo, status, criado, concluido_em, resumo_final
- `subtarefa`: enxame_id, descricao, status (pendente|rodando|concluida|erro), resultado, erro, iniciado_em, concluido_em

**Execução paralela:** `asyncio.Semaphore(max_paralelo)` dentro de `asyncio.gather()` — cada sub-tarefa chama `ollama.AsyncClient().chat(...)` com prompt isolado.

**Refactor necessário em `cerebro_maestro.py`:** extrair o `while True` de tool-calling do `/chat` pra uma função compartilhada `executar_chat_com_tools(mensagens, tools, modelo)` — tanto o chat principal quanto sub-tarefas precisam do mesmo loop. **✅ FEITO 01/07/2026** — ver `LYRA_TECNICO.md` seção "Item 6". Nota: o enxame (`lyra_agentes.py`) acabou sendo implementado ANTES desse refactor, com sua própria cascata Groq→Gemini isolada — não chegou a depender dele. O refactor valeu de qualquer forma pra eliminar a duplicação entre os 3 andares nativos do `/chat`.

**Integração no `loop_proativo`:** enxames com subtarefas todas terminadas → chama `consolidar_enxame()` automaticamente → `notificar_usuario`/`notificar_celular`.

### Limites de concorrência (CRÍTICO)

A GPU (RTX 2060 Super, 8GB) já é compartilhada com jobs como vetorização BGE-M3. Mitigações obrigatórias:

1. `max_paralelo=2` como default — nunca > 3 sub-tarefas simultâneas.
2. Checar `checar_saude_sistema()` antes de iniciar — se GPU > 85% de carga ou VRAM livre < 1.5GB, recusar e avisar.
3. Timeout de 120s por sub-tarefa — uma travada não derruba o enxame.
4. Sub-tarefas não disparam `criar_ferramenta`/auto-extensão.

### Fases de implementação (ordem sugerida)

**Fase 0 (pré-requisito):** Refatorar loop de tool-calling do `cerebro_maestro.py` pra `executar_chat_com_tools()`. Validar que `/chat` normal não quebrou.

**Fase 1:** `lyra_agentes.py` com `criar_enxame`/`status_enxame` SEM ferramentas nas sub-tarefas (só texto puro). Testar com 2-3 sub-tarefas simples.

**Fase 2:** Sub-tarefas usam subconjunto seguro de ferramentas (`ler_documento`, `pesquisar_internet`, `buscar_url`, `traduzir_texto`). Testar com caso real (ex: 3 PDFs).

**Fase 3:** `consolidar_enxame()` + integração no `loop_proativo` pra notificar automaticamente.

**Fase 4 (v2):** Personas diferentes por sub-tarefa, métricas de custo, interface de acompanhamento.

### Critérios de teste

- [ ] Enxame de 3 sub-tarefas simples roda e consolida, com `max_paralelo=2`.
- [ ] Sub-tarefa com erro proposital não derruba o enxame — fica `erro`, as outras concluem.
- [ ] `checar_saude_sistema()` bloqueia criação de enxame quando GPU está sob carga alta.
- [ ] `loop_proativo` detecta e notifica enxame concluído sem intervenção manual.
- [ ] Regressão: `/chat` normal continua funcionando exatamente como antes.

### Decisões abertas (perguntar ao usuário quando for implementar)

- Modelo nas sub-tarefas: mesmo `Lyra` (qwen3) ou mais leve pra sub-tarefas simples?
- `max_paralelo` padrão: 2 é conservador o suficiente ou o usuário quer ajustar por pedido?
- Sub-tarefas visíveis em tempo real no chat ("[3/5 concluídas]") ou só no final?

---

## 2. Backlog de Itens Pendentes

### Task Scheduler real (privilégio elevado)
`schtasks` dá "Acesso negado" no ambiente sandboxed atual — contornado hoje via atalho na pasta Startup do Windows. Se o ambiente mudar (permissões elevadas), revisitar: agendamento real sobrevive reboot sem depender do `loop_proativo` estar de pé.

### Backup automático agendado
Já existem `backup_memoria(destino)` (testado, exporta SurrealDB + snapshot Qdrant) e `gerenciar_agendamentos`. Falta compor os dois: um agendamento `diario` chamando `backup_memoria` automaticamente. **Usuário pediu explicitamente pra NÃO implementar ainda** — anotar para revisitar quando quiser.

---

## 3. Itens do Backlog Já Implementados (para referência histórica)

- **Explicar tela por voz** — implementado como `explicar_tela()` via Gemini Vision (primário) + llava-phi3 (fallback). `moondream` testado e descartado (incompatibilidade com Ollama 0.30.10).
- **Volume/mídia como ferramenta de chat** — implementado como `controlar_midia(acao)` em `lyra_tools.py`.
- **Vigilância de arquivos** — implementado como `iniciar_vigilancia_pasta`/`parar_vigilancia_pasta`/`listar_vigilancias()` via `watchdog`.
- **lyra_agentes.py** (26/06/2026) — enxame de sub-agentes paralelos com `asyncio.Semaphore`. Persiste em SurrealDB (`enxame` + `subtarefa`). Cascata Groq → Gemini por subtarefa. Loop proativo detecta enxames concluídos e notifica. Endpoints: `POST /enxame`, `GET /enxame/{id}`, `POST /enxame/{id}/consolidar`. Ferramentas no lyra_tools: `criar_enxame`, `status_enxame`, `consolidar_enxame`.
  - **Toolset expandida (26/06/2026):** trocada a allowlist de 4 tools por **denylist** (`TOOLS_BLOQUEADAS`). Subtarefas agora acessam quase todo o lyra_tools (busca, memória, visão, documentos, clima, git, etc.), bloqueando só o destrutivo/auto-modificante/recursivo (execução de comando, escrita de arquivo, `criar_ferramenta`, processos bg, agendamentos, `salvar_memoria`, notificações, `consultar_especialista`, `*_enxame`). Fallback Gemini ganhou tool-calling (antes texto puro). Validado: subtarefa executou `consultar_clima`.
- **Reranker no Hybrid RAG** (26/06/2026) — ✅ FEITO. `bge-reranker-v2-m3` (cross-encoder) servido pelo embed_service (`/rerank`), plugado como 3º estágio de `buscar_hibrido` após o RRF. Era o item "Hybrid RAG (BM25 + dense + ColBERT reranker)" da Fase 2. Validado ao vivo em 30/06/2026 via `GET /buscar` — retorna `rerank_score`/`rrf_score`/`bm25_score`/`dense_score` corretamente.
- **`gerar_imagem()`** — já em produção via Pollinations.ai (Flux, sem key). Item "Geração de imagens" da Fase 2 estava com status desatualizado no roadmap (dizia ComfyUI/SD1.5 planejado); corrigido em 30/06/2026.
- **`lyra_agent.py`** (30/06/2026) — módulo standalone com loop ReAct autônomo, separado do chat: `executar_agente(objetivo, max_iteracoes, ferramentas_bloqueadas)` roda cascata Groq → Gemini → local (mesmo padrão de function-calling do `cerebro_maestro.py`, sem streaming) até o LLM responder texto final ou bater o limite de iterações. Reusa `TOOLS_MAP`/`TOOLS_SCHEMA` do `lyra_tools.py` e a denylist `TOOLS_BLOQUEADAS` do `lyra_agentes.py` (mesmo critério: nada destrutivo/recursivo/auto-modificante). Persiste cada execução em SurrealDB (tabela `agente_run`: objetivo, iteracoes, passos, resposta_final, sucesso, criado_em). `self_test()` roda 3 casos (aritmética sem tool, busca em memória com tool, tool inexistente não derruba o loop) — validado 3/3 via CLI (`python lyra_agent.py --self-test`), exit code 0. Era o último item pendente da Fase 2.
  - **`_rodar_local` validado ao vivo (02/07/2026)** — chamado diretamente (bypass do Groq/Gemini) com os 3 casos do `self_test()` contra `Lyra:latest` via Ollama local. 3/3 passaram: aritmética sem tool ("345" correto, 1 iteração), busca em memória com tool (`buscar_memoria` chamada, respondeu "Paris" corretamente, 2 iterações), tool inexistente não derrubou o loop (retornou texto vazio na 1ª iteração sem tentar chamar a tool — mesmo comportamento observado nos outros andares nesse caso, não é regressão do andar local). Confirma que o loop ReAct funciona igual nos 3 andares da cascata.
  - **Não há ferramenta de hora/data** em `lyra_tools.TOOLS_MAP` — se for útil no futuro, considerar adicionar.
  - **Não integrado ainda:** sem endpoint HTTP novo no `cerebro_maestro.py` por decisão deliberada (módulo standalone primeiro, integração fica para quando o Antônio revisar).
- **`/health` completo** (26/06/2026) — latência real de Qdrant/SurrealDB/Ollama + VRAM via nvidia-smi. `GET /health`.
- **`/grafo`** (26/06/2026) — traversal de grafo SurrealDB por keywords da query. `GET /grafo?q=...`. Fix do bug de LIMIT no `buscar_grafo_surreal` (limitava tópicos, não eventos).
- **`/metrics` com GPU** (26/06/2026) — `gpu_pct` e `vram_pct` via nvidia-smi (cache 4s). Frontend atualizado com 2 novas linhas no painel.
- **`/historico`** (26/06/2026) — `GET /historico` + `DELETE /historico`. Botão de lixeira no header do chat.
- **`/resumo_sessao`** (26/06/2026) — briefing + histórico em memória.
- **Compressão de histórico** (26/06/2026) — quando passa de 14 msgs, comprime as 8 mais antigas via Groq e injeta sumário. Lock `_comprimindo` evita race condition.
- **Telemetria da cascata** (26/06/2026) — `/stats` rastreia usos/falhas/latência/taxa de sucesso por andar, persiste em `telemetria.json`. Painel no frontend mostra distribuição %.
- **`/enxames`** (26/06/2026) — lista enxames recentes. `listar_enxames()` em lyra_agentes. Enxame validado end-to-end (2 subtarefas paralelas + consolidação).
- **`/exportar` + `/tts/falar` + `/` (raiz)** (26/06/2026) — export markdown, TTS de texto arbitrário, ping. Frontend: botões exportar/reler, atalhos `/` e ArrowUp.
- **`consultar_clima(cidade)`** (26/06/2026) — clima atual + previsão via wttr.in (sem key). Default Marília-SP. Registrado no roteador de intenção (clima/tempo/temperatura).
- **Infra** (26/06/2026) — `requirements.txt`, `requirements_embed.txt`, `README.md`, `test_smoke.py` (31 checagens) criados (não existiam).
- **Grafo de Memória 3D — totalmente conectado** (30/06/2026) — `3d-force-graph v1.73.4` + Three.js r128 integrado ao front-end (`script.js`). Lyra central fixada na origem, tópicos na superfície esférica (Fibonacci + força radial), eventos como partículas menores. Linhas Lyra→tópico com curvatura orgânica (valores por link). `d3AlphaDecay(0.04)`, `cooldownTicks(200)`, autoRotate após estabilização. Fallback para mock offline. Preview standalone: `preview_grafo_visualizador.html`. Endpoint `/grafo/completo` corrigido (bug da tabela `topico` inexistente — tópicos extraídos do `sobre.out`). Retorna 40 nós + 100 links das memórias reais do SurrealDB.

## 4. Refatoração OOP completa (07-08/08/2026)

**✅ FEITO.** Backend inteiro migrado de procedural pra OOP em 6 fases — ver `LYRA_TECNICO.md` seção 3 pro detalhamento técnico completo (arquivos novos, bugs corrigidos, mapa de nomenclatura antiga→nova).

Nota específica pra este documento: o `executar_chat_com_tools()` mencionado na linha 56 (feito em 01/07/2026) foi **superado** pela Fase 3 dessa refatoração — a lógica de streaming + tool-calling por provedor (Groq/Gemini/Claude CLI/local) agora vive inteira em `llm_cascade.py` (`LLMCascade`), usada tanto pelo `/chat` (streaming) quanto por `lyra_agent.py`/`lyra_agentes.py` (batch, via `LLMCascade.run()`). O `lyra_tools.py` citado em vários itens acima como módulo monolítico virou shim — as ferramentas em si (`criar_enxame`, `consultar_clima`, `iniciar_vigilancia_pasta`, etc.) continuam com os mesmos nomes e comportamento, só que fisicamente em `Lyra_Ollama/tools/*.py` por domínio. Nenhuma ferramenta/endpoint mudou de contrato — só a organização interna do código.

## 5. Frontend v2 — scaffold iniciado (07/08/2026)

**Stack decidido:** Vite + React + TypeScript, projeto novo em `Lyra_Core/Front_end_Lyra_v2/` (v1 em `Front_end_Lyra/` fica intocado até a troca final). Mockups/plano de referência em `Lyra_Core/Front_end_Lyra_v2_mockups/` (`mockups.html` com as 4 variantes, `plano.html`).

**Decisão de layout:** Classic + Focus Mode mesclados num shell único com toggle de chrome (sidebar + painel direito somem/aparecem) em vez de variantes separadas — ver decisão S18/obs 146-148 do histórico de sessão.

**Feito nesta sessão:**
- Scaffold Vite+React+TS criado e buildando limpo (`npm run build`, `tsc --noEmit` sem erros).
- `useOrb.ts`: hook canvas 2D da esfera (nuvem de pontos fibonacci, projeção/rotação) — portado do JS inline do mockup, parametrizado por `pointCount/linkDist/speed/dotRadius/lineWidth`.
- `components/Orb.tsx`: wrapper do hook com dois presets (`mini` pro header da sidebar, `centerpiece` pro estado vazio).
- `components/Sidebar.tsx`, `RightPanel.tsx`, `Chat.tsx`: portados 1:1 do CSS/HTML do mockup Classic (tokens de cor, sidebar de conversas, painel de métricas system/cascade, chat scroll+input).
- `components/Shell.tsx`: componente raiz mesclado — mostra Sidebar+Chat+RightPanel quando há mensagens; quando vazio, esconde sidebar/painel e mostra a esfera centerpiece + input único (Focus Mode). Botão `⋯` no topo do chat alterna visibilidade do chrome manualmente.
- Dados (conversas, métricas de system/cascade) ainda são mock estático — falta ligar nos endpoints reais (`/metrics`, `/historico`, `/stats`) do backend.

**Integração real com backend (07/08/2026, mesma sessão):** CORS liberado pra `http://127.0.0.1:5173` (Vite dev) em `cerebro_maestro.py`, `vite.config.ts` fixado em host `127.0.0.1:5173`. `api.ts` cobre `/chat` (SSE streaming com AbortController pro stop button), `/historico`, `/sessoes` (+ `PATCH`/`DELETE /sessoes/{id}` novos no backend pra renomear/deletar — excluídos do MCP como os outros destrutivos), `/metrics`+`/stats` (poll 4s no painel direito), `/buscar`, `/tts/mudo`. Sidebar vira rail de ícones (um único elemento com `transition: width`, não troca de componente) dentro de conversa; modelo (auto/groq/gemini/claude/local), mute TTS, markdown+copiar nas respostas, stop button, busca de memória e modal de config (TTS, modelo padrão, limpar conversa, versão do backend, atalhos) — tudo real, sem mock.

**Polish "estilo app Claude" (07/08/2026):** scrollbar fina, textarea com auto-resize + Shift+Enter, indicador de "pensando" (3 pontos) antes do primeiro chunk chegar, auto-scroll do chat, ações da mensagem (copiar) só aparecem no hover, animação de entrada nas mensagens, sidebar agrupada por data (Today/Yesterday/This week/Older), chips de sugestão no estado vazio, fade-in nos modais/overlay.

**Paridade com app do Claude, 2ª rodada (07/08/2026):** avatar (Lyra=orb mini, Antônio="A") + mensagem do usuário em bolha; ações (copiar) no hover pras duas partes; botão **Retry** na última resposta da Lyra (reenvia o último prompt do usuário, trunca a resposta anterior); anexo de arquivo (📎) via `POST /upload` já existente — path do upload cai no textarea pro modelo decidir chamar `analisar_imagem`/`transcrever_audio`; markdown ganhou headings/blockquote/tabela/hr; blocos de código com header + botão copiar próprio (renderer customizado do `marked`, sanitizado via DOMPurify); atalhos globais `Ctrl+K` (busca) e `Ctrl+Shift+O` (nova conversa); rodapé da sidebar virou account chip (avatar+nome, abre config); Settings reestruturado em abas (Profile/Model & voice/Data controls/Keyboard shortcuts/About) em vez de lista única.

**Não feito ainda:** variante IDE preview (fase futura, não é prioridade agora), roteamento por URL entre conversas (tudo em SPA state), tema claro (decisão consciente — identidade visual é dark-only), edição de mensagem já enviada (backend não suporta truncar histórico arbitrário, só o append sequencial — precisaria de endpoint novo).

**Settings expandido pra 7 abas (07/08/2026, 4ª rodada):** Profile (nome de exibição editável, localStorage), Appearance (tamanho de texto small/medium/large via `--chat-font-size`, reduce motion real — desliga toda animação via `[data-reduce-motion]`), Model & voice, **Connected apps** (dados reais do `GET /integracoes` — Telegram, Voice Live, mic wake-word, TTS, enxame, upload, com dot verde/cinza), Data controls (Clear + **Export** novo, baixa `GET /exportar` como `.md` via Blob), Keyboard shortcuts, About. Nome de exibição também substitui "Antônio" fixo no account chip da sidebar.

**Correção de layout de mensagem (07/08/2026, 3ª rodada):** avatar circular genérico (gradiente roxo "A" + ícone 💬 feio no rail) removido — não bate com o padrão real do Claude. Layout reconstruído: mensagem do usuário vira bolha alinhada à direita (sem avatar, sem label "Antônio"); resposta da Lyra é texto puro alinhado à esquerda com só uma marca pequena (mini-orb) acima, sem bolha nem avatar. Rename/deletar sessão na sidebar só aparecem no hover (antes ficavam sempre visíveis, poluindo). Seletor de modelo virou pill com chevron em vez de `<select>` nativo cru. Timestamp da mensagem aparece no hover (`/historico?sessao=` já retornava, só não estava sendo usado no front).
