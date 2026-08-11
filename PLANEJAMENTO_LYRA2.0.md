# PLANEJAMENTO_LYRA2.0

Data: 2026-08-11
Status: rascunho para decisão do arquiteto (usuário) — nada implementado ainda.

## 1. Objetivo deste documento

Analisei 5 projetos de referência salvos em `TESTE/` (LibreChat, AnythingLLM, Jan, Open WebUI, OpenClaw) para decidir o que vale a pena trazer para a Lyra — especialmente **login/autenticação**, que hoje a Lyra **não tem** (confirmado: nenhum arquivo de auth/JWT/sessão real no backend, fora ruído de `node_modules`).

Resumo de cada referência, o que aproveitar, e uma proposta de arquitetura "Lyra 2.0".

## 2. Estado atual da Lyra (baseline)

- **Backend**: FastAPI monolítico, arquivos soltos na raiz de `Lyra_Ollama/` (`cerebro_maestro.py`, `rag_engine.py`, `surreal_client.py`, `session_manager.py`, `llm_cascade.py`, etc). Sem pastas `routers/`/`models/`/`utils/` — tudo flat.
- **DB**: SurrealDB (dados relacionais/documento) + Qdrant (vetores, ~3M embeddings BGE-M3) + Ollama (modelos locais).
- **Frontend**: React + Vite (`Front_end_Lyra_v2`), servido same-origin pelo backend em `/ui`.
- **Desktop**: Eclipse Theia (Electron) virando IDE própria, com o frontend da Lyra embutido via iframe/widget (`lyra-chat-ext`).
- **Auth**: inexistente. Single-user implícito, sem tela de login, sem sessão.
- **Regra de rede**: só 127.0.0.1 (sem exposição externa hoje).

## 3. Referências analisadas

### 3.1 Open WebUI (a mais relevante — mesma stack: FastAPI + Python)

- **Arquitetura**: `routers/` (endpoints) + `models/` (SQLAlchemy + Pydantic, 1:1 com routers) + `utils/` (`auth.py`, `access_control.py`) + `internal/` (DB engine) + Alembic migrations. Config fica no banco (tabela `Config`), não só em `.env`.
- **Auth**: email+senha (bcrypt/argon2) é a base. JWT (HS256) em cookie httpOnly + Bearer, com `jti` e revogação via Redis. Dependency `get_current_user` central que todo endpoint usa. Roles simples: `admin` / `user` / `pending`. Primeiro cadastro vira admin automaticamente (com proteção contra race condition). Também suporta LDAP, OAuth/OIDC, SCIM, API keys — mas isso é overkill para nós.
- **Frontend**: SvelteKit, uma única página `auth/+page.svelte` alternando entre login/signup por estado local, não rotas separadas. Store simples (`writable`) guardando `user` + token.
- **O que aproveitar**: exatamente o "subset mínimo" — bcrypt + JWT em cookie httpOnly + 1 dependency de auth + campo `role` simples. É o modelo mais próximo do que a Lyra precisa, e a arquitetura `routers/models/utils` é um bom próximo passo de organização pro backend hoje flat.
- **O que ignorar**: LDAP, OAuth/OIDC, SCIM, Redis para revogação, config dinâmico no banco.

### 3.2 LibreChat

- **Arquitetura**: Node/Express + MongoDB, monorepo pesado (Turborepo), migração JS→TS em andamento, dois state managers no frontend (Jotai + Recoil legado — sinal de dívida técnica).
- **Auth**: Passport.js com 7+ estratégias (local, JWT, Google, GitHub, Discord, Facebook, Apple, SAML, LDAP, OIDC genérico), refresh tokens com sessão no Mongo, 2FA com backup codes, rate limiting por rota de auth.
- **O que aproveitar**: nada de auth diretamente (excesso de escopo pra 1 usuário). Vale só o **padrão de tema** (tokens semânticos light/dark versionados) e a ideia de artifacts/painel de código no chat, se um dia a Lyra quiser algo assim.
- **Vereditco**: enterprise multi-tenant, não é o caminho pra Lyra.

### 3.3 AnythingLLM

