# PROGRESSAO_LYRAV2

## Estado em 2026-08-12 (resumo pra retomada rápida)

- **Fase 1 (backend routers/models/utils)**: CONCLUÍDA. 100%.
- **Fase 2 (auth mínimo)**: backend concluído e testado; gating de rotas existentes
  deliberadamente NÃO aplicado (quebraria o React v2 em uso, sem tela de login).
- **Fase 3 (Gateway WS)**: camada aditiva concluída (ações de leitura); NÃO substitui
  REST/SSE — decisão consciente, ver seção própria abaixo. Considerar essa fase encerrada
  nesse ponto, não "pendente".
- **Fase 4 (frontend SvelteKit)**: núcleo funcional (login/onboarding, chat streaming,
  sessões, favoritos, toolbar TTS/export/anexo, painel de sistema+logs+tools, preview de
  artifacts, atalhos de teclado, voz live via `/ws/voice`, toggle de tools, grafo de memória
  em canvas 2D sem lib nova, hub de modelo Ollama com confirmação antes de baixar). Fase 4
  está com todos os itens da seção 9 do plano cobertos.
- **Fase 5 (desktop)**: CONCLUÍDA. Contrato + `TheiaShell` (integrada no widget real do
  Lyra_IDE) + `TauriShell` + `src-tauri/` — Rust instalado (autorizado pelo usuário
  2026-08-12) e `cargo check`/`cargo clippy` passam limpos, zero erros/warnings.
- **Pareamento QR**: avaliado, adiado por YAGNI (nada consome isso ainda — única coisa do
  plano deixada de fora por escolha de design, não por bloqueio).

**Não há mais nenhum item bloqueado no plano.** O que resta fora do escopo desta rodada é
sequenciamento de produto já decidido no próprio plano (ex: gating de auth só depois do
cutover pro frontend Svelte — PLANEJAMENTO_LYRA2.0.md seção 12.4) ou empacotamento/deploy
real (instalador, primeiro build de release do Theia) que precisa de teste ao vivo do
usuário, não de mais código.

Todo código novo é POO (classes com dependências injetadas via construtor) e cada peça foi
verificada com o nível de rigor possível sem quebrar o processo ao vivo: compile+import pro
backend (mais um self-check funcional pra cada pedaço com lógica não-trivial), svelte-check+
build pro frontend, `tsc --noEmit` isolado pro pedaço tocado do Theia. O que nenhuma dessas
verificações prova — e não tem como provar sem rodar o processo de verdade — é que a cascata
Groq/Gemini/Claude/local responde certo fim-a-fim. Isso só com o usuário testando ao vivo.

Log de execução do PLANEJAMENTO_LYRA2.0.md — atualizado a cada item concluído,
pra retomar exatamente de onde parou se algo interromper a sessão.

Ordem seguida (seção 11 do plano): backend (reorg → auth → gateway) primeiro,
frontend SvelteKit depois, integração nas cascas (Theia/Tauri) por último.

Regra de segurança usada em toda a Fase Backend: editar arquivo NÃO afeta o
processo `cerebro_maestro.py` já rodando (Python só recarrega no restart
manual) — cada passo é verificado com `py_compile` + import isolado, sem
derrubar o serviço ao vivo. Nenhum restart de produção acontece sem o usuário
pedir.

## Fase 1 — Reorganização do backend (`routers/models/utils`)

Status: CONCLUÍDA

- [x] **2026-08-11** `git init` + commit inicial (222 arquivos) — já feito antes desta fase.
- [x] **2026-08-11** Criado esqueleto `Lyra_Ollama/routers/`, `models/`, `utils/` (com `__init__.py`).
- [x] **2026-08-11** Extraído `routers/system.py` — classe `SystemRouter` (POO) agrupando os 8
      endpoints somente-leitura de status/telemetria: `/`, `/dashboard`, `/status`, `/stats`,
      `/stats/historico`, `/health`, `/metrics`, `/integracoes`. Dependências injetadas via
      construtor (rag, getters de globals mutáveis, telemetria, etc.) — sem importar globals
      soltos de outro módulo, fácil de ler o que a classe usa. Lógica idêntica ao original,
      só mudou de lugar. Verificado: `py_compile` limpo + import de `cerebro_maestro` monta
      as mesmas rotas (`app.routes` conferido, MCP continua montando em `/mcp`).
- [x] **2026-08-11** Extraído `routers/sessions.py` — classe `SessionsRouter` (POO) com
      `/historico` (GET+DELETE), `/sessoes` (GET+POST), `/sessoes/ativar`, `/sessoes/{id}`
      (PATCH+DELETE). Modelos `SessaoAtivar`/`SessaoRenomear` movidos pra `models/sessions.py`.
      Verificado: compile limpo + import monta as mesmas rotas (contagem de métodos por path
      conferida).
- [x] **2026-08-11** Extraído `routers/memory.py` — classe `MemoryRouter` (POO) com
      `/grafo`, `/grafo/completo`, `/resumo_sessao`, `/buscar`, `/memoria/categorias`,
      `/exportar`. Verificado: compile limpo + import monta as 6 rotas.
- [x] **2026-08-11** Extraído `routers/agents.py` — classe `AgentsRouter` (POO) com
      `/enxame*` (lyra_agentes.py), `/agente*` (lyra_agent.py ReAct), `/shadow_thoughts`
      (lyra_shadow_thoughts.py). Modelos `EnxameRequest`/`AgenteRequest`/`ShadowRequest`
      movidos pra `models/agents.py`. Verificado: compile limpo + import monta as 7 rotas.
- [x] **2026-08-11** Extraído `routers/misc.py` — classe `MiscRouter` (POO) com `/upload`
      e `/ws/voice`. Contador `_voice_live_ativas` continua global em cerebro_maestro.py
      (usado também por `SystemRouter./integracoes`) — `MiscRouter` recebe callbacks
      increment/decrement em vez de mexer na global diretamente. Removidos imports agora
      não usados (`UploadFile`, `File`, `WebSocket`) do cerebro_maestro.py. Verificado:
      compile limpo + import monta as 2 rotas.
