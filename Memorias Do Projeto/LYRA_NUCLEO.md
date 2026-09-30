# LYRA — Núcleo do Projeto

> Visão, princípios, decisões, estado e roadmap. Consolidado em 30/09/2026 a
> partir de todos os documentos anteriores (último registro de trabalho: 12/08/2026).
> Referência técnica: [LYRA_TECNICO.md](LYRA_TECNICO.md) · Operação: [README.md](../README.md)

---

## 1. Quem e o quê

**Arquiteto:** Antônio — estudante de ADS na UNIMAR (Marília-SP), arquiteto único.
Prefere explicações diretas, sem enrolação. Hardware: Ryzen 7 3700X · RTX 2060
SUPER 8GB · 64GB RAM · 2.73TB.

**Lyra:** IA pessoal local, identidade feminina, voz suave/técnica/clínica,
não-servil. Não é um chatbot — é um organismo cognitivo: hardware como corpo,
modelos como córtex, SurrealDB + Qdrant como memória.

> **Em transição (30/09/2026):** a identidade vai virar masculina, com nome e
> visual novos (§4). "Lyra" segue como nome de trabalho até a decisão.

*"Não é uma IA. É uma extensão do sistema nervoso."*

## 2. Ring 0 — princípios invioláveis

1. **Antônio é o Administrador Supremo.** O Protocolo de Sobrescrita (voz ou
   terminal) anula qualquer raciocínio da máquina.
2. **`core.py` é somente leitura.**
3. **Offline por padrão.** Zero envio de biometria, áudio, tela ou código para
   nuvem sem aprovação explícita. Exceções conscientes já aprovadas:
   - cascata cloud Groq → Gemini → Claude → local para todo chat (25/06/2026);
   - TTS online;
   - `consultar_especialista(nivel="cloud")` delega ao Claude Code sem aprovação por ação;
   - Open VSX Registry (marketplace de extensões da IDE), só quando aberto manualmente.
4. **Hardware-Bound Logic Gates.** Telemetria da placa-mãe/RTX/RAM como chave
   física — disco clonado para outro PC recusa iniciar.