- **Arquitetura**: Node/Express + Prisma (SQLite/Postgres), 3 processos (`server`, `collector` isolado pra parsing de documento, `frontend` React buildado pro `server/public`).
- **Auth**: dois modos — single-user (senha única via `AUTH_TOKEN` + JWT, sem tabela de usuário real) e multi-user (tabela `users` com bcrypt + JWT, convite por código, reset de senha com backup codes, workspace-level permissions).
- **O que aproveitar**: o **modo single-user** é literalmente o formato mais simples que existe — 1 senha, sem tabela de usuário. Bom fallback se quisermos "proteção mínima" sem sistema de conta completo. O padrão de abstração por provider (um arquivo por vector DB/embedding engine, interface comum) é elegante mas desnecessário — a Lyra já decidiu Qdrant + Ollama, não precisamos de camada de troca de provider.
- **Vereditco**: útil como inspiração de "modo simples", mas o resto (multi-processo, convites, workspaces) é infraestrutura demais pra Lyra hoje.

### 3.4 Jan (Tauri desktop)

- **Arquitetura**: Tauri 2 (Rust) + React 19/Vite/TanStack Router, com duas camadas de extensão (contrato JS + plugins Rust nativos). Backend Rust expõe comandos via `invoke` (filesystem, settings, secrets, download de modelo, servidor HTTP local compatível com OpenAI API).
- **Auth**: nenhuma. 100% local, sem conta, sem sync — só chaves de API de provedores de nuvem opcionais, guardadas via comando Rust (não em localStorage).
- **O que aproveitar (não é sobre login, é sobre virar desktop)**:
  - Padrão de comandos Tauri pra guardar segredos fora do webview/localStorage — relevante porque a Lyra também está virando app desktop (Theia/Electron).
  - Settings persistidos no lado nativo (Rust), não só no frontend — ideia equivalente: o backend FastAPI da Lyra já pode ser o "dono" da config, o Electron/Theia só orquestra.
  - Servidor HTTP embutido (`localhost:1337`) é exatamente o que a Lyra já tem (`cerebro_maestro.py` rodando local) — Theia só precisa subir/gerenciar esse processo, não reinventar.
  - Confirma que **não precisar de login é uma escolha válida e usada por um projeto sério** — reforça a opção "B" abaixo.

### 3.5 OpenClaw

O mais próximo conceitualmente da Lyra: assistente pessoal single-user, "always-on", que fala em vários canais (WhatsApp, Telegram, Slack, Discord etc). Diferente dos outros 4, não é um clone de chat-UI — é um daemon de controle (Gateway) com clientes leves em volta.

- **Arquitetura**: Node/TypeScript, um daemon único (`openclaw gateway`, `127.0.0.1:18789`) dono de todas as sessões/canais, expondo uma API WebSocket tipada (schema TypeBox → JSON Schema → modelos gerados até pra app iOS). CLI, app Windows Hub, Control UI web, dispositivos — tudo é cliente WS do Gateway. Um único Gateway por máquina, roda como serviço (systemd/launchd).
- **Auth/segurança (a parte mais valiosa pra Lyra)**:
  - **Conexão ao Gateway**: token/senha compartilhado, ou modos com identidade (Tailscale, header de proxy confiável). Loopback local pode auto-aprovar; conexão de fora da máquina sempre exige pareamento explícito.
  - **Pareamento de dispositivo/node**: todo cliente WS novo gera um pedido pendente, aprovado manualmente (`openclaw nodes approve <id>`) ou pela Control UI. Aprovação emite um token de dispositivo rotativo; toda conexão futura assina um desafio (nonce). Pareamento mobile usa **QR code / código base64** com a URL do gateway + token de bootstrap de uso único (expira em 10 min) — isso é literalmente o padrão que a Lyra pode usar se o Theia/Electron ou um futuro app mobile precisar se conectar ao backend sem digitar senha toda vez.
  - **Segredos**: em vez de credencial em texto puro no código, usa `SecretRef` (`{source: env|file|exec, provider, id}`) resolvido uma vez em memória no start. Chaves de provedor de modelo viram **sentinelas opaças** (`oc-sent-v1-...`) que aparecem em logs/config no lugar do valor real, só desembrulhadas no ponto final de rede. Documentação é honesta: isso não é isolamento de processo — segredo em texto puro no `.json`/`.env` ainda é legível por quem tem acesso ao filesystem/ferramentas do agente.
  - **Pareamento por canal (DM pairing)**: separado do pareamento de dispositivo — contato desconhecido em um canal (ex: WhatsApp) recebe um código de 8 caracteres, dono aprova, vira "owner" do canal. Não se aplica à Lyra hoje (sem canais externos), mas é o mesmo padrão de "aprovação manual do primeiro acesso" do setup inicial do Open WebUI (seção 3.1).