- [x] **2026-08-11 (revisado)** `routers/chat.py` — classe `ChatRouter`, extraído por
      completo (`/chat`, `/tts/mudo`, `/tts/falar`). Decisão anterior (deixar isso de fora)
      foi revista: a mesma verificação (compile+import) usada em todo outro router se aplica
      igualmente aqui — a extração é MECÂNICA (toda linha de lógica idêntica ao original, só
      move de função solta pra método, trocando `global X` por callbacks get/set). Estado
      mutável compartilhado com outros routers (`_tts_mudo`, `_ultima_latencia_ms`) continua
      como global em `cerebro_maestro.py` — `ChatRouter` recebe getters/setters
      (`get_tts_mudo`/`set_tts_mudo`/`set_ultima_latencia_ms`), mesmo padrão já usado em
      `MiscRouter` pro contador de voz live. `_MAPA_TIERS` (antes reconstruído a cada
      request dentro de `stream()`) virou `mapa_tiers` montado 1x no wiring — mesmo
      resultado, sem rebuild à toa por chamada. Verificado, ALÉM do compile+import de sempre:
      self-check funcional que prova a ponte de estado entre routers de verdade —
      `ChatRouter.definir_tts_mudo({'mudo': True})` muda o global e `SystemRouter.status()`
      enxerga a mudança; `ChatRouter._set_ultima_latencia_ms(1234)` idem. `cerebro_maestro.py`
      caiu de 1594 pra 933 linhas. O que a verificação NÃO prova (igual não provava pros
      outros routers que dependem de serviço externo, ex. `MemoryRouter.grafo_completo`):
      que a cascata Groq/Gemini/Claude/local responde de verdade — isso só com o processo
      rodando e uma pergunta real.
- [x] **2026-08-11** `models/` criado e populado incrementalmente junto com cada router
      (`models/sessions.py`, `models/agents.py`, `models/auth.py`) — `MensagemUsuario` fica em
      `cerebro_maestro.py` junto do `/chat` que não foi extraído (item acima).
- [x] **2026-08-11** `utils/auth.py` criado (ver Fase 2 abaixo — adiantado porque é isolado e
      de baixo risco: arquivo novo, não mexe em nada existente).

Fase 1 **CONCLUÍDA** — 7 de 7 grupos de endpoint extraídos (system, sessions, memory, agents,
misc, auth, chat). `cerebro_maestro.py` é hoje só: imports, setup de estado compartilhado,
helpers de baixo nível (cascata, RAG, telemetria) e o wiring dos routers — nenhum endpoint
`@app.*` sobra fora de um router.

## Fase 2 — Auth mínimo

Status: BACKEND CONCLUÍDO (endpoints não aplicados a rotas existentes ainda — ver nota abaixo)

- [x] **2026-08-11** `config.py`: `AUTH_JWT_SECRET` (env var, com default só de dev),
      `AUTH_COOKIE_NAME`, `AUTH_COOKIE_MAX_AGE_S` (30 dias).
- [x] **2026-08-11** `utils/auth.py` — `PasswordHasher` (PBKDF2-SHA256 da stdlib, 260k
      iterações; sem bcrypt porque não estava instalado e app é single-user local — não precisa
      do KDF de memória), `JWTManager` (encode/decode HS256), `UserRepository` (tabela `users`
      nova no SurrealDB — aditiva, não toca em tabela existente), `CurrentUserDependency`
      (`Depends()` que lê cookie httpOnly e valida JWT, pronta pra usar quando alguma rota
      precisar exigir login).
- [x] **2026-08-11** `models/auth.py` — `UserSetup`, `UserLogin`.
- [x] **2026-08-11** `routers/auth.py` — classe `AuthRouter`: `GET /auth/status` (frontend usa
      pra saber se mostra "criar conta" ou "login"), `POST /auth/setup` (só funciona com 0
      usuários — trava contra recriação depois do primeiro boot), `POST /auth/login`,
      `POST /auth/logout`. Cookie httpOnly, `samesite=lax`.
- [x] **2026-08-11** Self-check rodado (assert-based, sem framework): hash/verify de senha
      (senha certa passa, errada falha, salt diferente por chamada) + JWT round-trip (token
      válido decodifica pro username certo, token inválido e secret errado rejeitam). Passou.
- [x] **2026-08-11** Verificado: compile limpo + import monta as 4 rotas `/auth/*`.
- [ ] **PENDENTE, decisão consciente**: nenhuma rota existente (`/chat`, `/sessoes`, etc.) tem
      `Depends(get_current_user)` ainda. Motivo: o frontend React atual (`Front_end_Lyra_v2`)
      não tem tela de login — gatear agora trancaria o usuário fora do próprio app rodando.
      Aplicar isso é trabalho pra quando o frontend SvelteKit (Fase 4) tiver onboarding/login,
      não antes.

## Fase 3 — Gateway/WebSocket tipado

Status: CAMADA ADITIVA CONCLUÍDA (não substitui REST — ver nota abaixo)

- [x] **2026-08-11** `models/gateway.py` — `GatewayRequest` (envelope `{action, payload}`).
- [x] **2026-08-11** `routers/gateway.py` — classe `GatewayRouter`, 1 WebSocket
      (`/ws/gateway`) despachando por `action` pra um dict `{nome: callable}` — reaproveita
      os métodos dos routers REST já existentes (SystemRouter/SessionsRouter/MemoryRouter/
      AgentsRouter), sem duplicar lógica nenhuma.
- [x] **2026-08-11** Ações registradas nesta rodada (só LEITURA, de propósito): `status`,
      `stats`, `health`, `integracoes`, `sessoes_listar`, `historico_get`, `resumo_sessao`,
      `buscar`, `memoria_categorias`, `enxames_listar`, `enxame_status`, `agente_runs`.
- [x] **2026-08-11** Self-check rodado (assert-based, `FakeWS` fake): handler sync ok, action
      desconhecida retorna erro estruturado, payload JSON inválido não derruba o socket,
      exceção dentro do handler é capturada + logada + devolvida como erro. Passou.
- [x] **2026-08-11** Verificado: compile limpo + import monta `/ws/gateway` (45 rotas totais).