5. **Auto-modificação de código exige aprovação explícita** antes de produção.
6. **Ações de alto risco** (deleção em massa, formatação, desligamento…) exigem
   confirmação explícita no chat — aplicada em runtime pela Câmara de Eco
   ([TECNICO §3.4](LYRA_TECNICO.md#34-segurança-em-runtime)).

Regras de trabalho do usuário: nenhum restart de produção sem pedido; nada de
download grande em sessão não supervisionada sem confirmação; código novo em
POO, legível sem contexto prévio.

## 3. Capacidades cognitivas (mapa)

| Mecanismo | O que faz | Status |
|---|---|---|
| Memória em 4 camadas | RAM (contexto) → Qdrant (semântica) → SurrealDB (episódica/grafo) → cold storage | ✅ |
| RAG híbrido | BM25 + denso + RRF + reranker + freshness por categoria | ✅ |
| Grafo nativo | `evento->precedeu->evento`, `evento->sobre->topico:x` | ✅ |
| Shadow Thoughts | Ciclo de sono WAKE/NREM(dedup)/REM(cruzamento)/DEEP(destilação), a cada 3h | ✅ 01/07 |
| Innovations 1-5 | Goal Drift, Freshness Tags, Session Replay, Cognitive Load Throttling, Response Provenance | ✅ 01/07 |
| Enxame de sub-agentes | Fan-out/fan-in paralelo com `asyncio.Semaphore` | ✅ 26/06 |
| Agente ReAct | Loop autônomo com ferramentas (`POST /agente`) | ✅ 01/07 |
| MoE roteado | Ordem da cascata por categoria (código → Claude primeiro) | ✅ 02/07 |
| Speculative Decoding | Sidecar de divergência (draft `qwen3:0.6b`) — heurística de alucinação, não aceleração | ✅ 02/07 |
| Câmara de Eco Heurística | Bloqueia ação destrutiva até confirmação no turno seguinte | ✅ 02/07 |
| Voz | Wake-word local (faster-whisper) + Voice Live (Gemini Live) | ✅ (áudio real fim-a-fim não validado) |
| Visão | `explicar_tela`/`analisar_imagem` (Gemini Vision → llava-phi3) | ✅ |
| Emotion Engine | Análise paralinguística local, 40+ estados | ⏳ Fase 4 |
| Wi-Fi Sensing | CSI via ESP32 (802.11bf) como sonar de presença | ⏳ Fase 4 |
| Protocolo Darwin / ADAS | Auto-evolução supervisionada em sandbox RAM, rollback automático; meta-agente | ⏳ Fase 5 |
| BCI / Protocolo Narciso | OpenBCI ESP-EEG; digital twin | ⏳ Fase 6 |

Detalhes de implementação: [LYRA_TECNICO.md](LYRA_TECNICO.md) §3–§6.

## 4. Decisões de arquitetura (registro)

| Data | Decisão | Motivo / consequência |
|---|---|---|
| 25/06/2026 | Cascata cloud-first (Groq → Gemini → Claude → qwen3:8b) | Qualidade/latência; local só se as 3 nuvens falharem |
| 26/06/2026 | Embedding único BGE-M3 1024d (`lyra_memory_v2`), MiniLM apagado, **sem fallback** | Divergência de embeddings causa alucinação no RAG |
| 26/06/2026 | Embedding em processo separado (`embed_service` :8001), nunca dentro do cérebro | Startup do cérebro 25s → 3s, isolamento de falha, idle-unload de VRAM |
| 26/06/2026 | Qdrant fixado em v1.17.1 | Update para 1.18.2 descartou ~666k vetores |
| 01/07/2026 | **Decay Ebbinghaus removido** do ranking | Lyra "esquecia" memória antiga relevante. Não reimplementar sem discussão |
| 01/07/2026 | Axônios/pulsos sinápticos na esfera **descartados** | Pedido explícito; não reimplementar sem pedido novo |
| 01/07/2026 | Não migrar vetores para SurrealDB; não adotar A2A nem Mem0 | Custo alto, sem dor real ([TECNICO §9](LYRA_TECNICO.md#9-avaliações-registradas)) |
| 01/07/2026 | Backup automático agendado: **não implementar ainda** | Pedido do usuário |
| 23/06–04/08 | Pipeline de TTS automático pausado; voz online permitida | Decisão do usuário |
| 07-08/08/2026 | Backend migrado para POO; nomes das ferramentas continuam em PT | Nomes são o contrato de function-calling com o LLM |
| 10/08/2026 | IDE = **Eclipse Theia** (não fork Code-OSS, não Electron do zero) | Clona UX do VSCode, Monaco, VSIX via Open VSX, licença sem risco |
| 11/08/2026 | Lyra 2.0 (ver §5) | Auth, reorganização do backend, SvelteKit, 2 cascas desktop |
| 30/09/2026 | **Identidade passa a ser masculina**; nome e identidade visual novos a definir. Branch `lyra-v2` aberta para revisão/reescrita livre do código | Mais vozes masculinas de qualidade disponíveis (TTS) |

## 5. Lyra 2.0 (plano de 11/08/2026 e execução)

### 5.1 Referências analisadas

Cinco projetos (clonados em `TESTE/`, fora do git): o que foi aproveitado.

| Projeto | Aproveitado | Descartado |
|---|---|---|
| Open WebUI (FastAPI + SvelteKit) | Subset mínimo de auth, organização `routers/models/utils`, tela "criar admin no 1º boot" | LDAP, OAuth/OIDC, SCIM, Redis, config no banco |
| LibreChat | Ideia de artifacts, tokens de tema | Auth enterprise (Passport com 7+ estratégias) |
| AnythingLLM | Modo single-user como referência; upload → embeddings com progresso | Multi-processo, convites, workspaces |
| Jan (Tauri) | Segredos/settings no lado nativo; hub de modelos; telas de MCP/monitor/logs | — |
| OpenClaw | Padrão Gateway (1 processo dono do estado, WS tipado), `SecretRef`, pareamento QR | Adaptadores multi-canal |

Paridade Open WebUI (12/08) — inaplicável por ser multi-usuário: RBAC, grupos,
analytics, leaderboard, canais, compartilhamento com ACL.

### 5.2 Auth mínimo — proteção de acesso

**Decidido: (A) proteção de acesso**, não multi-usuário. Uma conta admin; a senha
protege o app. Tabela `users` no SurrealDB (aditiva), PBKDF2-SHA256, JWT HS256 em
cookie httpOnly (30 dias), `CurrentUserDependency` pronta, rotas `/auth/status`,
`/auth/setup` (só com 0 usuários), `/auth/login`, `/auth/logout`. Frontend v3
mostra "criar conta" ou "entrar" conforme `/auth/status`.

**Pendente por decisão consciente:** nenhuma rota existente exige login — gatear
agora trancaria o usuário fora do v2 (sem tela de login). Aplicar junto com o
cutover pro v3 e com a correção do CORS `"null"`.

### 5.3 Backend: `routers/models/utils` + Gateway WS

- Backend continua **Python + FastAPI** (escolha certa mesmo do zero: ecossistema de IA).
- `cerebro_maestro.py` 1594 → ~930 linhas: só estado compartilhado, helpers e
  wiring. Todos os endpoints vivem em routers (classes POO com dependências via
  construtor; estado mutável compartilhado via getters/setters).
- **Gateway WS** (`/ws/gateway`, envelope `{action, payload}`) é camada
  **aditiva**, só ações de leitura, reaproveitando os métodos dos routers REST.
  Não substitui REST/SSE — trocar `/chat` para WS exigiria reescrever o consumo
  do v2. Fase considerada encerrada nesse ponto.

### 5.4 Capacidades novas (o que a Lyra não tinha)

| Item | Status |
|---|---|
| Onboarding/login no 1º boot | ✅ v3 |
| Favoritar sessões (`POST /sessoes/{id}/favoritar`) | ✅ |
| Monitor de sistema + viewer de logs (`/health`, `/metrics`, `GET /logs`) | ✅ `SystemPanel` |
| Painel de ferramentas: listar + ligar/desligar (`/tools`, `/tools/{nome}/toggle`, estado em memória) | ✅ |
| Preview de artifacts (`html`/`svg` em iframe sandboxed, inline por bloco) | ✅ |
| Hub de modelos Ollama (listar + pull com progresso SSE, confirmação obrigatória) | ✅ `ModelHubPanel` |
| Grafo de memória em Canvas 2D (força com decaimento `alpha`) | ✅ `GraphPanel` |
| Biblioteca de prompts (`/prompts` CRUD, clique insere no composer) | ✅ |
| `SecretRef` (`utils/secrets.py`: env/file/exec + máscara) | ✅ criado; `config.py` ainda não migrado (exige teste ao vivo) |
| Upload de documento → base de conhecimento com progresso | ⏳ |
| Pareamento de dispositivo por QR/token | ⏸ adiado (YAGNI — não há cliente que consuma) |
| Personas por modelo, notas, calendário, automações, branching de resposta, citações inline, execução de código, tags/pastas, editor de tools in-app | ⏳ aguardando priorização do usuário |

### 5.5 Frontend v3 — SvelteKit

Reescrita completa (não port do React): bundle menor, menos boilerplate. Nasceu com
login/onboarding, chat streaming, sessões (renomear/excluir/agrupar por data),
busca de memória (`Ctrl+K`), configurações em 7 abas, composer multi-linha com
parar/tentar de novo/copiar, seletor de modelo, voz live, esfera (Orb) no estado
vazio, e todos os itens da §5.4. Paleta mais contida que o v1: `--bg #0b0b0d`,
`--accent #4fc3d9`, peso 300 (decisão do usuário 11/08: base no visual atual,
priorizando minimalismo). Detalhes técnicos: [TECNICO §7.3](LYRA_TECNICO.md#73-v3--sveltekit-lyra-20).

### 5.6 Cascas desktop — Theia + Tauri

**Dois produtos, um frontend.** Theia é a casca da IDE (painel `lyra-chat`); Tauri é
a casca leve "só assistente". Ambas carregam o mesmo SvelteKit. O frontend nunca
sabe onde está: interface fina `LyraShell` (`getSecret`, `setSetting`,
`startBackend`, `openIDE`) implementada por `BrowserShell`, `TheiaShell`
(`?shell=theia`) e `TauriShell` (`window.__TAURI_INTERNALS__` → 4 comandos Rust).
Botão **"Abrir IDE"** na casca Tauri lança/foca o Theia.

### 5.7 Regras de transição

- Mudança de schema sempre **aditiva** — nunca remover/renomear campo que código antigo lê.
- Snapshot SurrealDB + Qdrant antes de qualquer mudança de schema real.
- **Critério de corte do v2:** o React continua em `/ui` até o v3 ter paridade
  testada; só sai após alguns dias de uso real sem bug crítico. Nada é apagado antes.
- Instalador **não** carrega os ~3M vetores: conecta nos bancos existentes; "começar
  vazio" ou "importar snapshot" (~2-3GB) só se pedido.
- Footprint (backend + bancos + Ollama + casca) ainda não medido — medir na
  integração e decidir o que sobe sob demanda.

### 5.8 Status das fases (12/08/2026)

| Fase | Status |
|---|---|
| 1 — Backend `routers/models/utils` | ✅ 7/7 grupos de endpoint extraídos |
| 2 — Auth mínimo | ✅ backend; gating pendente (§5.2) |
| 3 — Gateway WS | ✅ camada aditiva de leitura (encerrada) |
| 4 — Frontend SvelteKit | ✅ núcleo + paridade com v2 auditada; servido em `/ui-novo` |
| 5 — Cascas desktop | ✅ contrato + `TheiaShell` + `TauriShell`; `cargo check`/`clippy` limpos |

Nada bloqueado. O que resta é sequenciamento de produto (cutover, gating) e
empacotamento/teste ao vivo. Verificação feita: compile/import + self-checks no
backend, `svelte-check` + build + Playwright contra backend real no frontend.
**Não verificado:** cascata fim-a-fim com todas as nuvens e áudio real de voz.

## 6. Estado atual por área

- **Backend:** POO, routers, 58 ferramentas, auth pronto sem gating, Gateway WS aditivo.
- **Memória:** ~3.09M vetores (`lyra_memory_v2`), SurrealDB ~3.27M registros,
  reconciliação automática SurrealDB↔Qdrant a cada ~1h.
- **Frontends:** v1 em produção; v2 em `/ui` (usado pela IDE e pelo Desktop); v3 em
  `/ui-novo` (preview lado a lado, cutover pendente).
- **Lyra IDE:** Fase A (browser + Electron) e B (branding) concluídas; Fase C
  iniciada — painel `lyra-chat` (iframe de `/ui/?shell=theia`) validado ao vivo.
- **Lyra Desktop:** Electron puro carregando `/ui/`, single-instance, links externos bloqueados. Start manual.
- **Tauri:** compila limpo; ainda não empacotado.

## 7. Pendências e roadmap

### 7.1 Próximos passos
1. Cutover v2 → v3 (critério §5.7), trocar o iframe do Theia para o v3.
2. Gating de auth nas rotas + remover `"null"` do CORS + autenticar `/mcp`.
3. Bridge IPC real da `TheiaShell` (`getSecret`/`setSetting` hoje só avisam).
4. **IDE Fase C/D:** avaliar plugar a Lyra como provider do `@theia/ai-*` (já
   embutido) vs painel próprio; completion inline no Monaco; menu "Perguntar à
   Lyra"; voz na status bar; grafo como aba; "Explicar erro" do Problems (sugere,
   nunca aplica sozinho). Terminal real via `pywinpty`/ConPTY ↔ `xterm.js`;
   autocomplete `pyright-langserver --stdio` ↔ `monaco-languageclient` (só Python);
   `GET /ide/interpreters`; DAP depois.
5. **IDE Fase E:** instalador `.exe` (`electron-builder`, NSIS), auditoria de rede do
   build final (única saída aceitável: Open VSX quando aberto manualmente), update manual.
6. **IDE Fase F:** curadoria de extensões. Decisão pendente: extensões Microsoft
   (Python, C/C++, Docker) têm EULA restritiva — recomendação: instalação manual
   opcional, alternativas abertas por padrão (`clangd`, `rust-analyzer`,
   `redhat.vscode-yaml`, `eslint`, `prettier`, `gitlens`, `material-icon-theme`, `rest-client`).
7. Medir footprint (§5.7).

### 7.2 Backlog técnico
- Migrar `config.py` para `SecretRef`; `migrar_chaves_para_keyring()` ainda nunca executado.
- Upload de documento → RAG com progresso (§5.4).
- Rebuild incremental do BM25 (hoje exige swap de pasta com o cérebro parado).
- `validador_cortical.py` por categoria (métrica atual mistura episódios com wiki).
- Qwen3-VL-7B como VLM local no lugar de `llava-phi3` (download grande — decisão do usuário).
- `browser-use` 0.13.1 → 0.13.3.
- Ferramenta de hora/data (não existe no `TOOLS_MAP`).
- Estado `input-required` para sub-agentes do enxame (ideia do A2A).
- Frontend v1: Three.js → WebGPURenderer (r171+).
- `lyra_launcher.py` não mata processo antigo na mesma porta.
- Task Scheduler real (`schtasks` dá acesso negado; hoje atalho na pasta Startup).
- Sandbox de arquivos do agente (`WORKSPACE_SEGURO`) — só esboço, nada implementado.
- Ícones da activity bar e glassmorphism profundo na IDE; tema "Lyra Dark" como extensão própria.
- SurrealDB `root/root` — aceito enquanto o bind for 127.0.0.1.

### 7.3 Modo Construção (planejado)

| | Modo Chat | Modo Construção |
|---|---|---|
| Modelo | Cascata cloud ou qwen3:8b | Qwen3.6 27B / DeepSeek-R1 32B distilled |
| Hardware | 8GB VRAM | 64GB RAM (offload) |
| Vazão | >40 tok/s | 5-10 tok/s |

LM Studio (`:1234`, efêmero, nunca auto-inicia) para achar a camada ótima de
offload. Interface split-pane: chat à esquerda, renderizador de código à direita.
Voz duplex com VAD (interrupção ativa, fallback walkie-talkie após 5s).
Task-Aware Budgeting: resume (não descarta) mensagens de baixa densidade técnica
na transição de domínio.

### 7.4 Visão de longo prazo (conceitual)
Sistema de Arquivos Líquido (hard links contextuais) · Total Recall (OCR contínuo de
tela) · Telepatia de Clipboard · DNA de Projeto (versiona intenção, não só diff) ·
OPSEC avançado (esteganografia de núcleo, sandbox de hipertempo em RAM, honeypot
USB, CRYSTALS-Kyber) · Soberania acadêmica (mentor UML/Java, resumo de PDFs de aula) ·
Sensor Fusion (Wi-Fi CSI + mic + teclado + câmera) · Biometria passiva (ritmo de
digitação, EEG) · Ghost OS Level 2 (namespace/eBPF).