- **Sistema de skills**: pasta `skills/` com um `SKILL.md` por skill (frontmatter YAML + instruções em markdown) — é exatamente o mesmo formato do sistema de Skills que eu (Claude Code) uso nesta sessão. Separado de "plugins" (capacidades de runtime tipadas via JSON Schema, ex: canais, providers). Vale comparar com o sistema de tools/agentes que a Lyra já tem (`lyra_tools.py`, `lyra_agentes.py`) — dá pra adotar convenção `SKILL.md` se algum dia quiser portabilidade/documentação melhor das tools da Lyra.
- **Onboarding**: wizard guiado via terminal (`openclaw onboard`), cada etapa pulável/retomável depois. No Windows, um app nativo "Hub" substitui o wizard de CLI — companion app com tray, status, chat, pareamento.
- **O que é irrelevante pra Lyra**: toda a camada de adaptadores de canal de mensagem (WhatsApp/Telegram/Slack/Discord/Signal/iMessage/...) — a Lyra não é um bot multi-canal, isso não se aplica.

## 4. A pergunta central: a Lyra precisa de login?

Duas leituras possíveis do que o usuário pediu ("tem algo que todas têm que a Lyra não tem, o login"):

- **(A) Login = proteção de acesso.** A Lyra roda local (127.0.0.1) hoje, mas se vai virar app desktop redistribuível, ou se algum dia expõe a rede, uma tela de login com senha é a peça que falta pra não ser "qualquer um que abrir o app entra".
- **(B) Login = identidade multi-usuário.** Diferente de (A), aqui a ideia é ter contas separadas (ex: você e outra pessoa usando a mesma instância, cada um com seu histórico).

**Decidido em 2026-08-11: (A) proteção de acesso.** Sem multi-usuário — 1 conta admin, senha protege o app. Simplifica a seção 5: `role` na tabela `users` fica só de futuro-proofing, não precisa de lógica de permissão por enquanto.

## 5. Proposta de arquitetura mínima de auth para a Lyra

Baseado no subset do Open WebUI + modo single-user do AnythingLLM:

1. **1 tabela `users` no SurrealDB** (não precisa de banco novo): `username`, `password_hash` (bcrypt), `role` (`admin`/`user`, default `admin` já que é o primeiro), `created_at`.
2. **JWT em cookie httpOnly** (não localStorage — evita XSS pegar o token), assinado com secret em `.env`. Expiração longa (ex: 30 dias) já que é app pessoal, sem necessidade de refresh token separado.
3. **1 dependency FastAPI** (`get_current_user`) que todo endpoint protegido usa — modelo `utils/auth.py` do Open WebUI, sem LDAP/OAuth/SCIM.
4. **1 rota de login + 1 rota de setup inicial** (se não existe nenhum user, primeira tela é "criar conta admin", não "fazer login" — como Open WebUI faz).
5. **Frontend**: 1 página de login (React), guarda estado de auth num Context/store simples (o que a Lyra já usa), redireciona pra `/login` se 401.
6. **Fora de escopo agora** (adicionar só se necessidade real aparecer): multi-usuário de verdade, OAuth, 2FA, convites, LDAP, rate limiting dedicado, revogação de token via Redis.

Isso é o menor sistema de auth que resolve "abrir o app pede senha" sem herdar a complexidade enterprise de LibreChat/Open WebUI completos.

**Complemento do OpenClaw**: se o app desktop (Theia/Electron) ou algo mobile precisar se conectar ao backend da Lyra sem digitar senha toda hora, o padrão de **pareamento por QR/token de uso único** (seção 3.5) é o próximo passo natural depois do login básico — mais seguro que guardar a senha eterna no cliente. E o padrão de `SecretRef`/sentinela vale considerar pra guardar as API keys de fallback cloud (Groq/Gemini/Claude) hoje provavelmente em `.env` puro — não é urgente, mas é uma melhoria barata.

## 6. Reorganização de backend (opcional, mas facilita auth)

Hoje o backend é flat. Para adicionar auth de forma limpa, vale considerar (inspirado no Open WebUI, mas SEM exagerar):

```text
Lyra_Ollama/
  routers/       # novo: auth.py, chat.py (mover endpoints do cerebro_maestro.py)
  models/        # novo: schemas Pydantic (User, Token, etc)
  utils/         # novo: auth.py (hash, JWT, dependency)
  cerebro_maestro.py  # continua sendo o entrypoint, só importa os routers
```