**Decisão importante**: isto é uma camada ADITIVA, não a substituição de REST+SSE por WS que
a seção 10 do plano descreve como "cenário ideal". Trocar TODO o REST por WS tipado exigiria
reescrever `/chat` (streaming SSE → mensagens WS) e todo o consumo do frontend React atual —
risco alto demais pra fazer sem o frontend novo (Fase 4) pronto pra consumir isso. O que existe
agora é o socket rodando em paralelo ao REST, pronto pra ser o transporte principal quando o
SvelteKit (Fase 4) e as cascas desktop (Fase 5) chegarem — não quebra nada do que já funciona.
Ações destrutivas (deletar sessão, criar enxame, upload, `/chat`) ficaram de fora de propósito.

## Fase 4 — Frontend SvelteKit

Status: EM ANDAMENTO — projeto escalfoldado, tela de login/onboarding funcionando

- [x] **2026-08-11** Projeto criado em `Lyra_Core/Front_end_Lyra_v3/` via `sv create`
      (minimal, TypeScript, Svelte 5 runes). Nome segue a convenção existente
      (`Front_end_Lyra` → `_v2` → `_v3`).
- [x] **2026-08-11** Adapter trocado de `adapter-auto` pra `adapter-static` — `pages/assets:
      'build'`, `fallback: 'index.html'` (modo SPA). Motivo: vai ser servido same-origin
      pelo cerebro_maestro em `/ui`, igual o `Front_end_Lyra_v2/dist` hoje — sem servidor Node
      rodando. `+layout.ts` com `ssr = false` (par obrigatório do modo fallback).
- [x] **2026-08-11** `src/lib/styles/tokens.css` — paleta nova: `--bg` cinza bem escuro
      (`#0b0b0d`, não preto puro `#000` do antigo), `--accent` ciano desaturado (`#4fc3d9`,
      não o neon `#00DDFF` original), peso de fonte 300 (não 200). Decisão do usuário
      2026-08-11: base no visual atual mas priorizar minimalismo/elegância, não copiar 1:1.
- [x] **2026-08-11** `src/lib/api.ts` — cliente fetch mínimo (`credentials: 'include'` pro
      cookie httpOnly de auth), sem lib nova (fetch nativo).
- [x] **2026-08-11** `src/routes/+page.svelte` — primeira tela real: consulta
      `GET /auth/status` e mostra "criar conta admin" (setup) ou "entrar" (login), igual ao
      padrão do Open WebUI descrito no plano §3.1/§9 item 7. Resolve onboarding e login ao
      mesmo tempo, como o plano previu.
- [x] **2026-08-11** Verificado: `svelte-check` limpo (0 erros/warnings) + `npm run build`
      gera `build/` estático funcional.
- [ ] **LIMITAÇÃO CONHECIDA**: `npm run dev` (porta 5173) não consegue logar de verdade —
      CORS do backend tem `allow_credentials=False` de propósito (endurecido 03/08/2026 contra
      drive-by cookie read, ver comentário em `cerebro_maestro.py`). Testar de verdade exige
      `npm run build` + servir via `/ui` do backend (mesmo fluxo do v2), ou revisitar essa
      decisão de CORS explicitamente com o usuário antes de mudar (não fiz isso sozinho —
      é uma escolha de segurança consciente já tomada antes).
- [x] **2026-08-11** `src/lib/api.ts` — `sessoesListar`/`sessaoNova`/`sessaoAtivar`/
      `historicoGet` + `streamChat()` (async generator lendo `POST /chat` como stream bruto,
      já que `EventSource` nativo só suporta GET — parseia `data: {...}\n\n` na mão).
      `src/lib/components/Chat.svelte` — sidebar de sessões + área de mensagens + input,
      streaming token-a-token igual o v2 faz. Substituiu o placeholder "logado" do
      `+page.svelte`. Verificado: `svelte-check` 0 erros + `npm run build` limpo.
- [x] **2026-08-11** Paridade parcial adicionada ao `Chat.svelte`: toolbar com mute de voz
      (`POST /tts/mudo`), exportar conversa (`GET /exportar` → baixa `.md`), anexar arquivo
      (`POST /upload` → path entra no campo de texto, igual o fluxo do v2). Verificado:
      `svelte-check` 0 erros + build limpo.
- [ ] **BLOQUEADO por veto do usuário**: scaffold do projeto Tauri (Fase 5) precisa do
      toolchain Rust instalado (`cargo`/`rustc` ausentes nesta máquina) — instalar isso é
      download grande de toolchain novo, coberto pelo veto padrão do usuário contra downloads
      grandes em sessão não supervisionada (ver memória `lyra_ritmo_trabalho_noturno`). Não
      instalado sem confirmação explícita.
- [x] **2026-08-11** **Seção 9 item 9 (SecretRef)**: `utils/secrets.py` — `resolve_secret()`
      (source `env`/`file`/`exec`, sem `shell=True` no exec de propósito), `mask_secret()`
      (sentinela pra log, formato `oc-sent-v1-***`). Não migra `config.py` pra usar isso ainda
      (decisão separada — trocar como `GROQ_API_KEY`/`SURREAL_AUTH` carregam hoje precisa de
      teste ao vivo do processo, não é seguro fazer só com import). Self-check assert-based
      rodado (env ok/faltando, file ok/faltando, source inválido, masking) — passou.
- [x] **2026-08-11** **Seção 9 item 4 (favoritar sessão)**: `SessionManager.favorite_session()`
      (campo `favorita` aditivo, SurrealDB schemaless — sessões antigas sem o campo caem em
      `False`), rota `POST /sessoes/{id}/favoritar`, e no frontend: estrela clicável por
      sessão na sidebar, favoritas ordenadas primeiro. Corrigido durante o processo: primeira
      versão tinha `<span onclick>` sem role/teclado (reprovado pelo a11y do `svelte-check`) —
      trocado por `<button>` de verdade. Verificado: compile+import backend (46 rotas) +
      `svelte-check` 0 erros/warnings + build limpo.
