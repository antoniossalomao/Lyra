# LYRA — Estado Atual do Projeto
> Consolidado em 10/08/2026 a partir de LYRA_NUCLEO.md, LYRA_TECNICO.md, LYRA_AGENTES_E_PLANOS.md, LYRA_IDE_PLANO.md e da sessão do dia.

---

## 1. O que é

IA pessoal local, identidade feminina, voz técnica/direta, não-servil. Não é um chatbot — pensada como organismo cognitivo: hardware como corpo, modelos como córtex, SurrealDB+Qdrant como memória. Roda 100% no PC do Antônio (Ryzen 7 3700X, RTX 2060 Super 8GB, 64GB RAM, Windows), sem Docker.

## 2. Ring 0 — princípios invioláveis

1. Antônio é Administrador Supremo — Protocolo de Sobrescrita anula qualquer raciocínio da máquina.
2. `core.py` somente leitura.
3. 100% offline por padrão. Exceções já aprovadas: cascata cloud (Groq→Gemini→Claude→local) pra todo chat; TTS pode ser online; Open VSX Registry (marketplace de extensões da IDE).
4. Hardware-Bound Logic Gates — telemetria da placa-mãe/RTX/RAM como chave física.
5. Auto-modificação de código exige aprovação explícita antes de produção.
6. Ações de execução de alto risco exigem confirmação explícita no chat (Câmara de Eco Heurística).

## 3. Stack técnico atual

| Camada | Tecnologia | Porta |
|---|---|---|
| Backend/orquestrador | `cerebro_maestro.py` (FastAPI, OOP desde 07-08/08) | 8000 |
| Embedding+reranker | `embed_service.py` — BAAI/bge-m3 1024d + bge-reranker-v2-m3 | 8001 |
| WS hub (frontend v1) | `lyra_app.py` | 8765 |
| Vector DB | Qdrant standalone (fixado v1.17.1) — `lyra_memory_v2`, ~3.09M vetores | 6333 |
| Graph+Doc DB | SurrealDB 3.0.5 (ns `lyra_core`, db `Db_CORTEX`) | 8090 |
| LLM local | Ollama, qwen3:8b (fallback da cascata) | 11434 |
| LLM cloud | Groq (gpt-oss-120b) → Gemini → Claude(CLI) → local | — |
| STT | faster-whisper "small" CPU int8 | — |
| TTS | Gemini TTS (voz Leda) → edge-tts Francisca → silêncio | — |
| Frontend v1 | pywebview + Three.js | — |
| Frontend v2 | React + Vite + TS (chat completo, real) | 5173 (dev) |
| IDE | Eclipse Theia + Electron ("Lyra IDE") | — |

**Regra crítica:** toda chamada interna entre serviços usa `127.0.0.1`, nunca `localhost` (resolver IPv6 do Windows adiciona ~2s/chamada).

## 4. Memória e cognição — implementado

- **4 camadas:** RAM (working memory) → Qdrant (semântica, BGE-M3 1024d) → SurrealDB (episódica/grafo) → cold storage.
- **RAG híbrido:** BM25 (bm25s, esparso, ~382ms sobre 3M docs) + denso (Qdrant) + RRF + reranker cross-encoder + recência. `GET /buscar`.
- **Grafo de memória nativo (SurrealDB):** `RELATE evento->precedeu->evento` (threading) e `RELATE evento->sobre->topico:keyword`. `GET /grafo`, `GET /grafo/completo` (visualizador 3D).
- **Shadow Thoughts (ciclo de sono):** WAKE/NREM(dedup)/REM(cruzamento via grafo)/DEEP SLEEP(destilação), roda a cada 3h. `POST /shadow_thoughts`.
- **Enxame de sub-agentes paralelos** (`lyra_agentes.py`): fan-out/fan-in via `asyncio.Semaphore`, persistido em SurrealDB. `POST /enxame`.
- **Enxame de especialistas (MoE roteado):** cascata do `/chat` roteada por categoria (código/geral).
- **Speculative Decoding (sidecar de alucinação):** draft qwen3:0.6b compara divergência semântica com a resposta principal.
- **Câmara de Eco Heurística:** bloqueia comandos de alto risco (deleção em massa, formatação, shutdown) até confirmação explícita.
- **`lyra_agent.py`:** loop ReAct autônomo standalone (não integrado a endpoint HTTP ainda, uso via CLI/import).
- **Innovations 1-5 (01/07):** Goal Drift Detector, Knowledge Freshness Tags, Session Replay cognitivo, Cognitive Load Throttling, Response Provenance — todas implementadas.

## 5. Voz e sentidos

- **Wake-word local:** `mic_engine.py` — "lyra" → Silero VAD → faster-whisper → `/chat`.
- **Voice Live (tempo real):** Gemini Live API bidirecional, `WEBSOCKET /ws/voice`, modelo `gemini-2.5-flash-native-audio-latest`. Handshake validado; áudio ponta a ponta com microfone físico ainda não testado.
- **Visão:** `explicar_tela()` via Gemini Vision (fallback llava-phi3 local), `analisar_imagem()`.
- **TTS:** pipeline pausado por decisão do usuário na v1 (Gemini TTS implementado como opção, não ligado por padrão).