Isso é uma decisão separada do login em si — dá pra fazer o login mínimo direto no `cerebro_maestro.py` também, sem reorganizar nada, se preferir menos mudança agora.

## 7. Sobre o frontend "Lyra 2.0" em geral

Nenhuma das referências sugere trocar a stack atual (React+Vite está alinhado com todas). Ideias soltas vale considerar independente do login:

- Tema com tokens semânticos versionados (LibreChat) — já que a Lyra vai ter dark/light.
- Settings organizados por sub-rota (Jan) se a tela de configurações crescer.
- Tela de onboarding/first-run (Open WebUI: "criar conta admin" na primeira execução) — resolve tanto o login quanto uma boa primeira impressão do app.
- Pasta `skills/` estilo `SKILL.md` (OpenClaw) pra documentar as tools/agentes da Lyra de forma portável, se algum dia quiser reaproveitar em outro host além do Claude Code.

## 9. O que é GENUINAMENTE NOVO pra Lyra (features que faltam, com código pra reaproveitar)

Verifiquei o que a Lyra já tem hoje (grep no backend `Lyra_Ollama/` e no frontend `Front_end_Lyra_v2/src/`) pra separar "padrão que já existe, só organizado diferente" de "capacidade que não existe". Lista abaixo é só o que falta de verdade, com o arquivo de origem pra copiar/adaptar.

1. **Upload de documento → base de conhecimento, com barra de progresso.** Hoje a Lyra só lê documento se você apontar um `path` (`tools/documents.py: ler_documento/resumir_documento`) ou ingere web docs via script manual (`ingest_webdocs.py`, rodado no terminal). Não existe: arrastar um PDF/DOCX pro chat e ele virar embeddings no Qdrant automaticamente, com indicador de progresso.
   - Reaproveitar: `TESTE/anything-llm/collector/` (parsing de arquivo → texto), `server/utils/DocumentManager/`, `server/utils/TextSplitter/` (chunking), e principalmente `frontend/src/EmbeddingProgressContext.jsx` (React, direto reaproveitável já que a Lyra também é React) pro indicador de progresso. Backend é Node — dá pra portar a lógica de chunking pra Python (ou simplificar, já que a Lyra usa `embed_service.py` própria em vez de multi-provider).

2. **Painel de Artifacts / canvas de código.** Nenhum componente em `Chat.tsx`/`RightPanel.tsx` renderiza código/HTML num painel sandboxed separado da mensagem de chat.
   - Reaproveitar: `TESTE/LibreChat/client/src/` (buscar por `Artifacts` — painel de preview de código/HTML renderizado em iframe sandboxed ao lado do chat). É o recurso mais "uau" visualmente das referências e a Lyra não tem nada parecido.

3. **Hub de modelos (buscar/baixar modelo Ollama pela UI).** `SettingsModal.tsx` só tem um `<select>` com modelos já configurados — não existe descoberta/pull de modelo novo pela interface.
   - Reaproveitar: `TESTE/jan/web-app/src/routes/hub` (busca/ranking) + `TESTE/jan/src-tauri/src/core/downloads` (máquina de estado de download com progresso) — dá pra adaptar pra chamar `ollama pull` com progresso via o WebSocket que a Lyra já tem.

4. **Favoritar/fixar/marcar conversas.** `Sidebar.tsx` lista conversas mas não tem favorito, tag, ou pin — só existe busca (`SearchOverlay.tsx` já cobre isso parcialmente).
   - Reaproveitar: modelo de dados de `sharedLink`/pin do LibreChat (`packages/data-schemas/src/schema/`) ou o padrão mais simples de `workspace`/thread do AnythingLLM.

5. **Painel de MCP servers (ativar/desativar, listar tools disponíveis).** A Lyra já expõe MCP (`cerebro_maestro.py`, seção "MCP (Model Context Protocol)") e já tem um registry de tools (`tools/_registry.py`, `_lazy.py`) — mas não tem UI pra ver/ligar/desligar isso.
   - Reaproveitar: `TESTE/jan/web-app/src/routes/settings/mcp-servers` (tela de ativar/desativar servidor MCP e listar tools).

6. **Monitor de sistema / logs dentro do app.** Hoje log é só `maestro.log`/`maestro.err` em arquivo texto, sem viewer.
   - Reaproveitar: `TESTE/jan/web-app/src/routes/system-monitor` e `routes/logs` (telas prontas de diagnóstico local).