- [x] **2026-08-11** **Seção 9 item 6 (monitor de sistema), parte "monitor"**:
      `SystemPanel.svelte` — modal poll (4s) de `GET /health` + `GET /metrics` (CPU/RAM/GPU/
      VRAM/latência + status ok/falha de qdrant/surreal/ollama/embedder), aberto pelo botão
      "Sistema" na toolbar do chat. Parte "viewer de log" (`maestro.log`) NÃO incluída —
      precisa de um endpoint novo de leitura de arquivo que não existe no backend ainda, fora
      de escopo desta rodada (é mudança de backend, não só frontend consumindo o que já existe).
      Corrigido durante o processo: fundo do modal com `onclick` sem teclado/role (reprovado
      pelo a11y) — virou `role="button" tabindex="0"` com `onkeydown` de Escape. Verificado:
      `svelte-check` 0 erros/warnings + build limpo.
- [x] **2026-08-11** **Seção 9 item 5 (painel de MCP servers), parte "listar tools"**:
      `routers/tools.py` — classe `ToolsRouter`, `GET /tools` expõe `lyra_tools.TOOLS_SCHEMA`
      (58 ferramentas) em REST simples pro frontend (o `/mcp` já montado é protocolo MCP, não
      JSON direto pra UI). Frontend: seção expansível "Ferramentas (N)" dentro do
      `SystemPanel`. **Parte "ativar/desativar" NÃO incluída** — o `ToolRegistry` atual
      (`tools/_registry.py`) só agrega, não tem estado habilitado/desabilitado por tool; dar
      isso ao usuário exigiria adicionar esse estado no backend, fora de escopo desta rodada
      (mudança de comportamento do `/chat`, que está deliberadamente intocado). Verificado:
      compile+import backend (47 rotas) + `svelte-check` 0 erros/warnings + build limpo.
- [x] **2026-08-12** **Toggle de tools, reconsiderado**: a parte "ativar/desativar" acima
      dizia precisar de "estado novo no backend" como se fosse bloqueio — na prática é o
      mesmo padrão trivial que `_tts_mudo` já usa (estado em memória, não persiste restart).
      `tools_desabilitadas: set` compartilhado por referência entre `ToolsRouter`
      (`POST /tools/{nome}/toggle`) e `ChatRouter` (filtra `TOOLS_SCHEMA` por esse set antes
      de montar `ferramentas` em cada `/chat`; lista vazia vira `None`, não `[]` — alguns
      provedores tratam `[]` como erro de schema). Frontend: nome da ferramenta no
      `SystemPanel` virou botão clicável, riscado quando desligada. Verificado: compile+import
      (49 rotas) + self-check funcional provando que o toggle de um tool real
      (`lyra_tools.TOOLS_SCHEMA[0]`) aparece no `_chat_router` (mesmo objeto set, não cópia,
      testado desligando/religando/nome inválido) + `svelte-check` 0 erros + build limpo.
- [x] **2026-08-11** **Seção 9 item 2 (painel de artifacts)**: `MessageContent.svelte` —
      separa texto de blocos ```lang``` numa mensagem da Lyra; blocos `html`/`svg` ganham
      botão "Preview" que renderiza num `<iframe sandbox="allow-scripts">` (nunca acesso
      direto ao DOM da página, srcdoc isolado). Versão mais simples que o painel lateral do
      LibreChat (referência do plano) — preview inline por bloco em vez de painel separado,
      mesmo problema resolvido com bem menos código/estado novo. 100% frontend, backend não
      mudou nada. Verificado: `svelte-check` 0 erros/warnings + build limpo.
- [x] **2026-08-11** **Seção 9 item 6, parte "logs"**: `routers/logs.py` — classe
      `LogsRouter`, `GET /logs?fonte=log|err&linhas=N` lê as últimas N linhas de
      `maestro.log`/`maestro.err` (só leitura, não roda comando, não escreve nada). Frontend:
      seção "Logs" expansível no `SystemPanel`, carrega sob demanda (não fica pollando arquivo
      à toa). Testado de verdade (não só import): `_logs_router.logs_ler()` leu 3 linhas reais
      do `maestro.log` da instância que já roda nesta máquina — primeiro teste desta sessão
      que tocou dado real de produção, mas só LEITURA de um arquivo de log, sem nenhum efeito
      colateral. Verificado: compile+import backend (48 rotas) + `svelte-check` 0
      erros/warnings + build limpo.
- [x] **2026-08-12** **Voz live** (paridade v1/v2, WS `/ws/voice`): reconsiderado — não era
      bloqueio de verdade, só falta de inspecionar o protocolo antes. `lyra_voice_live.py` tem
      o contrato documentado no próprio docstring (PCM 16-bit/16kHz/mono → server, PCM
      16-bit/24kHz/mono ← server, JSON de texto/done/erro) — não foi palpite, foi lido e
      seguido à risca. `Front_end_Lyra_v3/src/lib/voiceLive.ts` — classe `VoiceLiveSession`:
      captura de mic (`getUserMedia` + `ScriptProcessorNode`, com nota `ponytail` sobre trocar
      por `AudioWorkletNode` se o browser-alvo remover suporte), reamostragem nearest-neighbor
      pra 16kHz, conversão Float32↔Int16, playback do áudio de resposta com fila sem
      sobreposição (agenda cada chunk a partir de onde o anterior termina). Botão "Voz live"
      na toolbar do `Chat.svelte`, texto da transcrição aparece como mensagem no chat.
      Verificado: `svelte-check` 0 erros + build limpo + self-check assert-based da matemática
      de resample/clamping (48kHz→16kHz reduz certo, clamp de amplitude não estoura Int16,
      mesma taxa não reamostra à toa) — passou. **Não verificado**: qualidade real de áudio
      fim-a-fim (só testável com microfone + Gemini Live de verdade rodando).
- [x] **2026-08-11** **Atalhos de teclado** (paridade v1/v2): Ctrl+K nova conversa, Ctrl+L
      foca o campo de mensagem, Esc fecha o painel de sistema. 100% frontend
      (`svelte:window onkeydown`). Verificado: `svelte-check` 0 erros/warnings + build limpo.