## 6. Frontends

### v1 — `Front_end_Lyra/` (produção, pywebview + Three.js)
Esfera de partículas reativa a estado, painel lateral (telemetria, tiers), chat modal, grafo de memória 3D (`3d-force-graph` + Three.js, 100% vendorizado offline). Auditorias de segurança/visual/latência já feitas — ver LYRA_TECNICO.md.

### v2 — `Front_end_Lyra_v2/` (React + Vite + TS, chat real e completo)
Não é mais mockup — integrado de ponta a ponta ao backend real (`/chat` SSE streaming, `/historico`, `/sessoes`, `/metrics`, `/stats`, `/buscar`, `/tts/mudo`, `/integracoes`, `/exportar`, `/upload`). Paridade visual com app do Claude (bolhas, markdown, retry, anexo, atalhos, settings em abas). Tema dark-only, sem CDNs.
**Novo hoje (10/08):** `vite.config.ts` builda com `base: '/ui/'`; `cerebro_maestro.py` serve o `dist/` em `GET /ui/*` (mesma origem do backend, sem CORS).

## 7. Lyra IDE (Eclipse Theia + Electron) — Fase A/B concluídas, C em andamento

Decisão: base Theia (não fork Code-OSS, não Electron do zero) — clona UX do VSCode, Monaco nativo, extensões VSIX reais via Open VSX.

- **Fase A (validação):** ✅ concluída nos dois targets (browser e electron). App desktop abre, Monaco com highlight, terminal integrado, 97 extensões reais instaladas via Open VSX.
- **Fase B (branding):** ✅ concluída. Ícone real (estrela 4 pontas cyan de `lyra.ico`), wordmark "LYRA IDE", splash screen, tema "Lyra Dark" (`#00DDFF` sobre preto), fonte Inter vendorizada na UI, update-checker desligado.
- **Fase C (ponte com backend) — em andamento, primeiro passo feito hoje:**
  - Extensão custom `theia-extensions/lyra-chat/` criada: widget dockável (`LyraChatWidget`) com iframe apontando pra `http://127.0.0.1:8000/ui/` (frontend v2 servido same-origin pelo backend).
  - Comando "View: Toggle Lyra" registrado (Ctrl+Shift+P ou menu View) — abre painel na lateral direita.
  - Validado ao vivo: painel abre, iframe carrega, dados reais aparecem (CPU/RAM/GPU, distribuição da cascata Groq/Gemini/Local/Claude) — sem abrir navegador nenhum, tudo dentro da janela Electron.
  - Ainda não portado: componentes React individuais como widgets nativos Theia (é só iframe por enquanto, funcional mas não "nativo"); completion inline no editor; menu de contexto "perguntar à Lyra"; grafo de memória como aba própria — isso é Fase D.
  - **Revalidado ao vivo (10/08, sessão seguinte):** painel reaberto após rebuild do frontend v2 — histórico real da sessão intacto, resposta nova via Groq recebida, painel de métricas atualizando. Confirma que o iframe se conecta de novo sozinho, sem precisar tocar na extensão da IDE quando só o front-end v2 muda.

## 7.1. Lyra Desktop — app standalone novo (10/08/2026)

Além da IDE, a Lyra agora também roda como **app desktop próprio**, independente do editor — mais parecido com o que a v1 (pywebview) já fazia, só que pro front-end v2 (React).

- **Pasta:** `Lyra_Core/Lyra_Desktop/` — `main.js` (Electron puro, sem framework) + `package.json` + `lyra.ico` (ícone oficial, copiado de `Front_end_Lyra/lyra.ico`).
- **Reaproveita o Electron já baixado pela IDE** (`Lyra_IDE/node_modules/electron`) em vez de instalar uma cópia nova — zero dependência extra.
- Janela carrega `http://127.0.0.1:8000/ui/` (mesmo `/ui` que a IDE usa), sem menu bar, ícone/título "Lyra" corretos, single-instance lock (2ª abertura foca a janela existente em vez de abrir duplicata).
- **Ring 0 aplicado:** `setWindowOpenHandler` nega qualquer `target="_blank"`/`window.open` — nenhum link consegue abrir o navegador do sistema, mesma regra da IDE.
- **Como iniciar:** `bin/startup/start_lyra_desktop.bat` (não está no boot automático ainda — start manual por enquanto).
- Validado ao vivo: janela abre, título "Lyra" na barra, chat real funcionando (perguntei "quem é você?" e recebi a resposta certa da Lyra), painel de métricas ao vivo.

## 7.2. Bugs reais corrigidos no front-end v2 (10/08/2026)

Auditoria pedida pelo usuário (typecheck + lint limpos de saída, bugs achados na revisão manual dos componentes):