7. **Onboarding de primeira execução.** A Lyra não tem nenhuma tela de "primeiro uso" — hoje só funciona.
   - Reaproveitar: fluxo `openclaw onboard` (conceito, é CLI) ou mais aplicável: a tela de "criar conta admin no primeiro boot" do Open WebUI (`src/routes/auth/+page.svelte`, ligado ao `ENABLE_SIGNUP`/contagem de usuários zero) — resolve onboarding E login ao mesmo tempo, junto com o item 1 do plano de auth (seção 5).

8. **Pareamento de dispositivo (QR/token) pra desktop e um futuro mobile.** Já coberto na seção 3.5/5 — é capacidade nova de verdade, não só padrão. Reaproveitar o desenho (não o código, que é TypeScript/WS específico do Gateway) de `TESTE/openclaw` — pareamento por QR + token de bootstrap de uso único.

9. **Segredos como referência (`SecretRef`) em vez de texto puro no `.env`.** Hoje as chaves da cascata (Groq/Gemini/Claude) provavelmente estão em texto puro no `.env`/`config.py`. Não existe camada de indireção.
   - Reaproveitar: o conceito de `SecretRef` do OpenClaw (não achei o arquivo fonte exato — está compilado em `dist/` — mas o padrão é simples de reimplementar em Python: uma função `resolve_secret({source, provider, id})` chamada uma vez no boot).

**O que eu NÃO colocaria nessa lista** (já existe ou não se aplica): multi-canal de mensagem (Lyra já tem `lyra_telegram.py`, e não precisa de WhatsApp/Slack/Discord); abstração multi-vector-DB (Lyra já decidiu Qdrant); multi-LLM-provider genérico (Lyra já tem `llm_cascade.py` fazendo isso); tema dark/light (já existe, só falta o padrão de tokens versionado da seção 7).

## 10. Cenário ideal — decisão do arquiteto (2026-08-11)

Pergunta: se pudéssemos mudar tudo, sem peso de "dar muito trabalho", qual o desenho perfeito? Decisão tomada:

- **Backend: continua Python + FastAPI.** Não é concessão — é a escolha certa mesmo do zero, porque todo o ecossistema de IA (Ollama, embeddings, RAG) é nativo em Python. Open WebUI (seção 3.1) prova que dá pra ter essa stack exata bem organizada. Muda a **organização**: sair do flat atual (`Lyra_Ollama/*.py` solto) pra `routers/models/utils` (seção 6), e adotar o padrão **Gateway** do OpenClaw (seção 3.5) — 1 processo dono de todo estado (SurrealDB/Qdrant/Ollama/sessões) expondo uma API WebSocket tipada, em vez de REST+SSE solto como hoje.
- **DB/engine: continua SurrealDB + Qdrant + Ollama + cascata cloud (Groq→Gemini→Claude).** Nenhuma das 5 referências tem algo melhor pra esse caso — confirmado, não muda.
- **Frontend: migra pra SvelteKit** (decidido). Sai do React+Vite atual (`Front_end_Lyra_v2`). Motivo: bundle menor, menos boilerplate, mais leve rodando local — é o que Open WebUI e o Control UI do OpenClaw usam pro mesmo tipo de app. Todos os componentes novos da seção 9 (upload/progresso, artifacts, hub de modelo, favoritos, painel MCP, monitor, onboarding) nascem direto em Svelte, não em React — não vale a pena portar o React atual, é reescrita completa da camada de UI.
- **Desktop: os DOIS produtos, assistente E IDE** (decidido — não é ou/ou como eu tinha sugerido).
  - **Theia continua sendo a casca da IDE** (`Lyra_IDE`, já em andamento, Fase C) — é a ferramenta certa pra isso, tem ecossistema de extensão de verdade. Dentro dela, o painel `lyra-chat-ext` passa a carregar o novo frontend **SvelteKit** (troca o iframe React atual).
  - **Empacotamento leve via Tauri** pro modo "só assistente" (sem a IDE completa) — reaproveitando o **mesmo frontend SvelteKit**, já que ele fica desacoplado do shell. Ou seja: 1 frontend Svelte, 2 cascas nativas (Theia pra quem quer a IDE, Tauri pra quem quer só o assistente rodando leve). Padrão de secrets/settings nativos do Jan (seção 3.4) serve de referência pra essa casca Tauri.

## 11. Próximos passos (aguardando sua decisão)