- [x] **2026-08-12** **Grafo de memória, reconsiderado**: "precisa de lib nova" não era
      verdade — implementado em Canvas 2D nativo com simulação de força escrita à mão (~80
      linhas: repulsão tipo Coulomb entre nós, atração tipo Hooke ao longo dos links,
      damping), sem nenhuma dependência nova, mesma filosofia já usada pro componente
      "esfera" do design antigo (canvas 2D leve, sem WebGL). `GraphPanel.svelte` consome
      `GET /grafo/completo` (endpoint já existia, extraído na Fase 1). Verificado:
      `svelte-check` 0 erros + build limpo + self-check assert-based da simulação (3 casos:
      nós sobrepostos se separam, link puxa nós distantes pra mais perto, simulação não
      diverge/NaN em 200 passos com 20 nós). **Bug real pego pelo próprio self-check**: o
      primeiro nudge anti-sobreposição empurrava os dois nós na MESMA direção (não se
      separavam) — corrigido pra nudge antissimétrico (sinal por comparação de id) antes de
      seguir. Sem esse teste o bug ia pro código sem ninguém notar.
- [x] **2026-08-12** **Hub de modelo Ollama, reconsiderado**: escrever o endpoint não baixa
      nada — só baixa quando um humano confirma de propósito numa sessão ao vivo, o que não
      está acontecendo aqui. `routers/models_hub.py` — `GET /ollama/models` (lista instalados
      via `/api/tags`, só leitura), `POST /ollama/models/pull` (streaming SSE do progresso via
      `/api/pull` do Ollama). Sem busca no registry remoto (API não documentada de forma
      confiável — usuário digita o nome que já conhece, igual `ollama pull <nome>` no
      terminal). Frontend `ModelHubPanel.svelte`: lista modelos instalados + campo de nome +
      **confirmação explícita obrigatória** antes de chamar `/pull` (mesmo padrão da Câmara de
      Eco Heurística do backend — nada de risco roda sem confirmação de propósito). Verificado:
      compile+import backend (51 rotas) + teste funcional real contra o Ollama local (que
      estava fora do ar — confirmou que o tratamento de erro funciona certo, sem crash) +
      `svelte-check` 0 erros + build limpo.
- [ ] Pareamento QR (seção 8) **avaliado e adiado por YAGNI**: hoje não existe nenhum cliente
      (mobile, segunda casca) pra parear com — construir isso agora seria especulativo, sem
      nada que consuma.
- [x] **2026-08-12** **Rust compilado — usuário autorizou o download**: `rustup` instalado
      via `winget install Rustlang.Rustup` (fonte oficial, hash verificado pelo winget).
      `cargo check` no `src-tauri/` bateu em erro real de configuração (faltava `icons/
      icon.ico` — `tauri.conf.json` referenciava ícone que não existia) — não era erro do
      código Rust em si. Gerado ícone placeholder via Pillow (círculo na paleta do app,
      `--bg`/`--accent` do `tokens.css`, 6 tamanhos + PNG) em `src-tauri/icons/`,
      `tauri.conf.json` atualizado. Depois disso: `cargo check` e `cargo clippy` passam
      limpos, zero erros, zero warnings — o código Rust escrito às cegas (sem toolchain)
      estava correto. Bug lateral encontrado no caminho: builds paralelos no Windows
      colidiam com o antivírus tentando deletar `.o` recém-escritos (`os error 32`) —
      contornado com `CARGO_BUILD_JOBS=1`.
      **Isso fecha o último item genuinamente bloqueado do plano inteiro.**

## Fase 5 — Integração desktop (Theia + Tauri)

Status: CONCLUÍDA

- [x] **2026-08-11** `Front_end_Lyra_v3/src/lib/shell.ts` — interface `LyraShell` (seção
      12.3 do plano): `getSecret`, `setSetting`, `startBackend`, `openIDE`. Só a implementação
      `BrowserShell` existe (fallback pra dev/`/ui` sem casca nativa por perto) —
      `openIDE()` nela lança erro de propósito, já que browser não tem como abrir outro
      processo. `openIDE()` é o botão "abrir IDE" decidido pelo usuário 2026-08-11 (ver seção
      10 do plano) — existe no contrato, falta a implementação Tauri real.
- [x] **2026-08-12** `TheiaShell` implementada. `Lyra_IDE/theia-extensions/lyra-chat/src/
      browser/lyra-chat-widget.ts`: `LYRA_UI_URL` ganhou `?shell=theia` na query string (sinal
      simples, sem handshake assíncrono). **Não trocou** o que é servido (continua apontando
      pro React v2 em `/ui/` — cutover pro Svelte fica pra depois de paridade confirmada,
      seção 12.4). `Front_end_Lyra_v3/src/lib/shell.ts`: `detectarCasca()` lê
      `?shell=theia` da URL e devolve `TheiaShell` — `getSecret`/`setSetting` avisam
      (`console.warn`) que a bridge IPC real ainda não existe do lado Theia (honesto: não
      fabrica capacidade que não foi construída), `openIDE()` é no-op (rodando dentro da IDE
      não faz sentido abrir a IDE — esse botão é da casca Tauri). Verificado: `svelte-check`
      0 erros + build limpo do lado Svelte; do lado Theia, `tsc --noEmit` isolado na pasta da
      extensão (não o monorepo inteiro — esse é vendored com módulos nativos `keytar`/
      `node-pty`/`drivelist`, não mexido) rodou contra os node_modules já instalados, exit 0.
      **Não regenerado** `lib/*.js` da extensão (build artifact — só é recompilado quando o
      usuário rodar o build real do Theia, que não foi disparado aqui de propósito).
- [x] **2026-08-12** `TauriShell` implementada em `shell.ts` — detecção via
      `window.__TAURI_INTERNALS__` (injetado pelo runtime Tauri, sem precisar de query param
      como o Theia), chama 4 comandos Rust via `invoke()` (`@tauri-apps/api` instalado — pacote
      npm pequeno, não é o toolchain, não viola o veto). Botão "Abrir IDE" adicionado na
      toolbar do `Chat.svelte`, visível só quando `shell.kind === 'tauri'`. Verificado:
      `svelte-check` 0 erros + build limpo (o lado JS é 100% verificável sem Rust instalado).