1. **Botão de enviar morto na tela vazia** (`Shell.tsx`) — o input inicial ("Ready when you are") só enviava com Enter; o botão ↑ não tinha `onClick` nenhum, clicar nele não fazia nada. Corrigido: input virou controlado (`emptyDraft` state), botão e Enter agora chamam o mesmo `handleSend`.
2. **Link do dashboard abria navegador externo** (`SettingsModal.tsx`, aba About) — `target="_blank"` faz o Electron chamar `shell.openExternal`, violando a regra explícita de nunca abrir nada no navegador do sistema. Removido o `target`/`rel` — agora navega na própria janela.
3. **Ícone errado no front-end v2** (`favicon.svg`) — era o raio roxo/azul (mesmo engano já corrigido na IDE, ver seção 12/13 do `LYRA_IDE_PLANO.md`), não o ícone oficial da Lyra. Trocado pra PNG da estrela cyan real (mesmo asset gerado pra IDE).
4. **Título da aba/janela nunca foi trocado** (`index.html`) — ficava `front-end-lyra-v2` (nome default do Vite) em vez de "Lyra". Visível principalmente no app desktop (Electron usa o `<title>` da página como título da janela) — corrigido.
5. **4 handlers sem tratamento de erro** (`handleSelectSessao`/`handleNewChat`/`handleRename`/`handleDelete` no `Shell.tsx`, `handleExport` no `SettingsModal.tsx`, `handleFile` no `Chat.tsx`) — se o backend caísse no meio de uma dessas ações, virava unhandled promise rejection. Envolvidos em `try/catch` silencioso, mesmo padrão já usado no resto do arquivo (`.catch(() => {})`).

`tsc -b` e `oxlint` seguem limpos (0 erros/warnings) depois das correções. Rebuild (`npm run build`) servido direto pelo `/ui` do backend — IDE e Desktop pegam a versão corrigida sem precisar de nenhum passo extra.

**Correção adicional (mesma sessão, pedido do usuário — "a barra cortando as msg da lateral"):** o título da conversa na sidebar (`Sidebar.tsx`, `<span>{s.titulo}</span>`) tinha `overflow:hidden;text-overflow:ellipsis;white-space:nowrap` mas nenhum `min-width:0`. Dentro de um container `display:flex` (`.sb-conv`), um item flex sem `min-width:0` se recusa a encolher abaixo da largura do próprio texto — então a ellipsis nunca disparava e o título ficava cortado seco (sem "...") bem onde a barra de rolagem da lista aparece, dando a impressão de "a barra cortando a mensagem". Corrigido: `minWidth: 0, flex: 1` no span do título; mesmo problema replicado e corrigido em `.account-name` (nome de exibição no rodapé da sidebar). Também adicionado `scrollbar-gutter: stable` em `.sb-convs` pra a lista não mudar de largura quando a barra aparece/some.

## 8. Segurança — auditorias já feitas

- CORS restrito (`allow_origins` explícito, sem `*` + credentials) — corrigido drive-by via localhost (03/08).
- Todos os binds de serviço confirmados em `127.0.0.1` (Qdrant/SurrealDB tiveram vazamento pra LAN, corrigido 04/08 — inclusive bug do self-healing que reiniciava com storage vazio).
- Telegram default-deny (allowlist vazia recusa iniciar).
- Nenhuma chave de API hardcoded fora do `.env` (varredura feita).
- Rate limit + Câmara de Eco em todo dispatch de tool.

## 9. Pendências manuais (`instrucoes.md`)

| # | Item | Status |
|---|---|---|
| 1 | Bot Telegram (@BotFather + `.env`) | Pendente, opcional |
| 2 | Playwright Chromium (`navegar_web`) | ✅ Feito |
| 3 | Google Workspace OAuth (Gmail/Calendar) | Pendente, opcional |
| 4 | Screenpipe (gravação contínua de tela) | Pendente, opcional |
| 5 | Atualizar SurrealDB via winget | Pendente |
| 6 | Registrar MCP da Lyra no Claude Code | Pendente, opcional |

## 10. Roadmap — o que falta

- **Fase D da IDE:** completion inline, menu de contexto no editor, botão de voz na toolbar, grafo de memória como painel próprio, "explicar erro" a partir do Problems panel.
- **Fase E da IDE:** empacotamento `.exe` via electron-builder, auditoria de rede no build final.
- **Fase F da IDE:** curadoria de extensões recomendadas (Python/C++/Docker — pendente decisão sobre EULA da Microsoft).
- **Fase 4 (roadmap geral):** Emotion Engine (voz paralinguística), Wi-Fi Sensing via ESP32.
- **Fase 5+:** Protocolo Darwin (auto-evolução supervisionada), BCI OpenBCI, Protocolo Narciso.
- Decisão em aberto: `Front_end_Lyra_v2` standalone continua paralelo à IDE ou é substituído por ela no dia a dia?

---

*Detalhes técnicos completos, histórico de bugs e decisões: `LYRA_NUCLEO.md`, `LYRA_TECNICO.md`, `LYRA_AGENTES_E_PLANOS.md`, `LYRA_IDE_PLANO.md`.*