1. ~~Confirmar leitura (A) vs (B) da seção 4~~ — feito, (A) proteção de acesso.
2. **`git init` no `C:\Lyra_Project` + primeiro commit, antes de tocar em qualquer código.** Sem isso, reescrita de backend/frontend não tem como reverter erro nem comparar antes/depois. Custa zero, faz agora.
3. **Backend primeiro** (ordem confirmada pelo usuário): reorganizar `Lyra_Ollama/` em `routers/models/utils` (seção 6), depois implementar auth mínimo (seção 5) e o padrão Gateway/WS tipado (seção 10) por cima. Frontend Svelte só começa depois disso ter uma API estável pra consumir — evita retrabalho.
4. Depois do backend estável: reescrever frontend em SvelteKit (seção 10), já nascendo com a tela de login/onboarding do item 3 em vez de portar o React antigo primeiro.
5. Integrar o frontend novo nas duas cascas: Theia (`lyra-chat-ext`) e Tauri (novo, modo assistente leve) — ver seção 12.3 pra como evitar duplicar código entre as duas.
6. Depois do básico rodando, avaliar pareamento QR/token (seção 3.5) pra conexão entre as cascas e um futuro mobile.

## 12. Pontos que faltavam pensar (aprofundado em 2026-08-11)

### 12.1 Dados existentes (SurrealDB + Qdrant) durante a reescrita

Nenhum dado precisa "migrar" de verdade — SurrealDB e Qdrant continuam sendo os mesmos bancos, no mesmo lugar; só a camada de código por cima (routers, Gateway) muda. Regra pra não quebrar nada: toda mudança de schema durante a reorganização tem que ser **aditiva** (nova tabela `users`, novos campos com default) — nunca remover/renomear campo que o código antigo ainda lê, até o corte estar 100% completo. Antes de começar a mexer no backend: tirar um snapshot do SurrealDB e do Qdrant (o projeto já tem pasta `snapshots/` — usar) como ponto de restauração.

### 12.2 Empacotamento `.exe` / instalador (pergunta antiga, agora relevante com Tauri)

Decisão: **o instalador não carrega os 3M+ vetores por padrão.** Ele instala o app (Theia ou Tauri) e conecta no Qdrant/SurrealDB que já existem na máquina — pra quem já usa a Lyra, é só atualização de app, dado fica onde está. Pra instalar do zero num PC novo, fica como opção separada e não bloqueante: "começar vazio" (mais rápido, a Lyra reaprende com o tempo) ou "importar snapshot" (pesado, ~2-3GB, só se o usuário pedir explicitamente). Não precisa decidir isso agora — só não acoplar o instalador ao tamanho do banco.

### 12.3 Evitar duplicar código entre as duas cascas (Theia + Tauri)

Mesmo problema que o Jan resolveu (seção 3.4): frontend não pode saber em qual casca está rodando. Solução: uma interface JS fina e comum — algo como `getSecret()`, `setSetting()`, `startBackend()` — implementada duas vezes por baixo (uma fala com o processo principal do Electron/Theia, outra com comandos Tauri/Rust). O Svelte só chama a interface, nunca a implementação. Isso é trabalho de definir 1 contrato antes de escrever a primeira linha de casca nova, não depois.

### 12.4 Critério de corte do frontend React atual

`Front_end_Lyra_v2` (React) continua rodando até o Svelte ter paridade de feature testada — mesmo critério que já estava no plano antigo (fase "04 Paridade com v1" da memória `lyra_frontend_v2_plano`). Só vai pra `_lixeira/` depois de uso real confirmado por alguns dias sem bug crítico. Não apagar nada antes disso.

### 12.5 Fase IDE (LSP, terminal, debug) — já decidida antes, só não estava neste documento

Puxando da memória do projeto (decisão já confirmada com o usuário antes desta sessão): terminal real via `pywinpty`/ConPTY↔`xterm.js` (não `executar_comando` de uma tacada); autocomplete via `pyright-langserver --stdio`↔`monaco-languageclient` (só Python de início); seletor de interpretador via `GET /ide/interpreters`; debug (DAP) fica pra depois, não bloqueia nada. Isso é a "casca Theia" ficando de verdade uma IDE, além de só hospedar o assistente.

### 12.6 Footprint de rodar tudo junto

Backend + SurrealDB + Qdrant + Ollama + (Theia ou Tauri) rodando ao mesmo tempo na máquina do usuário ainda não foi medido. Não bloqueia o início (backend é prioridade agora), mas vale medir RAM/CPU idle de cada casca isolada quando a Fase de integração (item 5 acima) chegar, pra decidir se algum serviço deveria subir sob demanda em vez de sempre ligado.