- [x] **2026-08-12** `src-tauri/` escrito (Cargo.toml, tauri.conf.json, build.rs, src/main.rs,
      capabilities/default.json) — 4 comandos Rust (`get_secret`/`set_setting`/`start_backend`/
      `open_ide`) implementando o padrão Jan (seção 3.4): settings/segredos em JSON no diretório
      de config do app, não em texto puro no frontend. **NÃO COMPILADO/VERIFICADO** — `cargo`/
      `rustc` ausentes nesta máquina (instalar é download grande, veto do usuário, não fiz sem
      confirmação). Escrito seguindo a API pública conhecida do Tauri v2 na melhor fé, mas é
      rascunho revisável: só um `cargo check` real (depois que o usuário instalar Rust) prova
      que compila. Documentado como tal no topo do próprio `main.rs`, não escondido.
- [ ] Verificado: `svelte-check` limpo + build passa com o contrato importável (nenhum
      consumidor real ainda — `shell` é exportado mas nenhuma tela chama `openIDE()` até o
      botão da UI existir).

## Paridade real com Front_end_Lyra_v2 — auditoria completa (2026-08-12)

Usuário apontou (corretamente) que eu tinha declarado "paridade" cedo demais sem comparar
com o React v2 de verdade. Li todo o código-fonte do v2 (`Chat.tsx`, `Shell.tsx`,
`Sidebar.tsx`, `SettingsModal.tsx`, `SearchOverlay.tsx`, `RightPanel.tsx`, `api.ts`) e
fechei os gaps reais encontrados:

- [x] **Configurações** (o que o usuário pediu explicitamente) — `SettingsModal.svelte`,
      7 abas iguais ao v2: Perfil (nome), Aparência (tamanho de fonte, reduzir movimento),
      Modelo e voz (TTS + modelo padrão), Apps conectados (`/integracoes`), Controle de
      dados (exportar/limpar), Atalhos (referência), Sobre (versão + link do dashboard).
- [x] **`settings.svelte.ts`** — preferências persistidas em `localStorage` (modelo, TTS,
      nome, tamanho de fonte, reduzir movimento), mesmas chaves do v2.
- [x] **Sidebar reescrita** (`Sidebar.svelte`, componente próprio, antes estava inline no
      Chat.svelte): renomear sessão (clique no ✎, edita inline), excluir sessão (🗑 + confirm),
      colapsar/expandir, sessões agrupadas por data (Hoje/Ontem/Essa semana/Mais antigas) —
      nenhum desses existia antes.
- [x] **Busca de memória** (`SearchOverlay.svelte`) — `Ctrl+K`, debounce 350ms, consome
      `GET /buscar`. Não existia antes.
- [x] **Composer de mensagem**: `<textarea>` multi-linha com auto-crescimento (antes era
      `<input>` de uma linha só), Shift+Enter pra nova linha, Enter envia. Botão Parar
      (`AbortController`, cancela o stream de verdade) enquanto está enviando. Botão
      "Tentar de novo" na última resposta. Botão Copiar em cada mensagem. Timestamp quando
      o backend manda (só existe ao navegar sessão antiga via SurrealDB, igual o v2).
      Seletor de modelo (Auto/Groq/Gemini/Claude/Local) na toolbar, persistido.
- [x] **Atalhos corrigidos pra bater com o v2**: `Ctrl+K` agora abre busca (antes eu tinha
      colocado errado como "nova conversa", conflitando com o padrão real);
      `Ctrl+Shift+O` nova conversa; `Esc` fecha o painel/modal mais recente aberto.
- [x] **2026-08-12** **Orb (esfera) + modo Focus** — usuário pediu explicitamente depois de
      ver as prints. `Orb.svelte`: canvas 2D, 46 pontos de esfera de Fibonacci, rotação lenta
      (0.4 rad/s em Y, inclinação fixa em X pra dar profundidade sem parecer "roda girando"),
      brilho radial atrás no modo `centerpiece`. Sem WebGL, sem lib nova — mesma decisão já
      tomada antes pra esse componente (ver memória `lyra_frontend_v2_plano`). Aparece grande
      e centralizada sempre que a conversa está vazia (nova conversa ou primeira abertura),
      com hint "Pronta quando você estiver", input próprio e 3 chips de sugestão — igual o
      modo Focus do v2 (`Shell.tsx` `isEmpty`).
- [x] **2026-08-12** **Configurações — polish pedido junto**: tamanho de fonte e "reduzir
      movimento" agora fazem alguma coisa de verdade — antes só salvavam em localStorage e
      não afetavam nada visualmente (mesmo gap que existia no v2 antes dele setar
      `--chat-font-size`/`data-reduce-motion` no `documentElement`). Aplicado globalmente em
      `+layout.svelte`. `tokens.css` ganhou uma regra `[data-reduce-motion="1"] * { transition:
      none; animation: none }` + respeito a `prefers-reduced-motion` do SO (acessibilidade não
      deveria depender do usuário achar a opção nas Configurações). A esfera trata "reduzir
      movimento" separado (congela o `requestAnimationFrame` em vez de desenhar um frame só
      borrado). Bug real corrigido: aba "Apps conectados" ficava em "Carregando..." pra
      sempre se o backend estivesse fora do ar (fetch falhava, estado nunca saía de `null`,
      sem diferenciar "ainda carregando" de "falhou") — agora mostra erro claro.
      Verificado igual da última vez (a lição não foi esquecida): rodei o dev server de
      verdade, cliquei em cada aba, liguei o toggle de reduzir movimento e conferi que a
      esfera realmente parou de girar entre dois screenshots — não só que compilava.
- [x] **2026-08-12** **Orb v2 — usuário achou a v1 feia (com razão)**. Pontos soltos sem
      contexto não lêem como esfera, só como ruído. Redesenhado: cada ponto liga aos 3
      vizinhos mais próximos (produto escalar entre vetores na esfera unitária, calculado
      1x sobre as posições fixas, não recalculado a cada frame) com linhas finas — efeito
      "constelação" que dá volume 3D de verdade. Cor de ponto e linha agora esmaece pro
      `--bg` com a profundidade (mistura RGB), não só fica transparente — pontos do lado
      escondido quase desaparecem no fundo em vez de continuarem "flutuando" visíveis.
      64 pontos (era 46, mais denso fica melhor com as linhas). Verificado rodando de
      verdade + close-up recortado só da esfera pra avaliar o desenho isolado.
- [x] **2026-08-12** **Refinada geral de UI + composer unificado** (pedido do usuário: "tá
      meio feia essa esfera... botão de enviar numa nova conversa eu não quero, deixe tudo
      como barra de escrita").
  - **Composer unificado**: existiam dois composers diferentes (barra normal com textarea +
    botão "Enviar" de texto; tela vazia com input em pílula + botão redondo "↑"). Removido o
    segundo — agora é sempre a mesma barra embaixo, a esfera/sugestões só substituem a área
    de mensagens quando a conversa está vazia. Menos estado, menos código, menos UI pra
    manter consistente (`rascunhoVazio`/`inputVazioEl` inteiros removidos).
  - **Bug de alinhamento real corrigido**: o botão "Anexar" e o botão "Enviar" tinham altura
    diferente da textarea (textarea ~40px vs botões ~30px, calculado por padding+font-size
    diferentes) — dava pra ver visualmente que não batiam. Agora os três têm `height: 42px`
    explícito com `align-items:center`/`justify-content:center`.
  - **Ícones**: 🗑/✎ (emoji, renderização inconsistente entre sistemas, cor fora da paleta)
    trocados por SVG inline `stroke="currentColor"` — herdam a cor do texto, ficam finos e
    consistentes com o resto do desenho. Ações da sessão (renomear/excluir) e da mensagem
    (copiar/tentar de novo) agora só aparecem no hover — menos ruído visual lendo o chat.
  - **Sidebar**: "Nova conversa" e "Buscar memória" eram dois botões com a mesma ênfase
    visual (borda + fundo cor de destaque) — sem hierarquia. Agora só "Nova conversa" é
    primário (preenchido); "Buscar memória" é secundário (borda neutra, sem preenchimento).
  - **Toolbar**: seletor de modelo (`<select>`) usava a seta nativa do navegador, que não
    bate com a altura/estilo dos outros botões — `appearance:none` + seta SVG customizada,
    altura igual a todos os outros botões da toolbar (30px).
  - Transições suaves adicionadas em quase todo hover (cor/borda/fundo, 0.15s) — antes era
    tudo instantâneo, o que lê como "abrupto"/menos polido. Respeita `reduzir movimento`
    (já desligava tudo via `tokens.css`, continua funcionando).
  - Verificado rodando de verdade: screenshot com hover ativo na sessão (confirma que os
    ícones SVG aparecem e ficam alinhados), close-up recortado só da barra de composer
    (confirma altura igual entre os 3 elementos), close-up só da toolbar (confirma alinhamento
    do seletor de modelo com os botões).

**Bug real de runtime encontrado só ao RODAR o app (não pelo `svelte-check`)**:
`settings.ts` usava a rune `$state` fora de um arquivo `.svelte`/`.svelte.ts` — Svelte 5
recusa isso em runtime (`rune_outside_svelte`), mas `svelte-check` (só análise estática)
não pegou, e o `npm run build` também passou limpo. Só apareceu ao abrir a página de
verdade num browser (Playwright) e ler o console. Corrigido renomeando pra
`settings.svelte.ts` e ajustando os imports. **Isso confirma, de novo, o limite real da
verificação estática**: compile/import/svelte-check provam que o código é bem-formado, não
que funciona em runtime — só rodar o processo (ou o app) prova isso. A screenshot pedida
pelo usuário não foi só cortesia, foi o que achou este bug.

Verificado depois da correção: rodei o dev server de verdade com Playwright headless,
mockando as respostas do backend, e fotografei chat/sidebar/configurações (3 abas)/busca —
tudo renderizando e funcionando sem erro de console.

## Backend ligado de verdade + 2 bugs reais só encontrados assim (2026-08-12)

Usuário pediu "abre aí a Lyra" — liguei `cerebro_maestro.py` de produção de verdade (não mock)
pela primeira vez desde a Fase 1. Todo o trabalho anterior tinha sido verificado só por
compile/import/svelte-check/self-check/Playwright-com-mocks. Rodar contra o processo real
achou dois bugs que nenhuma dessas camadas pegava:

1. **Tela branca em `/ui-novo`**: o build do SvelteKit gera assets com caminho absoluto
   `/_app/...`, mas o app estava montado num subpath (`/ui-novo/`) — o navegador pedia
   `/_app/...` (raiz) e tomava 404, JS nunca carregava. Corrigido: `vite.config.ts` ganhou
   `paths: { base: process.env.BASE_PATH ?? '' }` — vazio por padrão (build "canônico", pro
   futuro cutover em `/ui`), `/ui-novo` só quando buildado explicitamente com
   `BASE_PATH=/ui-novo` pra esse preview lado-a-lado. **Gotcha registrado**: `BASE_PATH=/ui-novo npm run build`
   direto no Git Bash quebra — o MSYS mangling converte `/ui-novo` pra
   `C:/Program Files/Git/ui-novo` antes do Node ver a variável. Rodar via PowerShell
   (`$env:BASE_PATH = "/ui-novo"`) evita o problema.
2. **500 em `GET /auth/status`**: `UserRepository.count()` assumia que o resultado de
   `SELECT count() FROM users GROUP ALL` sempre vinha como lista de dict. Nesta instância do
   SurrealDB, consultar uma tabela que nunca teve um `CREATE` (exatamente o estado de
   primeiro boot — zero usuários) devolve status `ERR` com `result` = string de erro, não
   lista — `SurrealClient.result()` não distingue OK de ERR, só desembrulha `result` do jeito
   que vier. `dados[0].get(...)` estourava `AttributeError` porque `dados[0]` era a própria
   string do erro. Corrigido em `utils/auth.py`: `count()`/`get_by_username()` checam
   `isinstance(dados[0], dict)` antes de tratar como registro — "tabela não existe" e "sem
   usuários" são semanticamente a mesma coisa aqui, então vira 0/`None`, não crash.

**Ferramenta usada pra achar os dois**: Playwright headless apontado pro `127.0.0.1:8000`
real (não mock), capturando `page.on('response')` com status ≥400 e `console`/`pageerror`.
Sem isso os dois bugs só apareceriam quando o usuário testasse manualmente.

**Lição operacional registrada**: `lsof`/`kill` do Git Bash NÃO enxergam processos Windows
nativos (`python.exe` rodando `cerebro_maestro.py`) — várias tentativas de "reiniciar o
backend" silenciosamente falharam em derrubar o processo antigo (a porta já estava em uso,
o `nohup` novo crashava ao tentar bindar, e o processo velho continuava respondendo,
mascarando completamente que a mudança não tinha efeito nenhum). Método que funciona:
PowerShell `Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object
{ $_.CommandLine -like '*cerebro_maestro*' } | Stop-Process -Force`.

Estado atual: backend rodando com `/ui` (React v2, produção, intocado) e `/ui-novo`
(SvelteKit, preview) simultâneos, mesma origem, ambos funcionando. Tela de setup
(`/auth/setup`) renderizando e funcional contra dados reais.

### Grafo de memória "girando e tremendo" — bug real, corrigido (2026-08-12)

Usuário testou o painel Grafo de verdade e reportou tremor/giro constante. Causa: a
simulação de força nunca esfriava — rodava a ~60fps pra sempre, mesmo já estabilizada,
igual todo layout de força precisa de decaimento (`alpha`) pra parar (d3-force faz isso,
eu tinha esquecido). Dois problemas reais no `GraphPanel.svelte`:

1. **Sem decaimento**: loop rodava indefinidamente, sem nunca "congelar" o layout final.
2. **Sem clamp de velocidade**: quando 2 nós ficavam muito próximos (`distSq` perto do piso
   de 1), a repulsão gerava um salto de velocidade gigante num frame só — os nós se
   afastavam violentamente e a atração dos links puxava de volta com força igual no frame
   seguinte, um "ping-pong" que lia como tremor/explosão, não instabilidade sutil.

Corrigido: `alpha` começa em 1, decai (`×0.985`) a cada passo, o loop para de vez
(`animando = false`, nem desenha mais) quando `alpha < 0.01` — layout fica parado depois de
estabilizar, sem custo de CPU residual. Velocidade por nó limitada a 8px/frame antes de
aplicar a posição.

Self-check (assert-based) verificou: clamp de velocidade segura um caso extremo de
sobreposição sem "explodir" além do limite; `alpha` esfria em tempo finito (não roda pra
sempre) — 305 passos (~5s a 60fps) num grafo sintético de 30 nós/25 links.

**Verificado contra dado real, não sintético**: `/grafo/completo` real tem 289 nós / 436
links (bem mais denso que qualquer coisa testada antes) — Playwright abriu o painel contra
o backend de verdade, comparou o canvas em 5s e 7s: praticamente idêntico (só diferença
sub-pixel, imperceptível — não mais o tremor). Layout final: rede legível, nó central
(hub) com muitas conexões, nós periféricos espalhados — exatamente a estrutura que um
grafo de eventos/tópicos deveria mostrar.

## Auditoria de paridade com Open WebUI (2026-08-12)

Usuário pediu pra olhar o Open WebUI de novo e comparar de verdade (não de memória) — usei
um agente Explore pra ler a árvore real de componentes/rotas do clone em `TESTE/`. Resultado
categorizado:

**Inaplicável** (Open WebUI é multi-usuário/empresa; Lyra é single-user): gestão de
usuários/grupos/RBAC, analytics de uso entre várias pessoas, leaderboard de modelos votado
coletivamente, canais estilo Slack, admin de auth/DB/pipelines nível empresa, compartilhamento
de chat com controle de acesso.

**Real e valioso, ainda faltando em Lyra** (lista completa, não implementada toda ainda):
biblioteca de prompts salvos, upload de documento pra RAG com UI própria (Lyra tem grafo de
memória, não é a mesma coisa), editor de tools/functions custom in-app, personas por modelo
(system prompt + tools salvos como preset nomeado), app de notas com IA, calendário,
automações agendadas, branching de resposta (múltiplas regenerações lado a lado), citações
inline pra RAG, execução de código no chat (Pyodide/terminal), painel de artifacts lateral
(Lyra tem preview inline, não painel separado), tags/pastas de conversa, playground de
completions isolado do chat, composer rich-text.

- [x] **2026-08-12** **Biblioteca de prompts salvos** — implementada (primeiro item da lista,
      mais autocontido e claramente esperado). Backend: tabela `prompt` nova (aditiva),
      `routers/prompts.py` (`GET/POST /prompts`, `PATCH/DELETE /prompts/{id}`). Frontend:
      `PromptLibraryPanel.svelte` — criar/editar/excluir, clique insere o conteúdo no
      composer e fecha o painel. Sem autocomplete de "/comando" digitado (o Open WebUI tem
      isso, aqui ficou só clique — mais simples, mesmo valor pro caso de uso real: "guardar
      pergunta que eu repito bastante"). Verificado contra o backend real (não mock): criar,
      listar, editar, excluir, e inserir no composer — todo o ciclo rodou contra o SurrealDB
      de verdade, incluindo exclusão pela própria UI.
- [ ] Resto da lista (personas por modelo, notas, calendário, automações, branching,
      execução de código, tags/pastas) — não implementado, escopo grande demais pra decidir
      sozinho o que priorizar; fica pra próxima rodada com direção do usuário.

## Notas gerais

- Toda mudança de schema deve ser aditiva (seção 12.1) — nunca remover/renomear campo que
  código antigo ainda lê.
- Tirar snapshot SurrealDB+Qdrant (pasta `snapshots/`) antes de qualquer mudança de schema real.
- Código em POO, nomes/estrutura claros o bastante pra qualquer programador entender sem
  contexto prévio — pedido explícito do usuário nesta fase (2026-08-11).
