# LYRA — REFERÊNCIA TÉCNICA
>
> Consolidado em 25/06/2026. Atualizado em 30/06/2026.

---

## 1. Padrões técnicos confirmados (não quebrar)

### Embedding padrão: BAAI/bge-m3 (1024 dims) — via embed_service :8001

Divergência entre modelos de embedding causa alucinações no RAG. Todo arquivo que gera ou busca vetores DEVE usar este modelo (chamando `:8001/embed`) enquanto a produção for o `lyra_memory_v2` (1024d). Nunca trocar sem migrar todos os vetores existentes. **Histórico:** o padrão era `paraphrase-multilingual-MiniLM-L12-v2` (384d, coleção `lyra_memory`) até a migração BGE-M3 de 26/06/2026 — ver logo abaixo.

### ✅ Vetorização BGE-M3 CONCLUÍDA (26/06/2026)

Coleção paralela `lyra_memory_v2` (1024d) completa: **3.087.193 vetores**, 100% GPU, zero fallback CPU. Composição (bate com as tabelas-fonte do SurrealDB):

- `conhecimento_geral` (wiki): 1.112.246
- `conversa_geral`: 1.001.379
- `raciocinio_matematico`: 402.473
- `instrucao_ptbr`: 325.410
- `programacao`: 238.857
- `conhecimento_qa`: 6.828

**Índice de payload `categoria: keyword` criado no v2** (26/06) — o v2 tinha sido criado sem nenhum índice, o que quebrava facet e deixaria filtros por categoria lentos. v1 já tinha esse índice.

**Gap conhecido:** o v2 NÃO tem a categoria `episodio` (histórico de conversa) nem as pequenas (`config`, `codigo_python`, `documentacao`, `codigo_js`, `web`, `script`) — essas só existem no v1, criadas em runtime por `registrar_evento()`. Na migração, novos episódios passam a ir pro v2; os 235 episódios antigos do v1 podem ser re-vetorizados ou descartados (volume desprezível).

### Vetorização BGE-M3 na GPU — config que segura os 8GB de VRAM

`vetorizar_bge_m3.py`: `ENCODE_BATCH=32`, `MAX_SEQ_LEN=512` (wiki tem textos longos; batch 64/seq 1024 estourava). **Checagem de VRAM usa `torch.cuda.memory_allocated()`, NÃO `memory_reserved()`** — reserved inclui buffers internos do PyTorch e dispara falso positivo de OOM (cai pra CPU sem necessidade). Com essa config: ~1091MB VRAM alocada, ~88k vetores/30min, 94% GPU.

### 🔴 CRÍTICO — usar `127.0.0.1`, NUNCA `localhost`, em chamadas internas (Windows)

Descoberto 26/06/2026: toda chamada HTTP pra `http://localhost:PORTA` neste Windows paga **~2 segundos de delay** porque o resolver tenta IPv6 (`::1`) primeiro, espera o timeout, e só então cai pra IPv4. Os serviços (Qdrant :6333, SurrealDB :8090, Ollama :11434, embed_service :8001) escutam só em IPv4 (`127.0.0.1`). Medido: `localhost` ~2050ms vs `127.0.0.1` ~5-20ms por chamada — **100x mais lento**.

Isso estava penalizando silenciosamente CADA operação de RAG/grafo/memória do `cerebro_maestro`. Corrigido em `cerebro_maestro.py`, `lyra_agentes.py`, `lyra_tools.py`, `build_bm25_index.py`, `test_smoke.py`, `test_migracao_v2.py` — todas as URLs internas usam `127.0.0.1`. **Regra:** qualquer URL de serviço local DEVE ser `127.0.0.1`, nunca `localhost`. (URLs servidas ao frontend em :8000 podem ficar como estão — o Chromium do pywebview resolve melhor; mas internamente, sempre 127.0.0.1.)

**Impacto medido (antes → depois):** `/buscar` 5.6s → 1.26s; smoke test completo 56s → 8.2s; chat simples ~5s → ~1s. Foi o maior gargalo do sistema. Próximo gargalo de retrieval: o BM25 (`rank_bm25`, Python puro) varre os 2.16M docs a cada busca (~1s) — candidato a otimização (limitar corpus, ou impl nativa).

### UUID determinístico (uuid5) para IDs do Qdrant

`hash()` colidia e não era idempotente. Sempre `uuid.uuid5(uuid.NAMESPACE_URL, titulo)` para IDs de pontos Qdrant.

### Paginação por cursor no SurrealDB (não LIMIT/START)

LIMIT/START faz full scan com 1M+ registros. Usar `WHERE id > $cursor ORDER BY id LIMIT N`.

### SurrealDB Python SDK v1.x: formato de resposta do `query()`

SDK v0.x retornava `[{"result": [...]}]`; v1.x retorna lista direta. Usar `registros = res if res else []`. Nunca `res[0].get("result")`.

### SurrealDB porta 8090, DB_NAME "Db_CORTEX" (case-sensitive)

`DB_URL = "ws://localhost:8090/rpc"`, `NS = "lyra_core"`, `DB_NAME = "Db_CORTEX"` em todos os arquivos. Headers HTTP (`/sql`) devem ser `surreal-ns`/`surreal-db` (não `NS`/`DB` — formato antigo, incompatível com SurrealDB 3.0.5). Porta 8000 conflita com FastAPI.

### `log()` deve escrever no arquivo ANTES de tentar stdout

`sentence_transformers`/`tokenizers` corrompe o handle do console Windows. Em scripts que importam `sentence_transformers`: `_log_f.write()` + `_log_f.flush()` primeiro, depois `print()` em try/except.

### `sys.stdout.reconfigure(encoding="utf-8")` obrigatório

Quando saída é redirecionada/capturada em vez de ir pra console Windows nativo, Python cai pra ANSI codepage (cp1252) e `print()` de qualquer caractere fora do cp1252 (✓ ✗ ⚠ emojis) lança `UnicodeEncodeError` silencioso. Usar `try: sys.stdout.reconfigure(encoding="utf-8", errors="replace"); except: pass` logo após `import sys`.

### 🔴 CRÍTICO — ordem de import `pyarrow` ANTES de `torch` no Windows

Importar `sentence_transformers` carrega `pyarrow` (via `datasets`) como efeito colateral. Se `torch` (ou `qdrant_client`) já carregou primeiro, o `arrow.dll` do pyarrow colide e gera **access violation (0xc0000005)** — processo morre sem traceback Python (só aparece no Visualizador de Eventos). SEMPRE `import pyarrow` como PRIMEIRA linha de import pesado, antes de `torch`/`qdrant_client`/`sentence_transformers`. Já corrigido em `final.py`, `vetorizar_todos.py`, `cerebro_maestro.py`, `lyra_tools.py`, `test_tools.py`, `genesis_ingestor.py`.

### ⚠️ NUNCA atualizar o binário do Qdrant sem backup completo do `qdrant_data/` primeiro

Atualizar de v1.17.1 → v1.18.2 fez migração silenciosa que descartou ~666k vetores. Revertendo o binário, os dados NÃO voltaram. Fixado em **v1.17.1** — não atualizar sem `cp -r qdrant_data qdrant_data_backup_<data>` antes.

### ✅ `venv_embed` (5GB) APOSENTADO — Python global atualizado pra torch 2.6 (30/06/2026)

O motivo original do venv isolado (`bge-m3` exige `torch>=2.6`, só tem pesos `.bin` sem safetensors — confirmado testando `use_safetensors=True`, falha porque o repo não tem esse arquivo) continuava válido, mas o Python "principal" do projeto nunca foi um venv de projeto — é o **Python global do sistema** (`C:\Users\anton\AppData\Local\Programs\Python\Python312\python.exe`), usado por `cerebro_maestro.py`, `faster-whisper`, etc. Upgrade: `pip install torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124` (driver 596.49 suporta CUDA 12.4+). Backup de rollback salvo em `C:\Lyra_Project\bin\backup_pip_freeze_python312_30-06-2026.txt` (`pip install -r ... --force-reinstall` reverte).

**Decisão importante — NÃO fundir o embedding no `cerebro_maestro.py`:** cogitado inicialmente, mas rejeitado. O `cerebro_maestro` foi deliberadamente esvaziado de `torch`/`sentence_transformers` na migração de 26/06 (startup caiu de ~25s pra ~2-3s, processo leve). Trazer o embedding de volta pra dentro do processo principal reintroduziria exatamente esse custo, mais perda de isolamento de falha e do idle-unload de VRAM. **Solução aplicada:** manter o `embed_service.py` como processo HTTP separado (arquitetura intacta), só trocando o interpretador que ele usa — `start_embed.bat` agora chama o Python global em vez de `venv_embed\Scripts\python.exe`. Resultado: mesmos benefícios de isolamento, 5GB a menos em disco, sem tocar em `cerebro_maestro.py`.

Validado ao vivo pós-migração: `bge-m3` carrega em 4.3s (CPU) / GPU confirma `device:cuda, vram_mb:1091` após 1ª chamada; `bge-reranker-v2-m3` carrega em 2.1s; `GET /buscar` no cérebro retorna `rerank_score`/`dense_score` normalmente, sem precisar reiniciar o `cerebro_maestro.py` (ele só fala HTTP com :8001, indiferente ao interpretador do outro lado). `venv_embed` apagado (5GB liberados) depois de tudo validado.

**Pegadinha replicada do bug já documentado:** mesmo fora do venv isolado, `import pyarrow` ainda precisa vir ANTES de `sentence_transformers`/`torch` (o `embed_service.py` já fazia isso corretamente) — testei sem essa ordem primeiro e reproduzi o access violation (exit 139) até corrigir a ordem.

### Embedder CPU vs GPU — decisão deliberada

`cerebro_maestro.py` mantém embedder em `device="cpu"` de propósito — evita disputar VRAM com o LLM durante o chat. Scripts de vetorização em lote (`final.py`, `vetorizar_todos.py`) DEVEM usar GPU (`cuda`) — ~40 emb/s na CPU vs ~1400 emb/s na GPU.

### pyttsx3 não pode ser usado com asyncio

`pyttsx3.runAndWait()` bloqueia o thread worker do asyncio indefinidamente. TTS async usa subprocess PowerShell com `System.Speech.Synthesis.SpeechSynthesizer`.

### pywebview: path absoluto para `url=`

`url='index.html'` resolve pelo cwd, não pelo diretório do script. Usar `url=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html')`, `fullscreen=True`, `SetProcessDPIAware()` antes de `GetSystemMetrics`.

### Wikipedia vetorizada sem `categoria`/`fonte` no payload do Qdrant (corrigido 22/06/2026)

`final.py` montava o `PointStruct` só com `titulo`/`texto`/`surreal_id`. Todo `PointStruct` DEVE ter `categoria` e `fonte` — é o que permite filtro em `/buscar` e `buscar_memoria`.

### Tabelas do SurrealDB frequentemente vetorizadas só PARCIALMENTE no Qdrant

Ingestão (SurrealDB) e vetorização (Qdrant) são passos desacoplados — é fácil ingerir e nunca rodar a vetorização até o fim. Periodicamente comparar `SELECT count() FROM <tabela> GROUP ALL` no SurrealDB com contagem por categoria no Qdrant.

---

## 2. Bugs e melhorias pendentes

### ✅ Resolvidos (26/06/2026)

**`historico_recente` morre no restart** — ✅ RESOLVIDO. `_carregar_estado_inicial()` carrega últimas 20 msgs do SurrealDB no startup.

**SurrealDB subutilizado — só log cronológico** — ✅ RESOLVIDO. `_grafo_salvar_relacoes()` cria arestas `precedeu` (threading) e `sobre` (tópicos). `buscar_grafo_surreal()` faz traversal. Endpoint `GET /grafo`.

**`GET /grafo/completo` retornava 500** — ✅ CORRIGIDO (30/06/2026). O endpoint consultava `SELECT id FROM topico` mas a tabela `topico` não existe como entidade separada — os tópicos são referenciados implicitamente via `sobre.out` como `topico:keyword`. Além disso o código de processamento dos nós ficava FORA do try/except, então o `AttributeError` ao iterar `topicos` (que vinha como string de erro) subia como 500 não tratado. Corrigido: removida query de `topico`, tópicos extraídos do campo `out` das relações `sobre`, todo processamento dentro do try/except.

**Tabela `topico` não existe no SurrealDB** — Os tópicos são IDs implícitos do tipo `topico:palavra` criados automaticamente pelo SurrealDB ao executar `RELATE evento -> sobre -> topico:keyword`. Não há `DEFINE TABLE topico` — qualquer query direta a essa tabela retorna `NotFound`.

**Front-end: Grafo de Memória 3D** — ✅ IMPLEMENTADO (30/06/2026). Visualizador interativo com `3d-force-graph v1.73.4` + Three.js r128. Lyra central fixada na origem, tópicos na esfera via força radial (Fibonacci), eventos como partículas menores. Linhas Lyra→tópico com curvatura orgânica (Bézier quadrática). Busca, detalhe ao clicar, fallback mock offline. Arquivo: `Lyra_Core/Front_end_Lyra/script.js` → `_renderGrafo()` + `abrirGrafo()`. Preview standalone: `preview_grafo_visualizador.html`.

**Session briefing inexistente** — ✅ RESOLVIDO. `_carregar_estado_inicial()` gera briefing de 4 linhas via Groq e injeta no system prompt.

**Retrieval puro cosseno — sem recência** — ✅ RESOLVIDO. `buscar_hibrido()` reordena com `score_final = 0.7*rrf_norm + 0.3*recencia` (decaimento 30 dias). Payload do Qdrant tem `retrieval_count` + `last_accessed_at`, atualizados a cada recuperação.

**Compressão de histórico** — ✅ NOVO. Acima de 14 msgs, comprime as 8 mais antigas via Groq num sumário injetado. Lock `_comprimindo`.

**Bug do LIMIT em `buscar_grafo_surreal`** — ✅ CORRIGIDO. O `LIMIT` no SELECT externo limitava tópicos, não eventos. Agora busca por tópico individual com dedup + cap real.

### 🟠 Média prioridade

**✅ Tool router por keyword** — RESOLVIDO 26/06. Era substring solto (falsos positivos: "ram" casava em "programacao" → Lyra chamava ferramenta numa pergunta conceitual). Agora `_TOOL_KEYWORDS_RE` (regex com `\b`, prefixo no início de palavra) em `cerebro_maestro.py`. "tempo" removido (casava em "há quanto tempo"). Validado: perguntas conceituais não disparam tools, pedidos reais disparam.

**✅ Migração BGE-M3** — CONCLUÍDA 26/06/2026. `cerebro_maestro` usa `lyra_memory_v2` (1024d) via `embed_service`; `lyra_memory` (MiniLM 384d) apagada. Ver runbook abaixo (histórico) e status detalhado logo após.

#### 📋 Runbook da migração BGE-M3 (executar quando a vetorização terminar)

**Bloqueador conhecido:** o `bge-m3` exige `torch>=2.6` (pesos só em `.bin`), mas o Python principal do `cerebro_maestro` tem `torch 2.5.1+cu121`. Duas opções:

- **(A) Recomendada:** subir um microserviço de embedding no `venv_embed` (torch 2.6) expondo `POST /embed` → `cerebro_maestro` chama via HTTP. Mantém o cérebro intocado e isola a dependência pesada.
- **(B)** Atualizar o torch do Python principal pra 2.6+cu124. Mais simples mas mexe no ambiente que já funciona (risco de regressão em faster-whisper/outras libs).

**Passos (assumindo opção A):**

1. ✅ Validar contagem — FEITO 26/06: v2 = 3.087.193, bate com as tabelas-fonte. Índice `categoria: keyword` já criado.
2. ✅ Criar `embed_service.py` — FEITO 26/06. FastAPI :8001 no venv_embed, carrega `BAAI/bge-m3` (`normalize_embeddings=True`, `max_seq_length=512` igual à vetorização). Endpoints `/health`, `POST /embed {texto|textos}`. Rodar: `venv_embed\Scripts\python.exe embed_service.py`. **Testado e validado** via `test_migracao_v2.py`: queries reais retornam resultados altamente relevantes do v2 (recursão→0.73, capital BR→0.71, eq. 2º grau→0.68). fastapi/uvicorn instalados no venv_embed.
3. ✅ Em `cerebro_maestro.buscar_hibrido()`: trocado `embedder.encode(query)` por chamada HTTP a `:8001/embed`; `collection_name="lyra_memory"` → `"lyra_memory_v2"`. FEITO 26/06 — ver "Status" logo abaixo.
4. ✅ Em `registrar_evento()`: idem, novos episódios gravados no espaço de 1024d. FEITO 26/06.
5. ✅ **Rebuild do BM25** (`build_bm25_index.py`) sobre o conteúdo de `lyra_memory_v2`. FEITO 26/06.
6. ✅ Validado com `test_smoke.py` + perguntas factuais reais (qualidade superior ao MiniLM, comparação documentada). FEITO 26/06.
7. ✅ `lyra_memory` (MiniLM) aposentada e apagada. FEITO 26/06 — ~5GB liberados.

**Todos os 7 passos deste runbook estão concluídos** — mantido aqui só como registro histórico de como a migração foi planejada e executada (ver "Status" logo abaixo para o resumo final).

**Status:** ✅ MIGRAÇÃO EXECUTADA (26/06/2026). O `cerebro_maestro` agora usa `lyra_memory_v2` (BGE-M3 1024d) via `embed_service` :8001 — SEM fallback pro MiniLM (decisão do Antônio). Mudanças aplicadas:

- `_embed(texto)` chama `:8001/embed`; `_COLECAO = "lyra_memory_v2"` em todo lugar.
- `cerebro_maestro` NÃO importa mais sentence_transformers/torch/pyarrow → startup ~25s → ~3s.
- BM25 reconstruído sobre v2 (`build_bm25_index.py lyra_memory_v2`); backup do v1 em `bm25_index_v1_minilm.pkl.bak`.
- `embed_service` no boot (`lyra_boot.vbs` + `start_embed.bat`); `start_cerebro.bat` espera porta 8001.
- idle-unload 600s no embed_service: VRAM livre quando ocioso.
- Resiliência (não é fallback): se o embed_service cair, `buscar_hibrido` usa só BM25 e o chat segue sem contexto denso (logado).
- `buscar_memoria`/`salvar_memoria` no `lyra_tools.py` também migradas (helper `_embed_remoto` → :8001, coleção v2). lyra_tools não carrega mais MiniLM.
- ✅ `lyra_memory` (MiniLM 384d) APAGADA (qdrant_data 19.17GB → 14.16GB, ~5GB liberados).
- ✅ BM25 migrado `rank_bm25` → **bm25s** (esparso). `/buscar` ficou em **~382ms** (rank_bm25 sobre 3.08M dava ~2.1s). Índices antigos (`bm25_index.pkl`, backup v1) apagados — só `bm25s_index/` + `bm25s_meta.pkl` valem agora.
- Validação: 34/34 smoke tests, respostas corretas ("capital da França → Paris"), qualidade de recuperação superior ao MiniLM (comparação documentada).

### 🔵 Baixa / arquitetural

**Reescrever em C++/Rust não faz sentido agora.** Componentes pesados já são nativos (Ollama=Go+CUDA, Qdrant=Rust, SurrealDB=Rust). O Python é só cola de orquestração; gargalo real é latência do modelo e VRAM, não o runtime Python.

---

## 2.3.5. `test_smoke.py` recriado (01/07/2026) — arquivos de teste tinham sumido

Achado real: `test_smoke.py`, `test_migracao_v2.py` e `test_tools.py` — todos documentados no README.md/LYRA_TECNICO.md como existentes — **não existiam mais em lugar nenhum do disco** (busca em todo `C:\Lyra_Project` não achou nenhum `test_*.py`). `README.md` e os `requirements*.txt` continuavam intactos. Não há histórico git pra investigar quando/como sumiram (`C:\Lyra_Project` não é repositório git).

Recriado `test_smoke.py` do zero, cobrindo os 23 endpoints atuais do `cerebro_maestro.py` (17 checagens: GET's de leitura + 1 teste real de `POST /chat` com `modelo=groq`, opcional via `--rapido`). Propositalmente NÃO testa `POST /upload` (multipart), `POST /enxame` (custa tempo/tokens reais), `DELETE /historico` (destrutivo) nem `WEBSOCKET /ws/voice` (precisa áudio real) — listados como "não testado" no relatório final, não como falha.

**Resultado: 17/17 passou** — sistema saudável em produção nesta data. Recomendação: recriar `test_migracao_v2.py`/`test_tools.py` também fica pendente se fizer sentido (eram testes mais específicos de uma migração já concluída — talvez não valha a pena recriar exatamente iguais).

## 2.4. Auditoria frontend x backend (30/06/2026)

De 21 endpoints em `cerebro_maestro.py`, 11 têm chamada correspondente em `script.js` (`/chat` via WS hub :8765 → `lyra_app.py` → `/chat`, `/`, `/stats`, `/health`, `/tts/mudo`, `/tts/falar`, `/exportar`, `/upload`, `/metrics`, `/historico` DELETE, `/grafo/completo`). `/dashboard` é intencionalmente standalone (aberto direto no browser, não via pywebview) — não é órfão.

**Órfãos reais (sem consumidor no frontend, verificar se ainda fazem sentido expostos):** `GET /status`, `POST /enxame`, `GET /enxames`, `GET /enxame/{id}`, `POST /enxame/{id}/consolidar`, `GET /historico` (só o DELETE é usado), `GET /grafo` (só a versão `/grafo/completo` tem UI), `GET /resumo_sessao`, `GET /buscar`, `GET /memoria/categorias`.

**Achado mais relevante (RESOLVIDO 30/06/2026):** `WEBSOCKET /ws/voice` (`lyra_voice_live.py`, Gemini Live — voz bidirecional em tempo real) estava implementado no backend mas sem consumidor no frontend. Agora conectado:

- **Frontend:** novo botão `#voice-live-btn` (canto inferior direito, visualmente distinto do `#mic-btn` existente — são pipelines DIFERENTES: `mic-btn` é o wake-word local via `mic_engine.py`+faster-whisper; `voice-live-btn` é Gemini Live via `/ws/voice`). Captura microfone via `getUserMedia` + `AudioContext({sampleRate:16000})`, converte Float32→PCM16, manda por WS binário; toca áudio de resposta (24kHz) via `AudioBufferSourceNode` sequencial; mostra transcrição na bolha de chat existente (`_showBubble`); sincroniza `_setState()` com a esfera 3D. Arquivos: `index.html`, `style.css`, `script.js` (bloco `_vl*`/`_setupVoiceLive()`).
- **Bug de backend descoberto e corrigido no processo:** `lyra_voice_live.py` usava `GEMINI_LIVE_MODEL = "gemini-2.0-flash-live-001"`, que não existe mais pra essa API key (erro 1008 "model not found for bidiGenerateContent"). Único modelo com suporte a `bidiGenerateContent` disponível (confirmado via `GET /v1beta/models`): `gemini-2.5-flash-native-audio-latest`. Trocado. Esse modelo também só aceita **UMA** `response_modalities` por vez (`AUDIO` **ou** `TEXT`, nunca as duas — erro 1007 se combinar) — corrigido pra `response_modalities=["AUDIO"]` + `output_audio_transcription=types.AudioTranscriptionConfig()`, e o handler passou a ler o texto de `server_content.output_transcription.text` em vez de `model_turn.parts[].text`.
- Validado: handshake do `/ws/voice` conecta e fica aberto esperando áudio sem erro (testado via cliente `websockets` Python direto). Testado manualmente na UI real (WebView2): botão aparece, pede permissão de mic corretamente, estados visuais funcionam, erros são exibidos na bolha de chat sem travar a UI.
- **Não validado ainda:** áudio real ponta a ponta (nenhum microfone físico disponível nos ambientes de teste usados).

Nenhuma chamada em `script.js` aponta para endpoint inexistente.

## 2.5.5. Varredura de encoding/import em todos os scripts (01/07/2026)

Verificação sistemática de todos os `.py` de `Lyra_Ollama` contra os 2 bugs de Windows já documentados (seção 1): falta de `sys.stdout.reconfigure(utf-8)` em scripts que imprimem unicode E rodam com output redirecionado, e ordem errada de import `torch` antes de `pyarrow`.

**3 bugs reais encontrados e corrigidos** (mesma classe dos already achados em `validador_cortical.py`/`lyra_shadow_thoughts.py` nesta sessão): `lyra_telegram.py`, `lyra_browser.py`, `lyra_google_workspace.py` — todos têm bloco `if __name__ == "__main__":` que imprime `✓`/`✗`/`→` sem `reconfigure`. **`lyra_telegram.py` é o caso mais sério, não teórico:** `start_telegram.bat` roda ele com `>> telegram_startup.log 2>&1` (output redirecionado de verdade) — o bot travaria/morreria silenciosamente na primeira mensagem de log com esses caracteres. O bot nunca chegou a rodar em produção ainda (log file não existia, `TELEGRAM_BOT_TOKEN` está configurado no `.env` mas o bot não tinha sido iniciado) — bug latente, pego antes de causar problema real. Corrigido nos 3 arquivos.

**Sem problema de ordem `torch`/`pyarrow`** nos demais scripts do projeto — só os 2 casos já corrigidos antes existiam.

## 2.5.6. Varredura de segurança — segredos hardcoded (01/07/2026)

Busca por padrões de chave de API conhecidos (Groq `gsk_`, Google `AIza`, OpenAI `sk-`, Slack `xox`, GitHub `ghp_`) e por atribuições diretas tipo `api_key = "..."`/`password = "..."` em todo `.py`/`.js`/`.json`/`.bat`/`.vbs` do projeto, fora do `.env`. **Resultado: limpo.** Nenhuma chave real hardcoded, nenhum vazamento de conteúdo do `.env` copiado pra outro arquivo. As únicas credenciais fixas no código são `("root", "root")` do SurrealDB local — já documentado e aceito (ambiente 100% offline/local, seção 1). `.claude/settings.local.json` (allowlist de permissões do Claude Code) também conferido — só comandos, sem segredos.

## 2.5.6.1. Correção de segurança — CORS drive-by + Telegram default-deny (03/08/2026)

Auditoria de superfície de ataque real (bindings, CORS, auth, exec, upload, Telegram). Bindings todos em 127.0.0.1 ✅, `/upload` sanitiza filename ✅, `executar_comando` com rate limit + câmara de eco ✅. Dois problemas concretos encontrados e **corrigidos**:

1. **CORS aberto no cérebro (:8000)** — `cerebro_maestro.py` usava `allow_origins=["*"]` + `allow_credentials=True`, combinação em que o CORSMiddleware **ecoa qualquer Origin**. Consequência real: qualquer site aberto no navegador do Antônio podia ler a memória inteira (`/buscar`, `/historico`, `/exportar`, `/grafo`) e postar no `/chat` (que dispara ferramentas, incluindo `executar_comando`) — ataque drive-by via localhost; o binding 127.0.0.1 não protege porque a requisição sai do próprio navegador. **Fix:** `allow_origins=["null", "http://127.0.0.1:8000", "http://localhost:8000"]` + `allow_credentials=False` (frontend pywebview manda `Origin: null`; dashboard é same-origin; nada usa cookie). Verificado ao vivo após restart: origin estranho não recebe header CORS e preflight de POST `/chat` retorna 400; `Origin: null` continua permitido (frontend OK).
2. **Telegram allowlist vazio = mundo aberto** — `lyra_telegram.py` com `TELEGRAM_ALLOWED_USERS` vazio aceitava qualquer usuário do Telegram (com todas as ferramentas). Token está vazio hoje (bot inativo), mas era uma armadilha para quando fosse ativado. **Fix:** default-deny — o bot recusa iniciar sem allowlist configurado, com instruções no erro.

**Flagged, NÃO alterado (decisão consciente):** SurrealDB `("root", "root")` — local-only (127.0.0.1:8090), browsers não alcançam via CORS (Authorization exige preflight que o Surreal não libera), e trocar exige atualização coordenada em ~8 arquivos + restart do DB de produção. Continua aceito como na seção 2.5.6; revisitar se o Surreal um dia for exposto pra rede.

## 2.5.6.2. Melhorias de interação no frontend (03/08/2026)

Quatro melhorias pequenas de UX em `script.js`/`style.css` (pedido: melhorar interação/acesso sem mudanças significativas). Sintaxe validada (`node --check` + balanço de chaves CSS):

1. **Histórico de input estilo terminal** — `↑`/`↓` navegam pelas últimas 50 mensagens enviadas (antes `↑` só recuperava a última). Preserva rascunho ao entrar no histórico, ignora duplicatas consecutivas, e `↑` não rouba a seta de quem está editando texto novo (só entra com input vazio ou já navegando).
2. **Esc respeita empilhamento** — com o grafo de memória aberto, Esc fecha o grafo primeiro (antes fechava o chat escondido atrás do overlay); ordem: grafo > chat > painel.
3. **Drag & drop de arquivo** — arrastar imagem/áudio/vídeo de qualquer lugar da janela anexa como se fosse pelo clipe (mesmos tipos aceitos); borda do chat realça durante o arrasto (`#chat-terminal.drag-over`); abre o chat se estiver fechado; tipo não suportado dá toast. Contador de profundidade em dragenter/leave (eventos disparam por elemento filho).
4. **Feedback de upload** — toast "Enviando <arquivo>…" + botão de clipe pulsando (`#btn-attach.uploading`) até o `/upload` responder (antes não havia indicação nenhuma).

## 2.5.6.3. Auditoria visual completa — fontes, cores, casing, elegância (03/08/2026)

Revisão de todo o `style.css`/`index.html`/`script.js` a pedido do usuário ("reveja todo o frontend, melhore o máximo possível: fontes, letras minúsculas no começo de palavras, fontes despadronizadas, cores erradas, elegância, otimizar o motor"). Validado com `node --check` (JS), balanço de chaves (CSS) e screenshot headless via `msedge.exe --headless=new` do `index.html` antes/depois do boot (Three.js renderiza normal, cores batendo). Achados reais, todos corrigidos:

1. **Peso de fonte 500 nunca carregado** — `.msg-text strong` usa `font-weight: 500`, mas o `<link>` do Google Fonts só importava `100;200;300`. Todo texto em **negrito** dentro das mensagens da Lyra caía pra negrito sintético do navegador em vez do Inter Medium real. Import trocado pra `200;300;500` (peso 100 nunca era usado em lugar nenhum — removido, era download morto).
2. **Três azuis quase-idênticos sem fonte única de verdade** — `--neon: #00DDFF` (0,221,255) definida em `:root`, mas ~41 lugares usavam `rgba(0,220,255,*)` e mais 5 usavam `rgba(0,210,255,*)` hardcoded — três tons de ciano visualmente quase iguais mas nunca exatamente o mesmo, impossível de re-temizar sem caçar cada um. Unificados os 46 pontos pro valor exato de `--neon` (0,221,255).
3. **Cor do estado "idle" destoava** — `S_COLORS.idle` em `script.js` era `#00CCFF`, um azul diferente do `--neon` oficial (`#00DDFF`). Como "idle" é o estado padrão (a maior parte do tempo em que o app fica aberto), o dot central pulsava com a cor errada na prática. Corrigido pra `#00DDFF`.
4. **"Em Espera" em Title Case, único lugar destoando** — todo o resto da UI usa sentence case (só a primeira palavra maiúscula: "Abrir painel lateral", "Desativar resposta por voz"). `S_LABELS.idle = 'Em Espera'` capitalizava as duas palavras. Corrigido pra `'Em espera'`.
5. **Legenda do grafo sem o padrão dos rótulos HUD** — `.leg-item` ("tópico"/"evento"/"sobre"/"precedeu") era o único rótulo decorativo do app sem `text-transform: uppercase`, quebrando o padrão visual usado em `.panel-label`, `.boot-line`, `#state-indicator`, `.grafo-title`. Adicionado uppercase + letter-spacing consistente com os outros.
6. **Terceiro vermelho solto no toast** — `#toast` usava `rgba(255,90,90,0.25)`, um vermelho diferente do `#FF4466`/`#FF3355` já usados no resto do app (fechar/mudo). Consolidado: nova variável `--danger: #FF4466` em `:root`, aplicada no toast e nos 3 hovers de fechar que antes tinham o hex duplicado solto.
7. **Elegância — antialiasing explícito** — o app usa `font-weight: 200` (extra-light) como base; sem `-webkit-font-smoothing: antialiased` esse peso fica com serrilhado visível no Chromium/Electron. Adicionado ao `html, body` junto com `text-rendering: optimizeLegibility`.
8. **Motor — `prefers-reduced-motion` implementado** — nenhuma das ~8 animações infinitas (glow ambiente, pulsos, digitação do boot) respeitava a preferência de acessibilidade do SO. Adicionado bloco `@media (prefers-reduced-motion: reduce)` que desliga as decorativas sem afetar as transições curtas de abrir/fechar painéis.

**Verificado e descartado (não eram bugs):** cor do "Fonte" no painel lateral (`m.tier`) já vem capitalizada do backend (`cerebro_maestro.py:1640`, `_MAPA_TIERS` usa `"Groq"`/`"Gemini"`/`"Claude"`/`"Local"`); textos decorativos em minúscula (labels do painel, linhas de boot, placeholder do chat vazio) são intencionais — o CSS já os transforma em maiúsculas via `text-transform`, então a fonte em minúsculo no HTML/JS é só convenção de legibilidade do código-fonte, não um bug visual.

## 2.5.6.4. Grafo de memória quebrando — link órfão crashava o 3d-force-graph (03/08/2026)

Durante a auditoria visual acima, o usuário reportou o grafo "quebrado/desconfigurado" em tempo real. Reproduzido via script headless (`puppeteer-core` dirigindo `msedge.exe --headless=new`, apontando pro `index.html` local, chamando `abrirGrafo()` direto): console mostrava `Uncaught Error: node not found: evento:<uuid>` — o 3d-force-graph lança um erro **não tratado** quando um link referencia um id que não está no array de nós, e isso derruba a renderização inteira (não é cosmético, o grafo simplesmente não aparece).

**Causa raiz, confirmada no backend** (`cerebro_maestro.py:2126`, `/grafo/completo`): a query de `evento` tem `LIMIT {limite}` (pega só os N mais recentes por timestamp), mas as queries de `sobre`/`precedeu` (relações) não são sincronizadas com essa mesma janela — um link podia perfeitamente referenciar um evento fora dos N mais recentes, que nunca entrava no array `nodes`. Resultado: link "órfão" apontando pro vazio, e o 3d-force-graph crashava assim que topasse com um.

Não foi causado pelas mudanças de hoje (nada nos commits de UX/visual toca a lógica de dados do grafo) — provavelmente já falhava de forma intermitente dependendo de qual evento aleatoriamente ficava de fora da janela de `limite`.

**Fix em duas camadas:**

1. **Backend (correção na origem):** `cerebro_maestro.py:2126` — depois de montar `nodes`/`links`, filtra `links = [l for l in links if l["source"] in ids_vistos and l["target"] in ids_vistos]` antes de retornar. Zero órfãos possíveis a partir de agora.
2. **Frontend (defesa em profundidade):** `_renderGrafo()` em `script.js` agora filtra `links` contra o `Set` de ids de `nodes` antes de chamar `.graphData()` — protege contra regressão futura do backend ou dado velho já persistido, sem depender só do fix do lado servidor.

Verificado: `curl /grafo/completo?limite=300` → 298 nodes, 353 links, **0 órfãos** (script de checagem confirmou). Re-rodado o mesmo repro headless que capturou o crash original — sem erro no console, screenshot mostra o grafo renderizado normal (núcleo Lyra central, tópicos em dourado, eventos em azul, 353 conexões visíveis). `cerebro_maestro.py` reiniciado pra aplicar o fix.

## 2.5.6.3.1. Correção adicional pós-auditoria: cores hardcoded restantes em `script.js`

A consolidação de cores da seção 2.5.6.3 (item 2) só tocou `style.css`. Achado durante a investigação do grafo: `script.js` ainda tinha `rgba(0,210,255,*)` (4 ocorrências, tooltips do grafo) e `rgba(0,220,255,*)` (2 ocorrências, anel do mic) fora do padrão `--neon` (0,221,255). Não causavam bug — só inconsistência visual residual da mesma classe do item 2. **Corrigido** — mesmo find-and-replace aplicado, `node --check` validado.

## 2.5.6.5. Sessão noturna 04/08/2026 — debug geral, latência, conhecimento novo, voz Gemini, frontend offline

Sessão longa autônoma (Antônio dormindo; pedido: debug em tudo, otimizar latência, pesquisar novidades, ingerir repositórios de conhecimento, resolver voz, melhorar frontend, documentar). Backup do projeto (código+docs, 534KB, **sem .env** — chaves não vão pra nuvem) copiado pra `G:\Meu Drive\Backups_Lyra\lyra_backup_20260804.tar.gz` via Google Drive Desktop.

### Bug real corrigido: self-healing com falso-positivo de "FastAPI offline"

`cerebro_maestro.py` (loop proativo): o check de serviços a cada 5min chamava `lyra_seguranca.checar_servicos()` **síncrono direto no event loop** — o `requests.get` pro próprio :8000 bloqueava o loop, o servidor não respondia a si mesmo, timeout → "FastAPI offline" → tentativa de restart falhava (sem cmd configurado) → spam no log + notificação Windows de urgência alta a cada 5min. **Fix:** `asyncio.to_thread(...)` + skip do check "FastAPI" (se o loop roda, o processo está vivo por definição). Os outros erros do log (`AttributeError grafo_completo`, Groq 400 `divergencia_draft`) eram de versões antigas do código — já corrigidos anteriormente, log é acumulativo.

### 🔴 CRÍTICO — Qdrant e SurrealDB expostos na LAN + self-healing que apagava a memória silenciosamente (04/08/2026, tarde)

Achado durante manutenção de rotina (Antônio pediu pra "ir vendo a Lyra"), enquanto checava processos pra investigar a instalação de uma VPN: `netstat` mostrou Qdrant (:6333) e SurrealDB (:8090) ouvindo em `0.0.0.0`, não `127.0.0.1` — violando a regra crítica documentada na seção 1 deste arquivo. Isso significa: **qualquer dispositivo na mesma rede Wi-Fi/LAN podia conectar direto no Qdrant (sem autenticação) e no SurrealDB (`root`/`root`, credencial fraca já documentada mas até então considerada "aceitável" justamente por assumir bind local)**. Descoberto de bônus: o PC já tem **Radmin VPN** instalado (adaptador virtual 26.x.x.x) — outra rede pela qual a exposição também valia.

**Causas e fixes:**

- Qdrant: nunca teve `QDRANT__SERVICE__HOST` definido — Qdrant usa `0.0.0.0` por padrão quando omitido. Adicionado `set QDRANT__SERVICE__HOST=127.0.0.1` em `start_qdrant.bat`.
- SurrealDB: `--bind 0.0.0.0:8090` era **explícito** no `start_surreal.bat` (não omissão, alguém escreveu assim). Trocado pra `--bind 127.0.0.1:8090`.

**Durante a correção, apareceu um bug MUITO mais grave, ao vivo:** os comandos de restart automático do self-healing (`lyra_seguranca.py`, `_RESTART_CMDS`) **nunca foram atualizados junto com a evolução dos scripts de boot** e haviam divergido silenciosamente:

- `Qdrant`: o comando de restart não define `QDRANT__STORAGE__STORAGE_PATH` nem `QDRANT__SERVICE__HOST` — rodando assim, o Qdrant sobe apontando pra `C:\Lyra_Project\storage` (path default, pasta nova e **vazia**), não pra `qdrant_data\` (3M+ vetores reais). O self-healing reportaria "reiniciado com sucesso" enquanto a Lyra ficava com memória semântica **zerada** — silenciosamente, sem nenhum aviso de que os dados sumiram, só que a coleção "existe" (vazia). Isso é estritamente pior que o serviço ficar caído (que ao menos é visível).
- `SurrealDB`: o comando usava engine `rocksdb:` — os dados reais em disco são `surrealkv://` (confirmado pelos arquivos `.sst`/`vlog`/`wal`/`manifest`). Teria falhado ao abrir o storage.

**Como foi pego:** ao testar o fix do bind, parei o Qdrant manualmente pra reiniciar com a config corrigida — e bem nesse intervalo, o self-healing do `cerebro_maestro` (rodando em memória com o código ANTIGO, já que Python não recarrega módulos sozinho) detectou a queda e dispersou seu próprio restart buggy **ao mesmo tempo** que o meu manual. Resultado real, capturado ao vivo: dois processos `qdrant.exe` simultâneos, um em `127.0.0.1` com os 3M vetores certos, outro em `0.0.0.0` apontando pra uma coleção vazia recém-criada em `C:\Lyra_Project\storage\`. Deletado o processo e a pasta errados; **nenhum dado real foi perdido** (o storage antigo nunca foi tocado/sobrescrito — Qdrant só cria coleções vazias sob demanda, não apaga as existentes).

**Fix definitivo:** os três `_RESTART_CMDS` (SurrealDB/Qdrant/embed_service) agora chamam os próprios `start_*.bat` via `Start-Process` em vez de duplicar os comandos inline — uma fonte de verdade só, elimina a classe inteira de bug "restart diverge do boot normal". Também corrigido: `tentar_reiniciar_servico()` media sucesso com `time.sleep(3)` fixo — curto demais pro Qdrant carregar 3M vetores do disco (5-8s reais), causava falso-negativo ("não conseguiu reiniciar" mesmo quando conseguiu). Trocado por polling de até 20s.

**Bônus descoberto no caminho:** `qdrant.exe` não está no PATH do sistema (diferente de `surreal`/`ollama`, que estão) — e o `NoDefaultCurrentDirectoryInExePath=1` está setado como variável de ambiente do usuário (hardening de segurança do Windows que desliga a busca de executável no diretório atual). Combinação das duas coisas fazia `cd /d ...\bin` + `qdrant.exe` (nome sem caminho) falhar silenciosamente com "não é reconhecido como comando". `start_qdrant.bat` corrigido pra usar o caminho absoluto `"C:\Lyra_Project\bin\qdrant.exe"`.

**Validado ponta a ponta:** matei o Qdrant de propósito e chamei `tentar_reiniciar_servico("Qdrant")` direto (o código corrigido, em processo Python novo) — voltou em ~7s, bind `127.0.0.1`, `3.088.785` vetores intactos. Testado igual pro fluxo completo (restart + `cerebro_maestro` recarregado com o código novo + health check). Todos os `start_*.bat` restantes (screenpipe, telegram, embed, cerebro, ollama) auditados — usam caminho absoluto ou binário já confirmado no PATH, sem risco da mesma classe de bug.

**Decisão sobre o SurrealDB `root`/`root`:** com o bind agora corrigido pra 127.0.0.1, a avaliação de risco original da seção 2.5.6.1 volta a valer de fato (antes ela avaliava um cenário que na prática não era o real, já que o bind estava errado). Mantido como está.

### Latência: embed_service agora estaciona o modelo na RAM (era o cold start do RAG)

`/buscar` dava timeout >10s na 1ª chamada pós-idle: o idle-unload do embed_service (600s) descartava o BGE-M3 inteiro e a próxima query pagava reload do disco. **Fix em `embed_service.py`:** `_descarregar_impl` agora move o embedder pra RAM (`model.to('cpu')`, ~2.3GB fp16, máquina tem 64GB) em vez de destruir; `_garantir_modelo` reativa com `.to('cuda')`. **Medido: reativação 0.32s** (vs 5-15s reload). VRAM liberada igual (8MB residual). Reranker mantém unload completo (menos usado). `/health` ganhou campo `estacionado_ram`.

### Conhecimento novo ingerido: 1.480 vetores de documentação de referência (4 categorias novas)

Novo script `ingest_webdocs.py` (idempotente, uuid5 por url#chunk): crawleia docs curadas com crawl4ai → chunks ~1400 chars → BGE-M3 via :8001 em lotes → upsert `lyra_memory_v2`. 38/38 páginas ok: **referencia_database** (317 — PostgreSQL, SQLite, Redis, MongoDB, Qdrant, SurrealDB), **referencia_frontend** (627 — MDN CSS/JS, web.dev, patterns.dev, React, Three.js), **referencia_webdev** (256 — HTTP caching/CORS/WebSockets, OWASP Top 10, FastAPI, 12factor), **referencia_llm** (280 — Anthropic prompt eng/agents, OpenAI cookbook, Prompting Guide, Lilian Weng, Chip Huyen). Verificado: busca semântica retorna o conteúdo novo. **Limitação conhecida:** índice BM25 é pré-construído e não contém os pontos novos — o lado denso do RAG híbrido cobre; rebuild do BM25 (3M docs) fica pra uma sessão futura.

### Voz: Gemini TTS implementado como 1º da cadeia (PRIMEIRA opção nova desde o esgotamento)

`audio_manager.py` reescrito: cadeia agora é **Gemini TTS nativo → edge-tts Francisca → silêncio** (voz online é permitida — confirmado por Antônio em 23/06). Modelo `gemini-2.5-flash-preview-tts`, voz `Leda` (feminina/suave), com instrução de estilo. PCM 24kHz embrulhado em WAV; cache aceita .wav (Gemini) e .mp3 (edge). **Testado sem reproduzir áudio** (madrugada): WAV válido de 6.2s gerado; latência ~4s/frase curta (vs ~1s edge, qualidade muito superior). **Trade-off crítico descoberto: free tier = 3 req/min** — estourou no pré-cache e o fallback pro edge funcionou exatamente como projetado. Amostra pro Antônio ouvir: `Lyra_Core/Sons/cache/teste_gemini_voz.wav`. Decisão final de manter/reverter é dele após ouvir.

### Frontend: 100% offline (vendor/) + toques de elegância

- **CDNs eliminados** — o "faltava alguma coisa" do motor: three.js r128, 3d-force-graph 1.73.4 e a fonte Inter (variável v20, subsets latin+latin-ext, cobre pesos 100-900 num arquivo) agora vivem em `Front_end_Lyra/vendor/`. Sem internet, antes a esfera nem renderizava e a fonte caía pro fallback; agora o app é idêntico offline (Ring 0). **Validado com teste headless bloqueando toda request externa**: esfera renderizou, tipografia correta, zero requests a CDN.
- **Elegância (tendências 2026 — glass em camadas, micro-interações com propósito):** modal do chat ganhou gradiente vertical sutil de vidro + `saturate(1.15)` no backdrop + inset inferior escuro (profundidade real sem ruído); mensagens ganharam hover que levanta 1px e acende a borda (sinaliza interatividade dos botões copiar/ouvir que aparecem no hover).

### Pesquisa de novidades (04/08/2026)

- **Modelo local:** qwen3:8b segue sendo o melhor da faixa 8GB VRAM em 2026 (fontes: llmhardware.io, morphllm.com, localaimaster.com) — Lyra já está no estado da arte local. Anotado pra avaliar: **Qwen3-VL-7B** como VLM local (multimodal na mesma faixa de VRAM).
- **Tendências frontend 2026** (digitalupward, lucky.graphics, midrocket): dark-first, glassmorphism sutil em camadas, micro-interações com propósito — direção que a Lyra já segue; aplicados os refinamentos acima.

## 2.5.6.6. Auditoria noturna 04/08/2026 (noite) — regressão de binding em launcher órfão, localhost residual, BM25 rebuild

Auditoria autônoma completa (segurança → correções → docs → latência → mercado). Resultados:

**Segurança:**

1. **`lyra_launcher.py` (raiz do projeto) violava a regra de binding** — SurrealDB com `--bind 0.0.0.0` explícito e Qdrant sem `QDRANT__SERVICE__HOST` (default 0.0.0.0). Mesma classe do vazamento LAN corrigido em 04/08 (seção 2.5.6.5), mas neste arquivo ficou de fora porque ele NÃO é usado no boot (lyra_boot.vbs usa os start_*.bat) — launcher alternativo órfão, armadilha latente. **Corrigido** (bind 127.0.0.1 + env do Qdrant). Bindings ao vivo reconferidos via netstat: 6333/8000/8001/8090 todos em 127.0.0.1 ✅.
2. **`localhost` residual em chamadas/binds internos** (regra: sempre 127.0.0.1) — corrigidos: `lyra_app.py` (bind do hub WS :8765 — era `websockets.serve(..., "localhost")`), `mic_engine.py`/`webcam.py` (WS_URL), e 4 scripts de ingestão (`final.py`, `vetorizar_todos.py`, `fix_faquad_brquad.py`, `ingestao.py` — DB_URL ws://8090).
3. **CORS do :8000** — segue correto (allowlist + credentials off). `/mcp` não reabre superfície: exclui destrutivos, e POSTs JSON exigem preflight que o CORS bloqueia.
4. **Guard-rails** — todo dispatch de tool passa por `checar_rate_limit` + Câmara de Eco (`cerebro_maestro.py` ~1003-1016). Nenhuma feature nova contorna.
5. **Telegram default-deny** — código OK; docstring dizia "vazio = qualquer usuário" (desatualizada, corrigida).
6. **Segredos** — 2 chaves `AIza...` encontradas em `Memoria_Lyra/backups/20260624_160305/base_{codigo,conversas}.json`: NÃO são as chaves do Antônio (não batem com .env, não aparecem em código) — artefatos de datasets públicos ingeridos. Sem ação; se quiser higiene total, apagar/regenerar esses backups antigos.

**Correções/validações:**

- `test_smoke.py`: 16/16 ✅ (1ª rodada falhou `/buscar` por timeout de cold start — timeout do teste subido 15s→45s, falso-negativo eliminado).
- `reconciliar_episodios.py`: 0 órfãos de 113 eventos pós-migração — SurrealDB↔Qdrant consistente.
- `requirements.txt` vs pip freeze: só 2 divergências (`google-auth-httplib2` 0.2.0→0.4.0 real, `google-auth-oauthlib` 1.4.0→1.2.4 real) — arquivo corrigido.
- `except Exception`: re-varredura focada em engolimento silencioso (`pass`/`continue`) — todos são os idiomas já aceitos (guard de `stdout.reconfigure`, cleanup, campo opcional). Nenhum bug escondido novo.
- **BM25 rebuild** — índice era de 26/06 (3.087.193 docs) vs 3.088.785 pontos atuais (~1.6k docs fora: webdocs 04/08 + episódios). Rebuild rodado via `build_bm25_index.py`. **Pegadinha Windows descoberta:** o cerebro carrega o índice com `mmap=True` — os arquivos ficam com handle aberto e o `bm25s.save` não consegue truncá-los; é preciso reiniciar o `cerebro_maestro` ANTES do save do rebuild (ou nunca ter chamado `/buscar` desde o boot). Feito nessa ordem; resultado abaixo.
- **BM25 rebuild CONCLUÍDO:** 3.088.789 docs em 386s (índice de 26/06 tinha 3.087.193). O 1º rebuild FALHOU no save com `OSError errno 22` (= erro Windows 1224, arquivo com seção mmap ativa — o cerebro carrega o índice no STARTUP via `carregar_indice`, não lazy). Solução definitiva: `build_bm25_index.py --novo` salva em `bm25s_index_new/`+`bm25s_meta_new.pkl` (novo parâmetro `out_dir`/`out_meta` em `construir_indice`); swap de pastas com o cerebro parado (~10s de downtime) e restart. Validado: `/buscar` "OWASP top 10" retorna `referencia_webdev` com `bm25_score` real (antes só o lado denso achava os webdocs). Rollback disponível em `bm25s_index_old.bak`/`bm25s_meta_old.pkl.bak` (1GB — apagar quando confiar no novo).

**🔴 Regressão grave de latência encontrada e corrigida — draft do spec-decoding com `keep_alive=0`:**

Ao re-medir latência, `/chat` estava em **~9.5-10s** (baseline ~1s). Causa em duas partes:

1. **Ollama estava FORA DO AR** (descoberto porque `/chat` ficava em 2.5s com ele morto e 9.5s com ele vivo — o draft falhava rápido vs. rodava lento). Andar local da cascata morto sem ninguém saber. Religado. **Self-healing não cobria Ollama** — adicionado aos `_RESTART_CMDS` de `lyra_seguranca.py` (mesmo padrão start_*.bat); validado matando o processo e chamando `tentar_reiniciar_servico("Ollama")` → voltou ok.
2. **`keep_alive=0` no draft qwen3:0.6b** (`_rodar_draft`): descarregava o modelo após CADA chamada → todo `/chat` pagava reload de ~10-11s (medido direto no Ollama: keep_alive=0 → 11.1s/chamada; keep_alive=300 → 236ms quente, **50x**) e o endpoint bloqueava até 8s no `wait_for` do draft antes do `[DONE]`. **Fix: `keep_alive=300`** (custo ~1GB VRAM por 5min; cenário "draft+local juntos" só existe com as 3 nuvens caídas, Ollama faz offload parcial). **Medido após fix: `/chat` ~2.0s estável** (inclui draft + comparação de embeddings; baseline de ~1s era pré-spec-decode). `/buscar` quente ~630-660ms (vs 382ms de 26/06 — diferença é reranker+grafo+writes de retrieval_count já existentes, índice 1GB maior; sem regressão nova identificável além do já documentado).

Smoke final pós-tudo: **16/16** ✅.

**Mercado (04/08/2026):** Groq deprecou `llama-3.1-8b-instant`/`llama-3.3-70b-versatile` em 17/06/2026 — cascata NÃO afetada (já usa `openai/gpt-oss-120b`); input cacheado do gpt-oss-120b caiu pra $0.075/M. Qwen3-VL (7B/8B) confirmado viável em 8GB VRAM, forte em OCR multilíngue (relevante pra PT-BR) — candidato concreto a substituir `llava-phi3` como fallback de visão local; download grande, fica pra decisão do Antônio (Llama 3.2 Vision 11B é alternativa citada como melhor uso geral, mas mais apertada em VRAM).

## 2.5.7. `requirements.txt` conferido contra instalação real (01/07/2026)

`pip freeze` real comparado pacote a pacote com `requirements.txt`. Achados e corrigidos:

- **Versões desatualizadas no arquivo** (instalado é diferente do documentado): `pydantic` (2.13.4→2.12.5 real), `groq` (1.5.0→1.0.0 real), `google-genai` (2.10.0→**1.65.0** real, diferença grande), `requests`, `pypdf`, `pillow`, `pywin32`.
- **`bm25s` faltava inteiramente** do arquivo, apesar de ser a lib realmente importada em produção (`bm25_index.py`) desde a migração de 26/06.
- **`rank-bm25` sobrando** — confirmado via grep que não é importado em lugar nenhum do código atual (substituído por `bm25s`). Removido do arquivo.
- **`torch`/`torchvision`/`torchaudio`** atualizados pra 2.6.0/0.21.0/2.6.0+cu124 (migração do venv_embed desta sessão).
- **`requirements_embed.txt` REMOVIDO** (arquivo obsoleto — descrevia dependências do `venv_embed`, que foi aposentado nesta sessão). `README.md` atualizado pra não referenciar mais esse arquivo/venv.

## 2.5.8. Auditoria de `lyra_tools.py` (01/07/2026) — 2823 linhas, 66 ferramentas

Resultado: **código limpo, sem achados graves.**

- Imports: todos os 8 imports de topo (`os`, `json`, `shutil`, `subprocess`, `pathlib`, `re`, `time`, `uuid`, mais `datetime`/`timedelta`/`Any`) estão em uso ativo — nenhum import morto.
- Funções mortas: verificado (heurística: cada uma das 66 funções top-level referenciada em algum outro lugar do `Lyra_Ollama`, não só na própria definição) — **nenhuma função órfã encontrada**.
- Docstrings: 63/69 funções (91%) têm docstring. As 6 sem docstring são todas helpers privados (`_get_qdrant`, `_escanear_riscos`, `_tail`, `_run_crawl4ai`, `on_created`, `_esc`) — não são ferramentas expostas em `TOOLS_MAP`, prioridade baixa.

## 2.5.9. Auditoria de `except Exception` fora do `cerebro_maestro.py` (01/07/2026)

9 ocorrências no total entre `lyra_tools.py` (4), `lyra_agentes.py` (2), `lyra_agent.py` (2), `embed_service.py` (1). Todas revisadas — **todas são degradação deliberada, nenhuma esconde bug real:**

- `lyra_tools.py:1227` — `buscar_url`/crawl4ai falha → cai pro fallback `requests`+`BeautifulSoup` (comentário explícito no código).
- `lyra_tools.py:1267,1271` — campos opcionais da API de clima (wttr.in) ausentes → default para string vazia.
- `lyra_tools.py:1804` — enumeração de controles de janela via `pywinauto`, pula controle malformado individual num loop.
- `lyra_agentes.py`/`lyra_agent.py` (2 cada, mesmo padrão) — parse de `arguments`/resultado de tool-call em JSON, fallback pra `{}`/dict genérico se malformado (mesmo padrão já usado e aceito em `cerebro_maestro.py`).
- `embed_service.py:69` — parse de flag CLI (`--idle N`) pra inteiro, fallback pro default se o usuário passar algo inválido.

## 2.5.10. Limpeza de arquivos órfãos (01/07/2026)

Removidos: 3 pastas `__pycache__` (Lyra_Ollama, Lyra_Core, Lyra_Core/Front_end_Lyra — regeneram sozinhas, sem risco), 2 arquivos de log de teste órfãos em `lyra_processos_bg_logs/` (`*_teste_smoke_proc.log`, resquício de teste do `iniciar_processo_bg` de 25/06). Conferido: sem `.pkl` antigos sobrando (só `bm25s_meta.pkl` ativo), sem `.bak` soltos, sem arquivos temporários óbvios na raiz do `Lyra_Ollama`.

## 2.5.11. Rotação de logs de boot (01/07/2026)

`qdrant_startup.log` estava em 936KB, `cerebro_startup.log` em 227KB, sem rotação — cresceriam indefinidamente enquanto a máquina ficasse ligada sem reiniciar os serviços. Adicionado rotação simples nos 5 `.bat` que fazem `>> log 2>&1` (`start_qdrant.bat`, `start_cerebro.bat`, `start_embed.bat`, `start_surreal.bat`, `start_ollama.bat`): antes de anexar, verifica se o log passou de 5MB — se sim, move pra `.old` (mantém só 1 rotação) e começa um arquivo novo. `maestro.log` do `cerebro_maestro.py` não precisava (já é sobrescrito do zero — `open(..., "w")` — a cada restart, não usa append).

## 2.5.12. Organização de `.md` na raiz do Lyra_Ollama (01/07/2026)

Conferido: nenhum arquivo `.md` solto em `Lyra_Ollama/` ou subpastas — toda a documentação já vive corretamente em `README.md` (raiz do projeto) e `Memorias Do Projeto/`. Nada a organizar aqui.

## 2.5.13. Investigação: por que só ~40 episódios no Qdrant (01/07/2026)

Comparação `SELECT count() FROM evento` no SurrealDB (162) vs contagem de `categoria=episodio` no Qdrant (44) parecia um vazamento grave (73%), mas a maior parte é esperada:

- **104 dos 162 eventos são de ANTES da migração BGE-M3** (24-26/06) — legitimamente vetorizados só na coleção v1 (MiniLM), que foi **apagada de propósito** na migração (decisão já documentada). Não é bug.
- **Pós-migração (≥26/06): 58 eventos no SurrealDB vs 44 no Qdrant — gap real de 14 (24%).**

**Causa provável do gap real:** `registrar_evento()` (`cerebro_maestro.py:339`) grava no SurrealDB e no Qdrant como **duas operações não-atômicas em sequência** — primeiro SurrealDB, depois `_embed()` + `qdrant_client.upsert()`. Se o processo do `cerebro_maestro.py` for morto/reiniciado no meio (exatamente o que aconteceu várias vezes NESTA sessão, durante os testes do refactor da cascata e da migração do venv_embed), o evento fica gravado no SurrealDB mas nunca chega a ser vetorizado — sem erro visível, sem retry, sem mecanismo de reconciliação/backfill entre os dois bancos.

**Não é uma falha ativa do sistema em uso normal** (reinícios do cérebro são raros fora de sessões de manutenção como esta) — mas era uma lacuna arquitetural real: não existia um job que reconciliasse "eventos no SurrealDB sem vetor correspondente no Qdrant" automaticamente, só o script manual `reconciliar_episodios.py` (rodado uma vez em 01/07, 15 episódios recuperados).

**✅ Fechada (02/07/2026):** `reconciliar_episodios.py` ganhou parâmetro `silencioso: bool` (suprime os `print()`, mantém o CLI original intacto) e passou a retornar um `dict` (`eventos_verificados`/`orfaos_encontrados`/`reconciliados`) em vez de só imprimir. `loop_proativo()` em `cerebro_maestro.py` agora chama `reconciliar(dry_run=False, auto_fix=True, silencioso=True)` a cada 60 iterações (~1h, mesmo padrão de agendamento do Shadow Thoughts a cada 180 iterações/~3h), em `asyncio.create_task` — não bloqueia o loop. Só loga quando `orfaos_encontrados > 0`, silêncio total quando o sistema já está consistente (caso comum). Testado isoladamente antes de integrar: retornou `{'eventos_verificados': 78, 'orfaos_encontrados': 0, 'reconciliados': 0}` — sistema consistente no momento do teste. Backend reiniciado com a mudança, `/status` confirmado saudável.

## 2.5.14. Benchmark de latência de ferramentas (01/07/2026)

Medido diretamente via `lyra_tools.py` (chamada de função pura, sem passar pelo `/chat`):

| Ferramenta | 1ª chamada (fria) | Chamadas seguintes (quente) |
|---|---|---|
| `checar_saude_sistema()` | 1378ms | — (não repetido) |
| `consultar_clima("Marilia")` | 1978ms | ~1000-1250ms (3 chamadas) |
| `buscar_memoria(..., top_k=3)` | **8038-9472ms** | **128-147ms** (3 chamadas) |
| `gerenciar_lembretes(acao="pendentes")` | 43ms | — |

**Achado real:** `buscar_memoria()` tem um custo de "aquecimento" de ~8-9.5s só na 1ª chamada de um processo novo (provavelmente carregando o índice BM25/cliente Qdrant pela primeira vez, lazy-load) — cai pra ~130-150ms nas chamadas seguintes, ~60x mais rápido. Isso é esperado no processo de longa duração do `cerebro_maestro.py` (paga o custo uma vez só no boot), mas relevante pra quem for medir/testar essa função isoladamente (ex: scripts standalone) sem saber desse comportamento. `consultar_clima` fica estável (~1-1.2s) — é latência de rede real da API externa (wttr.in), fora do nosso controle.

## 2.5.15. Variáveis de ambiente documentadas (01/07/2026)

Levantamento completo via grep de `os.environ`/`os.getenv` em todo `Lyra_Ollama`. Só **4 variáveis reais configuráveis pelo usuário** (o resto que aparece em `os.environ["X"] = ...` são constantes que o próprio código FORÇA, tipo `HF_HUB_OFFLINE`, `TOKENIZERS_PARALLELISM` — não são configuração do usuário):

- `GROQ_API_KEY`, `GEMINI_API_KEY` — cascata de chat (obrigatórias).
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS` — bot Telegram (opcionais).

Todas as 4 já estavam presentes no `.env` real. Criado `Lyra_Ollama/.env.example` (não existia) documentando as 4, e `README.md` atualizado — antes só mencionava 2 das 4.

## 2.5.16. Documentação do endpoint `/mcp` (01/07/2026)

`GET/POST /mcp` (montado em `cerebro_maestro.py` via `fastapi_mcp.FastApiMCP`) expõe **todos os endpoints REST do cérebro como ferramentas MCP** (Model Context Protocol) — qualquer cliente MCP (Claude Code, Cursor, Continue, etc.) pode se conectar e usar a memória híbrida, grafo SurrealDB, enxames e métricas da Lyra como ferramentas nativas. Exclui de propósito: `/chat` (streaming SSE incompatível com o formato MCP), `/dashboard` (HTML), `/upload` (multipart), `/historico DELETE` (destrutivo), `/tts/mudo` (controle interno).

**Achado:** já existia documentação completa disso — em `C:\Lyra_Project\instrucoes.md` (arquivo na raiz do projeto, fora dos 3 `.md` canônicos de `Memorias Do Projeto/`, não referenciado por nenhum deles até agora). Esse arquivo é uma lista de "tarefas manuais pendentes" do Antônio (Telegram, Google Workspace, Screenpipe, atualização do SurrealDB, registro do MCP) — vale a pena ele conferir, tem pelo menos 5 itens ainda não confirmados como feitos (seção "Resumo rápido" do arquivo). Registrando aqui a referência cruzada pra não se perder de novo.

## 2.5. Referência da API HTTP (`cerebro_maestro.py` :8000)

> Atualizado 02/07/2026 — lista conferida direto contra `grep '@app\.' cerebro_maestro.py` (todas as rotas reais do código, nenhuma tabela desatualizada). Endpoints principais cobertos por `test_smoke.py` (17 checagens).

| Método | Rota | Descrição |
|--------|------|-----------|
| GET  | `/` | Ping — `{servico, ativo, versao}`. Usado pelo frontend pra checar conexão. |
| GET  | `/dashboard` | Dashboard de monitoramento HTML standalone (abre no navegador). Polla health/stats/metrics. |
| GET  | `/status` | Estado do cérebro (cerebro_ativo, qdrant, embedder, tts_mudo, carga_cognitiva). |
| GET  | `/health` | Latência real de Qdrant/SurrealDB/Ollama + VRAM (nvidia-smi) + contagem de vetores. |
| GET  | `/metrics` | CPU/RAM (psutil) + GPU/VRAM% (nvidia-smi, cache 4s) + latência último chat. |
| GET  | `/stats` | **Telemetria da cascata**: usos/falhas/latência média/taxa de sucesso por andar + distribuição %. Persiste em `telemetria.json`. |
| GET  | `/stats/historico?limite=` | Snapshots históricos da telemetria (~1/5min, `telemetria_historico.jsonl`) — tendência ao longo do tempo, não só acumulado desde o último restart. |
| POST | `/chat` | Chat principal (SSE streaming). Body: `{texto, modelo}`. modelo: auto\|groq\|gemini\|claude\|local. |
| GET  | `/buscar?q=&top_k=&categoria=` | Busca híbrida (BM25+denso+RRF+recência+freshness+rerank). |
| GET  | `/grafo?q=&limite=` | Traversal de grafo SurrealDB por keywords. |
| GET  | `/grafo/completo?limite=` | Grafo completo (nodes+links) pro visualizador 3D do frontend. |
| GET  | `/memoria/categorias` | Composição da base de conhecimento por categoria (contagem aproximada Qdrant). |
| GET  | `/historico` | Histórico em memória completo (inclui `fontes_rag`/`divergencia_draft` por resposta). |
| DELETE | `/historico` | Limpa histórico em memória (não afeta SurrealDB/Qdrant). |
| GET  | `/resumo_sessao` | Briefing + histórico (preview). |
| GET  | `/exportar` | Exporta a sessão como markdown. |
| POST | `/tts/mudo` | Liga/desliga voz global. Body: `{mudo: bool}`. |
| POST | `/tts/falar` | Dispara TTS pra texto arbitrário. Body: `{texto}`. |
| POST | `/upload` | Upload de imagem/áudio do chat. |
| POST | `/enxame` | Cria enxame de sub-agentes. Body: `{objetivo, subtarefas[], max_paralelo}`. |
| GET  | `/enxames?limite=` | Lista os enxames mais recentes (resumo). |
| GET  | `/enxame/{id}` | Status do enxame + subtarefas. |
| POST | `/enxame/{id}/consolidar` | Consolida resultados via LLM. |
| POST | `/agente` | Roda `lyra_agent.py` (loop ReAct autônomo) com um objetivo. Body: `{objetivo, max_iteracoes}`. |
| GET  | `/agente/runs?limite=` | Lista execuções recentes de `/agente` (tabela `agente_run`). |
| POST | `/shadow_thoughts` | Dispara manualmente o ciclo de sono (NREM/REM/DEEP) — normalmente automático a cada 3h via `loop_proativo`. |
| `WEBSOCKET` | `/ws/voice` | Voz bidirecional em tempo real via Gemini Live API (`lyra_voice_live.py`). |
| `GET/POST` | `/mcp` | Todos os endpoints REST acima expostos como ferramentas MCP (exclui `/chat`, `/dashboard`, `/upload`, `DELETE /historico`, `/tts/mudo`). |

**Telemetria (`/stats`)** — num sistema de cascata de 4 andares, saber qual andar atende a maioria e quem falha é essencial. Estrutura em `telemetria.json`: `{total_chats, tiers:{nome:{usos,falhas,latencia_total_ms}}, iniciado_em}`. Frontend mostra distribuição % no painel lateral.

## 2.6. Módulos existentes não documentados até 30/06/2026 (agora registrados)

- **`lyra_browser.py`** — navegação web via browser-use + Playwright, importado por `lyra_tools.py`.
- **`lyra_google_workspace.py`** — Gmail + Calendar via OAuth2, importado por `lyra_tools.py`.
- **`lyra_telegram.py`** — bot Telegram bidirecional, processo próprio, consome `/chat` via SSE.
- **`lyra_voice_live.py`** — Gemini Live API (voz tempo real), exposto em `WEBSOCKET /ws/voice` (ver 2.4 — sem consumidor no frontend ainda).

---

## 3. Hybrid RAG (arquitetura recomendada)

Status atual: naive RAG (dense-only no Qdrant) — 10-15% falso negativo em jargão, números e negações.

```
Query → [BM25 sparse] + [Dense vetorial] + [ColBERT opcional] → merge (RRF) → reranker → top-K → LLM
```

- **BM25** (`rank_bm25`): ~1-5ms, acerta nomes próprios/siglas/código exato.
- **Dense**: paraphrase-multilingual-MiniLM-L12-v2, ~80ms, acerta semântica/sinonímia.
- **ColBERT** (colbert-v2): reranker token-a-token, ~50-100ms, entende negações/ordem.
- **Merge**: BM25 (peso 0.3) + Dense (peso 0.5) → reranker → top-K.
- **Impacto esperado:** F1 65-70% → 80-85%; falsos negativos 12-15% → 3-5%; +70-120ms latência.

---

## 4. Módulo de Expansão & Modo Construção

### Interface de Voz Duplex com VAD (interrupção ativa)

`mic_engine.py` roda Silero VAD em thread paralela; ao detectar voz humana durante reprodução, envia `kill` ao player e limpa o buffer. Healthcheck/fallback obrigatório (VAD_TIMEOUT = 5.0s → revert para walkie-talkie).

### Validador Cortical de RAG (`validador_cortical.py`)

Gera perguntas sintéticas a partir de registros aleatórios do `Db_CORTEX` e mede Hit Rate (top-K) e MRR. Política de rollback automático: Hit_Rate_Min 85% | MRR_Min 0.68.

### Task-Aware Budgeting (coletor semântico por escopo cognitivo)

Detecta transição de domínio (chat casual → debug técnico) e resume (não descarta) mensagens de baixa densidade técnica, para evitar estouro de tokens e "lost in the middle".

### Modo Construção — chaveamento de modelos

| | Modo Chat | Modo Construção |
|---|---|---|
| Modelo | Cascata cloud ou qwen3:8b | Qwen3.6 27B / DeepSeek-R1 32B distilled |
| Hardware | 8GB VRAM | 64GB RAM (GPU offload) |
| Vazão | >40 tok/s | 5-10 tok/s |

**LM Studio** (`:1234`, ephemeral) para descobrir camada ótima de GPU offloading. Risco: ambos carregando o mesmo modelo → CUDA OOM. LM Studio nunca deve auto-iniciar.

### Interface Split-Pane (Modo Construção)

Painel esquerdo = chat; painel direito = renderizador de código (Prism.js/Monaco) acionado via `render_artifact` quando `escrever_arquivo`/`editar_arquivo` é chamado.

### Sandbox de arquivos do agente
>
> **⚠️ NÃO IMPLEMENTADO (confirmado 01/07/2026).** Isto é só um esboço de design — `grep -r "WORKSPACE_SEGURO"` em todo `Lyra_Ollama` não encontra nenhuma ocorrência real no código, e a pasta `C:\Lyra_Project\Workspace\Sandbox\` não existe no disco. Se algum dia isso for implementado de verdade, criar a pasta E o código de validação — nenhum dos dois existe hoje.
```python
WORKSPACE_SEGURO = os.path.abspath("C:\\Lyra_Project\\Workspace\\Sandbox\\")
def validar_caminho_seguro(path_alvo):
    path_absoluto = os.path.abspath(path_alvo)
    if not path_absoluto.startswith(WORKSPACE_SEGURO):
        raise PermissionError("Acesso bloqueado: o agente tentou evadir a Sandbox.")
    return path_absoluto
```

---

## 5. Front-end — Topologia Neuronal (axônios/pulsos sinápticos no `script.js`)

**Contexto atual:** `_buildSphere()` gera partículas em 3 camadas via `THREE.Points`; `animate()` rotaciona e pulsa opacidade. Posições ficam só no `BufferAttribute` — precisa extrair para criar curvas dos axônios.

**Passo 1** — Guardar posições individuais em `particlePositions = [{x,y,z,layer}]`. Só camada 0 (60 pontos) vira terminal de axônio.

**Passo 2** — `_buildAxons()`: para cada partícula da camada 0: `THREE.QuadraticBezierCurve3` → `getPoints(24)` → `THREE.BufferGeometry` → `THREE.LineBasicMaterial` com `AdditiveBlending`, opacidade base 0.

**Passo 3** — `_updateSynapticPulses(t)`: disparos como processo de Poisson (~0.08/s base). Pool `activePulses`, duration 0.4-1.2s, peakOpacity 0.10-0.45. Reatividade: `processing` → taxa 4x; `speaking` → pulsos rápidos (0.15s); `idle` → quase imperceptível.

```js
const AXON_CONFIG = {
    layerIdx: 0, segments: 24, cpJitter: 12, baseOpacity: 0.0,
    pulseRateIdle: 0.05, pulseRateActive: 0.22,
    durationMin: 0.4, durationMax: 1.2,
    peakOpMin: 0.10, peakOpMax: 0.40,
};
```

**Ordem de implementação:** globals → popular em `_buildSphere()` → `_buildAxons()` no `init()` → `_updateSynapticPulses(t)` no `animate()` → integrar taxa ao `_setState()` → ajustar visualmente.

> **Axônios — DESCARTADO (01/07/2026).** Chegou a ser implementado e testado (renderizava sem erro), mas o Antônio pediu explicitamente pra não fazer — revertido. Não reimplementar sem pedido novo.

### 5.1. Painel lateral — implementado (26/06/2026)

O painel lateral (`#side-panel`, toggle no canto superior esquerdo) agora tem:

- **conexões** — dots ws :8765 + cerebro :8000
- **estado** — estado atual + fonte (qual modelo respondeu)
- **modelo** — seletor manual da cascata (persiste em localStorage)
- **atividade** — latência / cpu / ram / **gpu / vram** (novos) + sparkline de latência. Poll `/metrics` a cada 4s.
- **telemetria** (novo) — total de chats + distribuição % por andar da cascata. Poll `/stats` a cada 10s (`_setupHealth()`).
- **serviços** (novo) — dots qdrant/surreal/ollama com latência real. Poll `/health` a cada 10s.

**Chat** — header tem botões: exportar conversa (.md, `exportarConversa()`), limpar histórico (`limparHistorico()`), fechar. Cada mensagem da Lyra tem botão copiar + **reler em voz alta** (`_addSpeakButton()` → `POST /tts/falar`).

---

## 6. Datasets ingeridos

Schema normalizado em todas as tabelas: `{ titulo, texto (max 3000), fonte, categoria }`.

| Tabela | Dataset | Conteúdo |
|---|---|---|
| `wiki_conhecimento` | wikimedia/wikipedia "20231101.pt" | 1.112.246 artigos PT-BR |
| `base_codigo` | nickrosh/Evol-Instruct-Code-80k-v1 | 80k pares instrução/código |
| `base_codigo` | iamtarun/code_instructions_120k_alpaca | 120k instruções Python |
| `base_codigo` | sahil2801/CodeAlpaca-20k | 20k instruções código geral |
| `base_codigo` | iamtarun/python_code_instructions_18k_alpaca | 18k Python específico |
| `base_instrucoes_ptbr` | dominguesm/Canarim-Instruct-PTBR-Dataset | 316k instruções PT-BR nativo |
| `base_instrucoes_ptbr` | CohereLabs/aya_dataset (filtro por=por) | Instruções PT-BR curadas por humanos |
| `base_raciocinio` | openai/gsm8k | 8.5k problemas matemáticos chain-of-thought |
| `base_raciocinio` | meta-math/MetaMathQA | 395k QA matemático passo a passo |
| `base_conversas` | teknium/OpenHermes-2.5 | ~1M conversas alta qualidade (GPT-4) |
| `base_conhecimento_qa` | piEsposito/br-quad-2.0 | SQuAD 2.0 traduzido PT-BR |
| `base_conhecimento_qa` | eraldoluis/faquad | QA nativo PT-BR (ensino superior) |
| `base_medicina_ptbr` | AKCIT/MedPT | 384.095 pares pergunta-resposta médicas PT-BR |

Script de orquestração completo: `Scripts_Ingestao/pipeline_noturno.sh`.

---

## 7. Melhores LLMs locais (referência 2026)

- **qwen3:8b** — modelo atual de fallback local da Lyra. Cascata cloud vai na frente.
- **Qwen3.6 27B** — candidato a Modo Construção via RAM offload.
- **DeepSeek-R1 distilado 7B** — raciocínio chain-of-thought local.
- **Mistral Small 3 7B** — velocidade máxima de inferência.
- **Gemma 4 26B** — 14GB VRAM, multimodal texto+imagem+áudio.

Groq = `llama-3.3-70b-versatile` (free tier, ~0.8s primeiro chunk). Gemini = `gemini-2.5-flash` (free tier, ~9s às vezes).

## 8. Modelos de embedding (referência)

- **paraphrase-multilingual-MiniLM-L12-v2** (384 dims) — atual, bom custo-benefício.
- **BAAI/bge-m3** (1024 dims) — migração em andamento (`lyra_memory_v2`).
- jina-embeddings-v3 (1024 dims) — melhor qualidade multilingual.
- nomic-embed-text-v1.5 (768 dims) — excelente PT-BR local.

## 9. VLMs em 8GB (referência)

- **llava-phi3** (~2.9GB VRAM) — em uso via Ollama (fallback de `explicar_tela`). `moondream` foi testado e descartado (retorna content vazio no Ollama 0.30.10).
- **Gemini Vision** (`gemini-2.5-flash`) — primário para `explicar_tela` e `analisar_imagem`.
- **SmolVLM 2B** — alternativa local rápida (~1.5GB VRAM).
- **MiniCPM-V 2.6** — melhor qualidade mas ~5.5GB VRAM (compete com LLM principal).

## 10. Geração de imagem/vídeo/áudio (referência)

- **Imagem:** Pollinations.ai (gratuito, sem key, Flux) — em uso via `gerar_imagem()`. ComfyUI + SD 1.5 (~2GB VRAM) como alternativa local.
- **Vídeo:** LTX-2 OPTIMIZED (único viável em 8GB, FP8, 2-5s de vídeo em 60-90s). NÃO roda simultâneo com o LLM.
- **Áudio/Música:** MusicGen Small (~1GB VRAM), AudioLDM2 (~2GB).

## 10.5. Auditoria de performance/qualidade (30/06/2026)

Ordem sugerida de ataque (impacto/esforço, quick wins primeiro):

1. **[TRIVIAL]** `start_qdrant.bat:2` e `start_surreal.bat:2` usam `Test-NetConnection -ComputerName localhost` — violam a própria regra documentada (seção 1, "127.0.0.1 nunca localhost"). Ficaram de fora da correção de 26/06.
2. **[PEQUENO]** Boot lento de verdade: `Test-NetConnection` custa **~7s por chamada** medido ao vivo (vs ~270ms de um `TcpClient.Connect()` bruto — 26x mais lento). `start_cerebro.bat` roda 4 dessas sequenciais por iteração do loop de espera → cada iteração custa ~28s reais, não os 2s que o `timeout /t 2` sugere. Com até 60 tentativas, o timeout "de 2 minutos" pode levar até ~28min num boot com serviço lento. Trocar por teste de socket TCP puro (`[System.Net.Sockets.TcpClient]`) ou `curl.exe -s -o NUL`.
3. **[PEQUENO]** `/health` cria um `httpx.AsyncClient()` novo por ping (`cerebro_maestro.py:1331,1340`) — overhead de conexão infla a latência reportada (~250-280ms pros 3 serviços, quase idêntico entre eles — suspeito). `curl` direto: Qdrant 0.8ms, SurrealDB 18ms, Ollama 2.6ms. Painel "atividade/serviços" do frontend mostra números enganosos. Corrigir: cliente `httpx.AsyncClient` global reutilizável com keep-alive.
4. **[MÉDIO, maior impacto real]** `_embed()`/`_rerank()` (`cerebro_maestro.py:261,276`, `httpx.post` síncrono) e `_executar_tool_segura()` (linha 656, chama qualquer uma das ~66 tools de `lyra_tools.py` de forma síncrona) rodam DENTRO de handlers/generators `async def` sem `asyncio.to_thread`. Como uvicorn roda um único event loop, qualquer busca RAG ou tool call **trava o servidor inteiro** — nenhum outro request (outro chat, `/health`, polling do frontend, WS de voz) é atendido nesse intervalo. Medido: `/buscar` cold >10s, quente ~820ms — todo esse tempo o backend fica bloqueado pra qualquer outra coisa. Corrigir: envolver essas chamadas em `await asyncio.to_thread(...)` ou trocar pra `httpx.AsyncClient`.
5. **[MÉDIO]** Pesos de `score_final` em `buscar_hibrido()` (`0.68·relevancia + 0.32·recencia`, `_BASE_ESTABILIDADE_DIAS=30`) têm racional documentado (decaimento de Ebbinghaus) e já foram revisitados quando o reranker entrou, mas nunca foram calibrados contra métricas reais — `validador_cortical.py` existe mas não está amarrado a esses coeficientes. Não urgente.
6. **[GRANDE]** Confirmado: os 4 "andares" da cascata (`_stream_groq`, `_stream_gemini`, `_stream_claude_cli`, `_stream_local`) reimplementam o mesmo loop de tool-calling (~260-280 linhas quase idênticas, só muda a tradução de formato por provedor). Item já conhecido do backlog (`executar_chat_com_tools()` compartilhada, nunca extraída) — o item 4 acima teria sido corrigido em 1 lugar só se esse refactor já existisse.
7. Tratamento de exceção (`except Exception: pass`, 7 ocorrências em `cerebro_maestro.py`) — revisado, todos são degradação deliberada (best-effort: VRAM via nvidia-smi, cache, etc.), nenhum esconde bug real. Sem ação necessária.

### ✅ Itens 1-4 CORRIGIDOS (30/06/2026)

- **Itens 1 e 2 (localhost→127.0.0.1 + Test-NetConnection→TCP puro):** `start_qdrant.bat`, `start_surreal.bat`, `start_embed.bat`, `start_screenpipe.bat`, `start_cerebro.bat` — todos trocaram `Test-NetConnection` por `[System.Net.Sockets.TcpClient].ConnectAsync(...).Wait(300)`. Medido ao vivo: **12.8ms vs ~7s** por chamada (~550x mais rápido neste teste). `start_cerebro.bat` também ganhou uma função `T($p)` inline pra testar as 4 portas sem repetir o boilerplate.
- **Item 3 (`/health` client novo por ping):** criado `_http_health_client = httpx.AsyncClient()` global em `cerebro_maestro.py` (reusado com keep-alive), substituindo `async with httpx.AsyncClient()` por chamada em `_ping`/`_ping_post`. Medido ao vivo depois do fix: Qdrant 0.0ms, SurrealDB 31ms, Ollama 16ms (antes: ~250-280ms idênticos pros 3 — número inflado pelo overhead de conexão).
- **Item 4 (bloqueio síncrono do event loop):** `/chat` (linha ~993) agora chama `await asyncio.to_thread(buscar_hibrido, ...)` em vez de `buscar_hibrido(...)` direto. Os 3 andares da cascata (`_stream_groq`, `_stream_gemini`, `_stream_local`) trocaram `_executar_tool_segura(nome, args)` por `await asyncio.to_thread(_executar_tool_segura, nome, args)`. **Nota:** `/buscar` (endpoint `GET`, linha ~1631) é `def` normal, não `async def` — FastAPI já roda handlers síncronos em threadpool automaticamente, então não precisava do fix (só os `async def` bloqueavam de fato).
  - Validado ao vivo: reiniciado `cerebro_maestro.py`, testado `/health`, `/buscar`, `/chat` (Groq respondeu "Tóquio." pra "capital do Japão") — tudo funcionando. Confirmado que `/status` responde em 348ms mesmo com um `/buscar` lento rodando em paralelo (antes ficaria bloqueado atrás da busca).

### ✅ Item 5 (calibração de pesos do RAG) FEITO (30/06/2026 → 01/07/2026)

`buscar_hibrido()` ganhou parâmetros opcionais `peso_relevancia`/`peso_recencia` (default = valores atuais, sem mudar comportamento de nenhum chamador existente). Criado `calibrar_pesos_rag.py` — grid search de 6 combinações de pesos contra o MESMO conjunto de perguntas sintéticas (reaproveita `validador_cortical.py`, evitando regerar via LLM a cada combinação).

**2 bugs reais encontrados e corrigidos no processo** (o `validador_cortical.py` NUNCA tinha funcionado de verdade antes disso):

1. `qdrant_client`/`indice_bm25` só existem depois de `cerebro_maestro._init()`, que só roda sob `if __name__=="__main__"`. Importar o módulo de outro script (como o validador sempre fez) NÃO inicializa nada — toda chamada a `buscar_hibrido()` batia em `qdrant_client=None`, era capturada pelo `try/except` de `buscar()` e retornava `[]` silenciosamente. **Todo Hit Rate/MRR relatado por esse validador, desde que foi criado, era sempre 0% sem ninguém perceber** (não é erro visível, é `[]` mascarado). Corrigido: `_garantir_cerebro_inicializado()` chama `_init()` explicitamente (não sobe uvicorn, só popula os globals).
2. `gerar_pergunta()` chamava `qwen3:8b` sem `think=False`. O modelo gasta o `num_predict=60` inteiro em tokens de `<think>...</think>` e nunca chega a emitir o campo `response` (confirmado: `done_reason:"length"`, `response:""`). Toda "pergunta sintética" gerada era string vazia, e `buscar_hibrido("")` sempre devolvia o mesmo conjunto genérico de resultados, incapaz de bater com qualquer gold_id. Corrigido com `"think": False` (mesmo padrão de `cerebro_maestro._stream_local`) + validação de resposta não-vazia com fallback.

**Resultado da calibração (n=40, após os 2 bugs corrigidos):**
```
rel=1.00 rec=0.00  HR=  0.0%  MRR=0.000
rel=0.85 rec=0.15  HR=  2.5%  MRR=0.008
rel=0.75 rec=0.25  HR=  5.0%  MRR=0.013
rel=0.68 rec=0.32  HR=  5.0%  MRR=0.013  ← atual em produção
rel=0.60 rec=0.40  HR=  5.0%  MRR=0.015
rel=0.50 rec=0.50  HR=  7.5%  MRR=0.022
```
**Decisão: pesos atuais MANTIDOS.** A diferença entre o par em produção e o melhor do grid (+0.008-0.009 MRR) não é significativa numa amostra de 40 — não vale trocar por ruído. Interessante notar: relevância pura (`rel=1.00`) teve o PIOR resultado (0%) — recência ajuda de fato a desempatar memórias episódicas recentes contra o resto do corpus.

**Baseline oficial (n=100, 01/07/2026):** Hit Rate **10.0%**, MRR **0.057** — consistente com o teste de n=40 (proporcionalmente até um pouco mais alto), confirma que o número baixo não é ruído de amostra pequena, é uma característica repetível da métrica atual (ver explicação da causa provável abaixo). Esse é o número de referência oficial pra comparar em validações futuras do RAG.

### ✅ `lyra_shadow_thoughts.py` — bug de escopo corrigido, executado (01/07/2026)

`fase_nrem()` tinha um bug real: fazia `scroll(limit=500)` sem filtro e sem paginação — sempre os mesmos ~500 primeiros pontos da coleção inteira (~3M vetores), nunca cobrindo o resto, comparando categorias sem sentido entre si (wiki com episódio de chat). Corrigido: agora filtra só `categoria=episodio` (onde duplicação real de fato acontece — hoje só 40 vetores, já que a coleção é nova desde a migração BGE-M3 de 26/06) e pagina via cursor do Qdrant até esgotar tudo dessa categoria. Rodar O(N²) pareado contra os 3M vetores estáticos (wiki/datasets) seria inviável e desnecessário — esse conteúdo já vem limpo da fonte. Também adicionado `sys.stdout.reconfigure(utf-8)` (faltava, mesmo bug de encoding já documentado em outros scripts).

**Execução real feita com aprovação do Antônio** — ver seção 10.11 abaixo ("Shadow Thoughts — primeira execução real") para o resultado (28 duplicatas NREM encontradas) e a seção 8 de `LYRA_NUCLEO.md` (agendamento automático a cada 3h no `loop_proativo` desde então).

**Achado importante para reavaliar o próprio validador (não é sobre os pesos):** os números absolutos (5% HR) ficam bem abaixo do limite documentado (85%) — mas isso provavelmente reflete uma limitação da METODOLOGIA, não da qualidade real do RAG. `validador_cortical.py` amostra da tabela `evento` (memórias episódicas curtas, ex: "A capital da França é Paris.") e exige que o `buscar_hibrido()` recupere EXATAMENTE aquele registro específico entre ~3,08M vetores — competindo diretamente com o artigo completo da Wikipedia sobre o mesmo assunto, que tende a rankear melhor por ser mais denso em informação. Ou seja: a Lyra provavelmente RESPONDE corretamente à pergunta (via o artigo da wiki, não o episódio), mas isso conta como "miss" no validador porque ele exige o episódio específico de volta. **Recomendação para o futuro:** separar a validação por categoria (testar recall só dentro de `episodio` vs. só dentro de `conhecimento_geral`) em vez de medir contra o corpus inteiro misturado — item de melhoria da ferramenta em si, não urgente.

### ✅ Item 6 (refactor da cascata) FEITO (01/07/2026)

Extraído o loop de tool-calling compartilhado que Groq/Gemini/local reimplementavam quase idêntico 3 vezes. Nova estrutura em `cerebro_maestro.py`:

- `ToolCall` (id, nome, args) — representação normalizada de uma chamada de ferramenta, independente do formato nativo do provedor.
- `_RodadaCtx` — carrega `tool_calls` (lista normalizada) e `extra` (payload bruto específico do provedor, necessário só na hora de formatar a mensagem de volta — ex: os deltas acumulados do Groq, os `parts` do Gemini, o `tool_calls` cru do Ollama).
- `_executar_chat_com_tools(estado, ferramentas, nome_provedor, transmitir, aplicar_tool_calls)` — o loop compartilhado: chama `transmitir()` (uma rodada de streaming específica do provedor), executa cada `ctx.tool_calls` via `_executar_tool_segura` em `asyncio.to_thread` (log + marcador `_[Executando: x]_`), chama `aplicar_tool_calls()` (formata o resultado de volta no "estado" nativo do provedor) e repete. **`_MAX_ITERACOES_TOOLS = 25`** — trava de segurança nova que não existia antes (o código original tinha `while True` puro, sem limite, por andar).
- Cada provedor agora só define 2 funções pequenas: `_groq_transmitir`/`_groq_aplicar_tool_calls`, `_gemini_transmitir`/`_gemini_aplicar_tool_calls`, `_local_transmitir`/`_local_aplicar_tool_calls`. `_stream_groq`/`_stream_gemini`/`_stream_local` viraram wrappers finos que montam o estado inicial e delegam pro loop compartilhado.
- `_stream_claude_cli` **não foi tocado** — não usa tool-calling nativo (delega pro Claude Code CLI), é genuinamente diferente dos outros 3, não fazia parte da duplicação.

**Validado ao vivo, um andar de cada vez (via `modelo: groq|gemini|local` no `/chat`, que força um andar sem fallback):**

- Sem tool call: os 3 andares respondem normalmente (`"quanto é 12×7?"` → "84" nos 3).
- Com tool call real (`consultar_clima`): os 3 executam a ferramenta e refletem o resultado na resposta final, idêntico ao comportamento anterior ao refactor.
- Um teste do Gemini bateu num 503 genuíno da API (alta demanda, transiente) — não é bug do refactor, confirmado porque o log mostra o tool call executando com sucesso ANTES da falha, e a repetição do mesmo teste passou limpo.
- Modo `auto` (cascata normal) seguiu funcionando sem regressão.

Backup (`cerebro_maestro.py.bak_pre_refactor_cascata_01-07-2026`) feito antes de editar, removido depois de toda a validação passar.

## 10.6. Avaliação SurrealDB 3.0 vs Qdrant (01/07/2026) — pesquisa, sem migração

SurrealDB 3.0 tem índice HNSW nativo (`DEFINE INDEX ... HNSW DIMENSION 1024 DIST COSINE`), com melhoria de performance real documentada pela SurrealDB (~8x mais rápido que antes, consultas indexadas caindo de ~35s pra ~4.5s no benchmark deles). Suporta EUCLIDEAN/COSINE/MANHATTAN, tipos F64/F32/I64/I32/I16, parâmetros `EFC`/`M` ajustáveis. Também tem DISKANN (disk-oriented) pra datasets maiores que a RAM disponível — Qdrant não tem equivalente direto a isso.

**Recomendação: NÃO migrar agora.** Motivos:

1. **Memória:** HNSW do SurrealDB mantém o grafo indexado quente em RAM. Só os vetores brutos (3.08M × 1024 dims × 4 bytes F32) já são ~12.6GB, mais overhead do grafo HNSW (M=12 conexões por nó) — provavelmente 15-20GB+ só de índice, concorrendo com RAM que já é usada por Ollama/outros serviços (64GB total, mas não é o único consumidor).
2. **Esforço de migração alto, benefício incerto:** exigiria reescrever `buscar_hibrido()` inteiro (hoje: Qdrant dense + BM25 externo + reranker, fundidos por RRF), re-inserir todos os 3.08M vetores num campo SurrealDB, e validar que a qualidade de retrieval não regride — dias de trabalho, não uma tarde.
3. **Qdrant já está estável e rápido em produção** (`/buscar` ~382-820ms, ver seção 1) — não há dor real motivando a troca, só a promessa de "um serviço a menos pra rodar".
4. **Risco documentado:** já existe um incidente registrado de perda de ~666k vetores ao atualizar o binário do Qdrant (seção 1) — qualquer migração de armazenamento vetorial merece o mesmo nível de cautela (backup completo, ambiente de teste isolado) antes de tocar em produção.

**Se algum dia fizer sentido revisitar:** um teste isolado (coleção pequena, ex: só a categoria `episodio` com ~40 vetores) seria um bom primeiro passo de baixo risco, sem mexer no `lyra_memory_v2` de produção.

Fontes: [SurrealDB 3.0 benchmarks](https://surrealdb.com/blog/surrealdb-3-0-benchmarks-a-new-foundation-for-performance), [Vector indexes docs](https://surrealdb.com/docs/learn/data-models/vector-search/vector-indexes).

## 10.7. Avaliação Mem0/Kore para decay de memória (01/07/2026)

**Kore** (projeto open-source, não confundir com Kore.ai, a plataforma enterprise) é quase um espelho conceitual do que a Lyra já faz: "local AI memory layer with Ebbinghaus forgetting curve" — memórias decaem se não forem recuperadas, com **meia-vida variável por IMPORTÂNCIA** (7 dias pra notas casuais, 1 ano pra informação crítica). Isso confirma que a decisão de arquitetura da Lyra (`buscar_hibrido()`, decaimento Ebbinghaus com estabilidade crescendo por `retrieval_count`) já está alinhada com o estado da arte de projetos pequenos/locais na área.

**Diferença real que vale a pena considerar:** hoje `_BASE_ESTABILIDADE_DIAS = 30` é uma constante FIXA pra toda memória, independente do conteúdo — só o histórico de recuperação (`retrieval_count`) faz a estabilidade crescer depois. O Kore varia a meia-vida BASE por categoria de importância desde o início. Poderia fazer sentido dar `_BASE_ESTABILIDADE_DIAS` diferente por categoria (ex: decisões técnicas/fatos importantes decaem mais devagar que bate-papo casual) — não implementado agora, fica registrado como refinamento futuro de baixo risco.

**Mem0** (biblioteca mais madura/comercial) usa uma abordagem diferente e complementar: hybrid vector+graph+KV store com **resolução de conflito via LLM** (ex: "usuário mudou de nome" sobrescreve o fato antigo automaticamente) — foco em evitar fatos contraditórios/desatualizados, não só em "esquecer com o tempo". Isso se conecta mais com a fase REM do Shadow Thoughts (cross-referenciar informação desconexa) do que com o decaimento em si. Benchmarks 2026: 92.5% LoCoMo / 94.4% LongMemEval, <7k tokens por chamada de retrieval.

**Recomendação:** manter a implementação atual (já é conceitualmente equivalente ao Kore). Considerar variar `_BASE_ESTABILIDADE_DIAS` por categoria como melhoria futura pequena. Não adotar Mem0 como dependência — a resolução de conflitos por LLM que ele oferece é um problema diferente, mais próximo do que o Shadow Thoughts (REM) já se propõe a resolver via grafo.

Fontes: [Kore no Hacker News](https://news.ycombinator.com/item?id=47070979), [Mem0 blog — Token-Efficient Memory Algorithm](https://mem0.ai/blog/the-token-efficient-memory-algorithm-now-has-temporal-reasoning), [AI Memory Benchmarks 2026](https://mem0.ai/blog/ai-memory-benchmarks-in-2026).

## 10.8. Avaliação do protocolo A2A (01/07/2026)

Agent2Agent (A2A) — protocolo aberto do Google (v1.0 em 2026, agora sob Linux Foundation, com Microsoft/Salesforce/ServiceNow apoiando). Componentes principais: **Agent Cards** (JSON descrevendo capacidades de um agente, pra outros agentes descobrirem "quem sabe fazer o quê"), **ciclo de vida de tarefa** rico (`submitted → working → input-required → completed/canceled/failed`), tudo sobre HTTP(S)/SSE/JSON-RPC, com auth/autorização de nível enterprise.

**Recomendação: NÃO adotar o protocolo inteiro.** A2A resolve um problema que a Lyra não tem — interoperabilidade entre agentes de **fornecedores diferentes** (empresa A conversando com agente da empresa B). O enxame da Lyra (`lyra_agentes.py`) é inteiramente interno (sub-tarefas da própria Lyra, não agentes de terceiros) — adotar Agent Cards/JSON-RPC/auth enterprise seria complexidade desproporcional ao problema real.

**2 ideias do A2A valem a pena "roubar" conceitualmente, sem adotar o protocolo:**

1. **Ciclo de vida de tarefa mais rico** — hoje `subtarefa.status` no SurrealDB só tem `pendente|rodando|concluida|erro`. O estado `input-required` do A2A é interessante: um sub-agente que precisa perguntar algo ao Antônio no meio da execução, em vez de falhar ou adivinhar. Não implementado, ideia registrada.
2. **"Agent Cards" (capacidade declarada)** — conecta direto com a tarefa 5 desta lista ("Enxame de especialistas / MoE roteado"): cada modelo/persona futura poderia declarar suas capacidades num formato parecido, e o roteador escolhe por isso em vez de um `if/else` de keyword.

Fontes: [IBM — What Is Agent2Agent (A2A) Protocol?](https://www.ibm.com/think/topics/agent2agent-protocol), [A2A protocol architecture](https://tyk.io/learning-center/a2a-protocol-architecture-and-technical-specification/).

## 10.9. Enxame de especialistas (MoE roteado) — ✅ IMPLEMENTADO (02/07/2026)

**Formalizado o design abaixo.** Em `cerebro_maestro.py`, o `if eh_pergunta_codigo: andares=[...] else: andares=[...]` solto virou uma lista declarativa `ESPECIALISTAS` (perto de `_TOOL_KEYWORDS_RE`, antes do `/chat`):

```python
ESPECIALISTAS = [
    {"categoria": "codigo", "trigger": _trigger_codigo, "andares": ["claude", "groq", "gemini", "local"]},
    {"categoria": "geral",  "trigger": None,             "andares": ["groq", "gemini", "claude", "local"]},
]
```

`_rotear_especialista(msg_lower, msg_texto)` percorre a lista NA ORDEM e devolve o primeiro cujo `trigger` bate; `trigger=None` é o catch-all (tem que ficar por último). O `/chat` chama isso uma vez (`especialista = _rotear_especialista(...)`) e monta `andares` a partir de `especialista["andares"]` — mesma lógica de antes, só data-driven. `_KEYWORDS_CODIGO` e a função `_trigger_codigo` são as mesmas keywords que já existiam, só reorganizadas.

**Comportamento idêntico ao anterior, validado ao vivo:** pergunta com "bug no meu código" → `tier: Claude` (categoria `codigo`); pergunta geral ("capital da Itália") → `tier: Groq` (categoria `geral`). Nada mudou pro usuário — o ganho é só estrutural: adicionar um especialista novo (matemática, visão, etc.) agora é uma entrada na lista, não editar roteamento espalhado pelo `/chat`.

**Escopo desta implementação:** só a ordem da cascata cloud (`/chat`). Não mexeu em `consultar_especialista()` (`lyra_tools.py`) nem generalizou o roteador de ferramentas (`_TOOL_KEYWORDS_RE`) — são mecanismos distintos, fora do escopo da proposta original.

### Design original (referência)

**Descoberta importante:** a Lyra já tem uma versão embrionária disso, só não estava documentada como tal:

- `cerebro_maestro.py` já prioriza Claude pra perguntas de código (`eh_pergunta_codigo`, keywords tipo "função"/"bug"/"refatora") antes de cair pro resto da cascata.
- `lyra_tools.py:911-928` — `consultar_especialista()` já delega problemas de código pro `qwen2.5-coder:7b` local (rodando via Ollama, modelo especializado em código que JÁ está instalado mas só usado nesse fallback específico) quando o Claude Code CLI não está disponível.

**Proposta de generalização** (inspirada nas "Agent Cards" do A2A — ver seção 10.8): formalizar isso como uma lista de "especialistas declarados", cada um com categoria/keywords de trigger + modelo:

```python
ESPECIALISTAS = [
    {"categoria": "codigo",     "modelo": "qwen2.5-coder:7b", "trigger": _KEYWORDS_CODIGO},
    {"categoria": "raciocinio", "modelo": "qwen3:8b",         "trigger": [...], "think": True},
    {"categoria": "visao",      "modelo": "llava-phi3",       "trigger": None},  # já roteado por tipo de anexo, não por keyword
    {"categoria": "geral",      "modelo": "cascata_cloud",    "trigger": None},  # default
]
```

O roteador (hoje `_TOOL_KEYWORDS_RE` + `eh_pergunta_codigo`, ambos regex/keyword) escolheria o especialista por essa lista em vez de `if/else` espalhado. Ganho: adicionar um especialista novo vira "adicionar uma entrada na lista", não editar lógica de roteamento em múltiplos lugares.

**Atualização 02/07/2026 — implementado apesar das ressalvas acima** (pedido explícito do usuário). Só os 2 especialistas reais (`codigo`, `geral`) — os placeholders `raciocinio`/`visao` do design original NÃO entraram, ficam como ideia registrada pra quando houver candidato real (ver ✅ IMPLEMENTADO acima para o que foi feito de fato).

Registrado como proposta de arquitetura pra quando houver mais candidatos a especialista (ex: um modelo de matemática dedicado, ou perfis de personalidade diferentes por sub-tarefa do enxame — item já cogitado em `LYRA_AGENTES_E_PLANOS.md` Fase 4).

## 10.10. Telemetria histórica (01/07/2026)

`telemetria.json` (existente) só guarda o acumulado desde o último restart do cérebro — sem noção de tendência ao longo do tempo. Adicionado:

- `_snapshot_telemetria_historico()` em `cerebro_maestro.py` — tira um snapshot (`ts`, `total_chats`, `tiers` com usos/falhas/latência média) a cada ~5min (a cada 5ª iteração do `loop_proativo`, que já roda a cada 60s), grava em `telemetria_historico.jsonl` (append-only, truncado nas últimas 2000 linhas pra não crescer sem limite — ~1 semana de histórico).
- `GET /stats/historico?limite=200` — devolve os snapshots mais recentes.
- Frontend: novo sparkline `#t-hist-spark` na seção "telemetria" do painel lateral, mesmo padrão visual do sparkline de latência já existente (`_drawHistoricoSparkline`, reaproveitando a lógica de `_drawSparkline`). Poll a cada 60s (dado muda devagar).

**Validado:** sintaxe Python/JS ok, `cerebro_maestro.py` reiniciado sem erro, `/stats/historico` testado (retorna `{"snapshots": [...]}` corretamente, inclusive um snapshot manual de teste que foi gravado, conferido e depois removido do arquivo antes de deixar rodando limpo). **Não confirmado visualmente** — o app foi aberto e renderizou sem crash/erro de console, mas não consegui abrir o painel lateral pra ver o gráfico novo de fato desenhado (tentativa de simular clique no menu não funcionou, provavelmente por foco de janela). Pedir pro Antônio conferir visualmente quando puder.

## 10.11. Sessão 01/07/2026 — itens implementados

### ✅ Shadow Thoughts — primeira execução real (01/07/2026)

Rodou `lyra_shadow_thoughts.py` (ciclo completo nrem+rem+deep) pela primeira vez com aprovação do Antônio. Resultado: **NREM** encontrou 28 duplicatas entre os 46 episódios existentes (mensagens de teste repetidas nas sessões de desenvolvimento) e as marcou com `duplicado=True` no Qdrant. **REM** 0 arestas cross-domain (eventos jovens, poucos tópicos cruzados — normal). **DEEP** 0 resumos (todos os eventos têm menos de 4 semanas). Ciclo completo em 2.5s.

### ✅ Endpoint `POST /agente` + `GET /agente/runs` (01/07/2026)

`lyra_agent.py` integrado ao `cerebro_maestro.py` com dois endpoints novos:

- `POST /agente` — dispara loop ReAct autônomo (`executar_agente_async`), aguarda conclusão, retorna resultado. Body: `{objetivo, max_iteracoes}`.
- `GET /agente/runs?limite=N` — lista execuções recentes da tabela `agente_run` no SurrealDB.
`import lyra_agent as _agent_module` + `AgenteRequest(BaseModel)` adicionados logo após o bloco de enxame (~linha 1640). Ambos os endpoints ficam expostos no MCP automaticamente (via `fastapi_mcp`).

### ✅ Reconciliação SurrealDB ↔ Qdrant (01/07/2026)

Gap real confirmado: 60 eventos pós-migração no SurrealDB vs 46 no Qdrant — **15 episódios órfãos** (todos de 26/06, horário de restart durante testes da migração BGE-M3). Script `reconciliar_episodios.py` criado em `Lyra_Ollama/`. Rodado com `--fix`: 15/15 re-embedados e inseridos no Qdrant sem erro. Sistema agora está com 61 episódios em ambos os bancos, zero gap. O script fica disponível para rodar manualmente sempre que necessário (nenhum daemon foi criado — o volume é baixo e o Shadow Thoughts + ciclos de manutenção já cobrem a detecção periódica).

### ❌ Decay Ebbinghaus — REMOVIDO (01/07/2026)

O componente de recência (`0.68·relevancia + 0.32·recencia`, Ebbinghaus `e^(-t/S)`) foi **completamente removido** do `buscar_hibrido()` por decisão do Antônio. Motivação: penalizar memórias antigas por tempo prejudica o recall de episódios não recentes que ainda são relevantes — a Lyra "esquecia" coisas que importavam só porque aconteceram há mais de 30 dias. Agora `score_final = relevancia` puro (score do reranker cross-encoder bge-reranker-v2-m3). Os campos `retrieval_count` e `last_accessed_at` continuam sendo gravados no Qdrant (úteis para auditoria e para futuras políticas de cache/eviction), mas não afetam mais o ranking. **Não reimplementar decaimento temporal sem discussão prévia.**

### ✅ Shadow Thoughts — agendamento automático (Fase 3, 01/07/2026)

`loop_proativo()` em `cerebro_maestro.py` agora dispara `lyra_shadow_thoughts.ciclo_completo(["nrem","rem","deep"])` automaticamente a cada 180 iterações (~3h), via `asyncio.create_task` (não bloqueia o loop). Isso elimina a necessidade de rodar o script manualmente ou de um processo daemon separado.

### ✅ Endpoint `POST /shadow_thoughts` (01/07/2026)

Permite disparo manual do ciclo de Shadow Thoughts sem acesso ao terminal. Body opcional: `{fases: "nrem,rem,deep"}`. Retorna imediatamente — execução é em background. Exposto no MCP automaticamente. Útil para forçar um ciclo fora do agendamento de 3h.

## 10.12. Cinco Inovações Cognitivas (01/07/2026)

Implementadas em `cerebro_maestro.py` na mesma sessão. Todas sem dependências novas.

### ✅ Innovation 1 — Goal Drift Detector

`_classificar_intencao(ator, texto) → str` — heurística por keywords, zero latência, zero LLM.
Classifica cada mensagem do usuário como: `objetivo` | `conclusao` | `passo` | `resposta` (Lyra).

**Onde entra:**

- `registrar_evento()` agora grava campo `intencao` em SurrealDB e Qdrant (payload do episódio).
- `_carregar_estado_inicial()` (Step 3 novo): no startup, busca eventos recentes com `intencao='objetivo'` e injeta no `_session_briefing` como `[OBJETIVOS RECENTES]` — a Lyra sabe quais pedidos ficaram em aberto.
- `/chat`: `registrar_evento` do usuário agora recebe `intencao=_classificar_intencao(...)` explicitamente.

**Degradação elegante:** campos `intencao` simplesmente ausentes em eventos antigos — queries por `WHERE intencao = 'objetivo'` retornam só os novos, sem erro.

### ✅ Innovation 2 — Knowledge Freshness Tags

`_FRESHNESS_MEIA_VIDA: dict[str, float]` — meia-vida em dias por categoria:

- `programacao`/`documentacao`: 180 dias (APIs e código mudam rápido)
- `conhecimento_geral`: 3650 (Wikipedia, fatos históricos — estável)
- `raciocinio_matematico`: 9999 (imutável)
- `episodio`: 9999 (não penalizar memória episódica — decisão mantida de 01/07)

`_freshness_factor(categoria, timestamp_str) → float` — decaimento `0.5^(dias/meia_vida)`, retorna 1.0 para categorias estáveis ou timestamps inválidos.

`_FRESHNESS_PESO = 0.06` — freshness influencia no máximo 6% do `score_final`.

**Diferença do Ebbinghaus removido:** aquele penalizava TODAS categorias igualmente. Este é seletivo — fatos históricos e matemática têm meia-vida infinita (sem penalidade). Artigo de 2020 sobre Python 3.8 recebe leve penalidade; equação de Euler não.

**Score final novo:** `relevancia * 0.94 + freshness_factor * 0.06`

### ✅ Innovation 3 — Session Replay

`_carregar_estado_inicial()` ganhou Step 4: ao startup, faz duas queries SurrealDB das últimas 24h:

1. **Top tópicos** via traversal de grafo `SELECT out FROM sobre WHERE in.timestamp >= $ontem GROUP BY out ORDER BY freq DESC LIMIT 6` — usa o grafo já existente, zero custo.
2. **Ferramentas usadas** via regex `_[Executando: X]_` em eventos da Lyra.

Resultado injetado no `_session_briefing` como `[TÓPICOS ATIVOS (24h)]` e `[FERRAMENTAS RECENTES]` — a Lyra abre a sessão sabendo não só o que foi dito (Step 1), não só um resumo em prosa (Step 2), mas quais tópicos dominaram e quais capacidades já foram exercidas.

**Degrada silenciosamente** se as queries do SurrealDB falharem — Steps 1 e 2 continuam.

### ✅ Innovation 4 — Cognitive Load Throttling

`_carga_cognitiva: str` — global com valores `baixa | media | alta`. Atualizado pelo `loop_proativo` a cada ~5min via `_atualizar_carga_cognitiva()`.

**Critério de carga:**

- `alta`: latência do último chat > 8s, OU modelo local (`qwen3:8b`) atendendo > 30% dos chats (sinal de que as APIs cloud estão falhando)
- `baixa`: latência < 2s
- `media`: demais casos

`_top_k_ajustado(top_k: int) → int` — ajusta o número de documentos do RAG:

- `alta`: `top_k - 2` (mínimo 2) — resposta mais rápida, menos contexto
- `baixa`: `top_k + 2` (máximo 10) — resposta mais rica
- `media`: sem alteração

`/status` agora expõe `carga_cognitiva` para o painel lateral (já conectado ao poll de 4s do frontend).

### ✅ Innovation 5 — Response Provenance

`ids_rag: list[str]` — capturado no `/chat` após `buscar_hibrido`: lista de IDs Qdrant dos documentos que alimentaram o contexto daquela resposta.

**Onde entra:**

- `historico_recente`: cada entrada de Lyra agora tem `"fontes_rag": [...ids...]` — `/historico` devolve isso automaticamente.
- `registrar_evento(... fontes_rag=ids_rag)`: salvo no SurrealDB e no payload do Qdrant.
- Usuário pode chamar `GET /historico` e ver de onde cada resposta veio.

**Limitation known:** IDs são UUIDs do Qdrant. Para ver o texto do documento-fonte, precisa de `GET /buscar?q=...` ou query direta ao Qdrant. Frontend com botão "ver fontes" ficou fora do escopo desta implementação — os dados estão disponíveis, a UI não.

## 10.13. Speculative Decoding — sidecar de detecção de alucinação (02/07/2026)

Item da Fase 3 do roadmap. **Importante: não é o Speculative Decoding clássico** (acelerar geração checando tokens de um draft contra o modelo principal token a token) — isso é inviável aqui porque a cascata usa APIs de nuvem (Groq/Gemini/Claude) sem acesso a logits nem vocabulário compartilhado com um modelo local. O que foi implementado é um **sidecar de detecção de divergência semântica**, usando a mesma ideia (draft leve + principal) pra outro fim: sinalizar possível alucinação, não acelerar.

**Modelo draft:** `qwen3:0.6b` (~520MB, baixado via Ollama). Escolhido por ser pequeno o bastante pra não competir por VRAM com o `qwen3:8b` (andar Local) quando os dois rodam juntos no mesmo card de 8GB.

**Mecânica em `cerebro_maestro.py`:**

1. `/chat` dispara `_rodar_draft(mensagens)` como `asyncio.create_task` **em paralelo** com a cascata principal (Groq→Gemini→Claude→Local) — não soma latência à resposta do usuário.
2. Só dispara quando `not precisa_tools` — se a pergunta aciona ferramentas, o andar principal vê dados que o draft nunca vê (clima, hora, resultado de busca), então divergência ali seria falso-positivo garantido.
3. Depois que a resposta principal termina, compara via `_embed()` (embed_service BGE-M3) + `_cosine_sim()`: `divergencia_draft = 1 - cosine_sim(vetor_final, vetor_draft)`.
4. `LIMIAR_DIVERGENCIA_ALUCINACAO = 0.45` — acima disso, loga `[SPEC-DECODE] divergência alta (...) — possível alucinação` com o texto do draft. Não bloqueia nem altera a resposta, só sinaliza.
5. Persistido como `divergencia_draft` em `historico_recente`, `registrar_evento()` (SurrealDB + payload Qdrant) — mesmo padrão de `fontes_rag` (Innovation 5). Visível via `GET /historico`, sem UI nova no frontend (decisão deliberada, fora do escopo desta implementação).

**Bug corrigido durante a validação:** a primeira versão usava o `SYSTEM_PROMPT_LYRA` completo pro draft. A Diretiva 2 desse prompt ("se REALMENTE não souber, diga 'Dados insuficientes no meu córtex'") fazia o modelo de 0.6B recusar quase toda pergunta de conhecimento — ele nunca tem "certeza" o bastante — gerando divergência alta sistemática por recusa, não por conteúdo divergente de verdade. Corrigido com um system prompt próprio (`_SYSTEM_PROMPT_DRAFT`) que instrui o draft a **sempre arriscar um palpite**, mesmo fraco.

**Limitação conhecida (arquitetural, não bug):** `_cosine_sim` sobre embeddings BGE-M3 mede similaridade de **tópico/estrutura**, não correção factual. Teste manual: pergunta "capital da França" com draft respondendo errado ("Lyon") vs resposta correta simulada ("Paris") deu divergência de só 0.13 — baixo demais pra disparar alerta, porque as duas frases têm a mesma estrutura semântica ("capital da França é X"). O sinal funciona bem pra divergência de **domínio/tópico** (ex: pergunta sobre França respondida com fatos sobre Austrália — divergência 0.44, próximo do limiar) mas não substitui verificação factual. Tratar como heurística de "a resposta está no mesmo assunto que um modelo independente esperaria", não como detector de alucinação factual fiável.

**Validado ao vivo (02/07/2026):** restart do `cerebro_maestro.py`, pergunta real via `/chat` ("capital do Japão") — draft rodou em paralelo, ambos responderam "Tóquio", divergência calculada = ~0.0, persistida corretamente em `/historico`. Sem impacto de latência perceptível (draft ~4-5s a quente, rodando em paralelo com a cascata principal que já leva tempo similar).

**Bug de regressão encontrado e corrigido na mesma sessão (02/07/2026):** ao testar um segundo turno de chat, o Groq passou a falhar com `400 - property 'divergencia_draft' is unsupported`. Causa raiz: `mensagens = list(historico_recente)` em `/chat` (linha ~1417) só copiava a *lista*, não os *dicts* — os itens de `historico_recente` carregam metadados extras (`fontes_rag` da Innovation 5, e agora `divergencia_draft`) que iam de volta pra API do Groq como parte do array de mensagens. A API do Groq valida o schema de mensagem estritamente e rejeita propriedades além de `role`/`content`. **Esse bug já existia desde a Innovation 5** (`fontes_rag`) — ficou mascarado porque a cascata cai pro Gemini silenciosamente em caso de falha do Groq, sem gerar erro visível pro usuário, só degradando (Groq deixava de ser usado em qualquer turno subsequente ao primeiro). `divergencia_draft` só tornou o bug reproduzível de forma óbvia o bastante pra ser notado e corrigido.

**Correção:** `mensagens = [{"role": m["role"], "content": m["content"]} for m in historico_recente]` — sanitiza pra só os dois campos que a API espera. Validado com 2 mensagens consecutivas via `/chat`: Groq respondeu nas duas (antes, a segunda caía pro Gemini).

## 10.14. `navegar_web` (browser-use) — estava completamente quebrado, corrigido (02/07/2026)

Item #2 do `instrucoes.md` (raiz do projeto) estava marcado como pendente há tempos: "instalar Chromium do Playwright". Ao testar de verdade (não só ler o código), achei que o problema era maior que isso — a ferramenta nunca tinha funcionado:

1. **Chromium nunca instalado.** `python -m playwright install chromium` nunca tinha sido rodado — `navegar_web()` falhava na primeira linha com `Executable doesn't exist`. Corrigido: instalado (Chromium completo + chrome-headless-shell + ffmpeg + winldd, ~115MB).

2. **API do `browser-use` mudou — `lyra_browser.py` quebrado independente do Chromium.** O código passava um `langchain_google_genai.ChatGoogleGenerativeAI` direto pro `Agent` do `browser-use`. A versão instalada (`browser-use==0.13.1`) migrou pra uma abstração de LLM própria (`browser_use.llm.*`, com wrappers por provider: `browser_use.llm.google.chat.ChatGoogle`, `.anthropic`, `.openai` etc.) — o objeto langchain não tem o atributo `.provider` que o `browser-use` novo espera, falhando com `'ChatGoogleGenerativeAI' object has no attribute 'provider'`. Corrigido: troca pra `browser_use.llm.google.chat.ChatGoogle(model=..., api_key=..., temperature=...)`.

3. **`gemini-2.0-flash` tem free tier = 0 nesta conta.** Depois da correção #2, o agente rodava mas toda chamada ao Gemini voltava `429 RESOURCE_EXHAUSTED... limit: 0` — não é rate-limit temporário, é quota zero permanente pro modelo 2.0 nessa conta (modelo mais antigo, sem free tier disponível mais). Trocado pra `gemini-2.5-flash` (mesma família usada em outros lugares do projeto, `GEMINI_MODEL` em `cerebro_maestro.py` está em `gemini-3.5-flash` — mais novo ainda, mas `2.5-flash` é o que está na lista de modelos suportados oficialmente pelo `ChatGoogle` do `browser-use` instalado).

**Validado ao vivo:** `navegar_web(objetivo="Acesse example.com e diga qual é o título da página", url_inicial="https://example.com")` rodou o ciclo completo (abriu Chromium headless, navegou, extraiu resposta, fechou sessão) e retornou `{"ok": True, "resultado": "..."}`. A resposta teve um pequeno erro de conteúdo (chamou "example.com" em vez de "Example Domain" — o `judge` interno do próprio `browser-use` sinalizou isso como falha de qualidade), mas isso é limitação do LLM/modelo, não da integração — mecanicamente a ferramenta está funcional pela primeira vez.

**Nota:** `browser-use` tem uma versão mais nova disponível (0.13.3, atual 0.13.1) — não atualizado agora, fora do escopo desta correção.

## 10.15. Auditoria geral de bugs (02/07/2026) — `/goal`: corrigir todos os erros, testar tudo, documentação perfeita

Varredura sistemática pedida pelo usuário: 3 sub-agentes em paralelo auditaram `lyra_tools.py` (2823 linhas/66 ferramentas), `cerebro_maestro.py` e os módulos menores (`lyra_agentes.py`, `lyra_agent.py`, `lyra_shadow_thoughts.py`, `embed_service.py`, `lyra_seguranca.py`, `lyra_telegram.py`, `lyra_google_workspace.py`, `lyra_voice_live.py`, `bm25_index.py`, `build_bm25_index.py`, `validador_cortical.py`, `calibrar_pesos_rag.py`). Todo achado foi **verificado manualmente antes de corrigir** (rodando o código de verdade, não confiando no relatório do agente às cegas) — dois "achados" dos agentes eram falsos positivos, descartados (ver final desta seção). `python -m py_compile` rodado em TODOS os `.py` do projeto (zero erro de sintaxe) e `node --check` no `script.js` do frontend (zero erro).

### ✅ Bugs reais corrigidos

**1. `analisar_clipboard_com_ia` usava modelo Gemini inexistente (`lyra_tools.py:1981`).** `gemini-2.5-flash-preview-05-20` retorna `404 NOT_FOUND` nesta conta (confirmado testando direto contra a API) — provavelmente um modelo preview aposentado. As outras 5 funções que usam Gemini (`explicar_tela`, `analisar_imagem`, `pesquisar_com_ia`, `resumir_documento`, `transcrever_audio`) já usavam `gemini-3.5-flash` corretamente (confirmado funcionando). Trocado pra `gemini-3.5-flash`. **Testado ao vivo:** clipboard com texto real → `{"ok": true, "via": "gemini", "resultado": "..."}`.

**2. `explicar_tela` escondia silenciosamente falha do Gemini Vision (`lyra_tools.py:669-670`).** `except Exception as e: pass` — se o Gemini quebrasse (nome de modelo errado, cota, rede), a degradação pro `llava-phi3` local acontecia sem nenhum sinal em lugar nenhum; o bug nº1 acima poderia ter ficado invisível pra sempre se essa função tivesse esse mesmo erro. Adicionado `print()` reportando a falha antes do fallback (mesma filosofia de "log mas continua" já usada em `cerebro_maestro.py`).

**3. `executar_comando` corrompia texto acentuado silenciosamente (`lyra_tools.py`).** PowerShell 5.1 formata a saída na codepage OEM do console (medido: 850 nesta máquina), não em UTF-8 — decodificar como `utf-8, errors="replace"` transformava todo acento em `�` sem erro nem aviso. **Confirmado com teste real:** `Write-Output 'ção àé íóú çãõ'` chegava como `'�o �� ���...'` no Python. Corrigido forçando a própria sessão do PowerShell a emitir UTF-8 (`$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8;` prefixado ao comando) — mais portável que fixar a codepage no lado do Python (que variaria por sistema/região). **Testado ao vivo:** mesmo comando agora retorna `'ção àé íóú çãõ'` corretamente.

**4. `abrir_app` tinha o mesmo bug de encoding + faltava escaping de aspas (`lyra_tools.py:202-215`).** Mesma correção de UTF-8 aplicada (o `stderr` de erros do PowerShell também saía corrompido). Além disso, `f"Start-Process '{nome}'"` sem escapar apóstrofos — um nome de app/caminho com `'` (comum) quebrava a sintaxe do PowerShell com erro genérico, sem validação. Corrigido com `nome.replace("'", "''")` (dobrar aspas simples é o escaping padrão de string literal do PowerShell). **Testado ao vivo:** nome com apóstrofo agora produz erro correto de "arquivo não encontrado" com acentos intactos, em vez de erro de sintaxe do PowerShell.

**5. (Grave) `migrar_chaves_para_keyring()` apagava chaves não-conhecidas do `.env` sem restaurá-las (`lyra_seguranca.py:184-241`).** A função migrava **qualquer** linha `chave=valor` do `.env` pro Windows Credential Manager, mas ao reescrever o `.env` só regravava as 4 chaves de `_CHAVES_CONHECIDAS` (`GROQ_API_KEY`, `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`) — e `carregar_chaves_do_keyring()` só restaura essas mesmas 4. Qualquer outra variável (ex: `TELEGRAM_ALLOWED_USERS`, que existe hoje no `.env` real) seria migrada pro keyring mas NUNCA reposta em nenhum lugar — desaparecia completamente. Cenário concreto: `TELEGRAM_ALLOWED_USERS` sumindo faz `lyra_telegram.py` tratar `ALLOWED_USERS` como conjunto vazio, o que **abre o bot pra qualquer usuário do Telegram** silenciosamente (só um log que ninguém revisita depois de rodando como serviço). Ainda não causou dano real — confirmado que a migração nunca foi executada (a chave ainda existe no `.env`). Corrigido: a migração agora só move pro keyring o que está em `_CHAVES_CONHECIDAS`; qualquer chave fora dessa lista é preservada com seu valor original no `.env` reescrito (variável `nao_migradas`, que já existia declarada no código mas nunca era usada — sinal de um refactor incompleto anterior). **Testado isoladamente** (lógica replicada com keyring fake, sem tocar no `.env` real nem no Credential Manager de produção): confirmado que `TELEGRAM_ALLOWED_USERS` e qualquer chave desconhecida sobrevivem intactas.

**6. Race condition real em `/chat` pode misturar respostas entre requisições concorrentes (`cerebro_maestro.py`, bloco de construção de `mensagens`).** `ultima_msg = mensagens[-1]["content"]` assumia que a última entrada de `historico_recente` era sempre a mensagem desta requisição — mas entre o `append` do usuário e esse ponto do código, há vários `await` (RAG híbrido, grafo SurrealDB, que o próprio código já documenta como "5-10s"). Se uma segunda requisição `/chat` concorrente também desse append nesse intervalo, `mensagens[-1]` podia ser a pergunta de OUTRA requisição — a resposta saía contaminada/trocada entre sessões simultâneas (ex: duas abas do frontend abertas). Corrigido: usa `msg.texto` (variável local desta requisição, imune a mutação concorrente) em vez de reler do estado global compartilhado. **Testado ao vivo:** duas perguntas factuais diferentes disparadas em paralelo (`curl` simultâneo, "capital da Alemanha" + "capital do Egito") — cada uma recebeu a resposta certa, sem contaminação cruzada.

### Verificação final: smoke test completo

`test_smoke.py`: **17/17 passaram** após todas as correções + restart do backend.

### ❌ Achados dos agentes que eram FALSOS POSITIVOS (verificados e descartados)

- **"Flag `--allow-dangerously-skip-permissions` do Claude CLI está errada"** — falso. Rodei `claude --help` e confirmei que essa flag existe de fato nesta versão do CLI (junto com a variante mais curta `--dangerously-skip-permissions`) — não é bug, não mexido.
- **"5 funções usam `gemini-3.5-flash`, modelo pode não existir"** — o agente inverteu a leitura: `gemini-3.5-flash` é o modelo que FUNCIONA (confirmado testando direto na API, é o mesmo usado com sucesso em `cerebro_maestro.py`); o problema real era o ÚNICO lugar com modelo DIFERENTE (`gemini-2.5-flash-preview-05-20`, item nº1 acima).

## 10.16. Câmara de Eco Heurística — bloqueio de ações de risco com confirmação explícita (02/07/2026)

Item do roadmap (`LYRA_NUCLEO.md` seção 4.4) que existia só como frase solta desde sempre: *"simula futuros possíveis na RAM antes de agir; cancela ações de risco"*. Formalizado e implementado nesta sessão, planejado antes de codar (modo de planejamento + validação por sub-agente, plano aprovado pelo usuário).

**Decisão de escopo:** v1 é heurística por padrões (regex/substring sobre o comando/args), **sem chamada de LLM** — mais rápido, zero custo de API, mesmo estilo já usado em `criar_ferramenta()` (varredura de padrões de risco no código gerado) e no roteador de intenção (`_TOOL_KEYWORDS_RE`). Uma v2 com simulação via LLM ("o que pode dar errado com essa ação?") ficou registrada como ideia futura, não implementada — usuário escolheu explicitamente a heurística.

### Mecânica

1. **`lyra_seguranca.avaliar_risco_acao(nome_tool, args) -> {"risco": "alto"|"baixo", "motivo": str|None}`** — só avalia as 4 tools realmente destrutivas:
   - `executar_comando`/`iniciar_processo_bg`: deleção em massa (`rm -rf`, `Remove-Item -Recurse -Force`, `del /s /q`), formatação/partição (`format C:` — **ancorado com regex `\bformat\s+[a-z]:`**, não substring solto, pra não confundir com `Format-Table`/`Format-List` do PowerShell), registro (`reg delete`), desligamento/usuários (`shutdown`, `Stop-Computer`, `net user /delete`), kill forçado (`Stop-Process -Force`, `taskkill /f`), download+execução (`iex`/`Invoke-Expression` + `curl`/`iwr`/`wget`), path de sistema + verbo destrutivo.
   - `escrever_arquivo`: **NÃO** trata toda sobrescrita como risco (geraria fadiga de alerta em uso normal, tipo reescrever um `.py`/`.md` de trabalho) — só extensão sensível (`.exe .dll .ps1 .bat .cmd .msi .sys .reg .vbs`) ou path fora dos diretórios de trabalho conhecidos (`C:\Lyra_Project`, `~\Documents`, `~\Downloads`, `~\Desktop`) ou dentro de diretório de sistema.
   - `organizar_pasta`: raiz de drive ou diretório crítico do sistema.
   - Qualquer outra tool: sempre "baixo", zero mudança de comportamento.
2. **`lyra_seguranca.hash_acao(nome, args)`** — SHA256 determinístico (`sort_keys=True`) de nome+args, liga uma confirmação à ação exata.
3. **`_executar_tool_segura()`** (`cerebro_maestro.py`) — depois do rate limit, antes de executar: se risco="alto" e o hash não está em `_confirmacoes_risco` (aprovação pendente), **bloqueia sem executar**, grava `_ultima_acao_bloqueada` (hash/nome/args/motivo/timestamp/turno), audita via `registrar_audit(bloqueado=True)`, e retorna `{"status": "BLOQUEADO_RISCO", ...}` instruindo o LLM a perguntar ao usuário.
4. **`chat_endpoint()`** — mesmo padrão já usado pra aprovação de delegação ao Claude (`_KEYWORDS_CLOUD_APROVADO`): lista de frases pareadas com verbo de ação (`"sim, executa mesmo assim"`, `"confirmo, pode executar"` etc. — **de propósito não inclui "sim"/"confirmo" soltos**, pra não colidir com confirmações de outro assunto tipo compromisso de calendário). Se a mensagem atual bate uma dessas frases E há uma ação pendente dentro da janela e do turno certos, marca o hash como aprovado (`_confirmacoes_risco[hash] = timestamp`) e injeta `[SISTEMA]` no prompt mandando o LLM repetir a MESMA chamada.

### Duas travas contra "aprovação vazando pro assunto errado" (não só o tempo)

Achado real do sub-agente de planejamento: uma janela de tempo sozinha (mesmo curta) deixa uma frase genérica tipo "sim, confirmo" dita num contexto não relacionado (ex: confirmando um evento de calendário) aprovar silenciosamente uma ação destrutiva de minutos atrás que o usuário já esqueceu. Mitigado com 2 travas combinadas, não só timestamp:

1. **Hash da ação exata** — a aprovação só vale pra ação especificamente pendente, nunca aprova outra coisa.
2. **Só no turno IMEDIATAMENTE seguinte ao bloqueio** — `_contador_turnos` (novo global, incrementado 1x por `/chat`) estampa em qual turno o bloqueio ocorreu; a confirmação só é aceita se `_contador_turnos_atual == turno_do_bloqueio + 1`. Janela de tempo (10min, escolha do usuário — tempo suficiente pra ler e responder sem pressa) fica como camada extra, não como única defesa.

**Bug real corrigido durante o teste ao vivo:** a primeira versão usava `len(historico_recente) == indice_gravado_no_bloqueio` pra checar "próximo turno" — quebrado por dois motivos: (1) offset errado (entre o bloqueio e a checagem, sempre 2 mensagens são appendadas — a resposta do turno bloqueado + a pergunta do turno seguinte — e o código não contava com isso), e (2) `historico_recente` é **truncado/reescrito** por `_comprimir_historico()` quando passa de 14 mensagens, o que tornaria qualquer índice absoluto guardado antes lixo. Corrigido trocando por um contador de turnos monotônico dedicado (`_contador_turnos`), imune a isso. Achado só foi possível testando o fluxo de ponta a ponta de verdade (a LLM simplesmente não repetiu a chamada da ferramenta na primeira tentativa) — não teria aparecido em teste unitário isolado do classificador de risco.

### Limitação conhecida (não é bug, é comportamento observado do Groq)

Em alguns turnos o Groq manda a MESMA tool call duas vezes na mesma resposta (quirk conhecido de function-calling de LLMs). Como a aprovação é de uso único, a 1ª chamada consome o hash e executa; a 2ª chamada idêntica não encontra mais aprovação e gera um NOVO bloqueio "fantasma" — que fica pendente até expirar sozinho (10min) ou ser substituído pelo próximo bloqueio real, sem nunca ser mencionado pela Lyra (ela já tinha o resultado de sucesso da 1ª chamada pra responder). Sem impacto observado no usuário; registrado como comportamento conhecido, não corrigido (não vale a complexidade de deduplicar tool calls idênticas no mesmo turno agora).

### Validado ao vivo (02/07/2026)

- **Unitário isolado**: 22/22 casos reais de `avaliar_risco_acao` corretos (incluindo negativos importantes: `Get-Process | Format-Table` não confunde com `format C:`; escrita normal de `.py` dentro do projeto não dispara risco). Hash determinístico confirmado (ordem de args não importa, args diferentes geram hash diferente).
- **`_executar_tool_segura` isolado**: comando de risco com path forjado (inofensivo) bloqueado sem executar; aprovação manual inserida no dict faz a 2ª chamada executar de verdade (erro benigno de "não encontrado", confirmando execução real); 3ª chamada (hash já consumido) bloqueia de novo.
- **`/chat` real, ciclo completo**: pedido de `Stop-Process -Name <processo_inexistente> -Force` → Lyra bloqueia e pergunta ("Você confirma?"); mensagem "sim, executa mesmo assim" → Lyra chama a ferramenta de novo, recebe erro benigno de processo não encontrado, reporta corretamente ("nenhum encerramento foi necessário"). `test_smoke.py` 17/17 antes e depois.

## 11. Ações pendentes de stack (priorizadas)

- ✅ ~~Adicionar `retrieval_count`+`last_accessed_at` nas memórias do Qdrant~~ (feito 26/06)
- ✅ ~~Implementar session briefing no startup~~ (feito 26/06)
- ✅ ~~Implementar retrieval ponderado: score = α·semântico + β·recência~~ (feito 26/06: 0.7·rrf + 0.3·recência)
- ✅ ~~Concluir vetorização BGE-M3 e migrar `cerebro_maestro` pra `lyra_memory_v2`~~ (feito 26/06 — migração total, v1 apagada)
- ✅ ~~Otimizar latência do BM25 sobre 3.08M docs~~ (feito 26/06: migrado `rank_bm25` → **bm25s** esparso. `/buscar` 2.1s → **382ms**. Índice em `bm25s_index/` + `bm25s_meta.pkl`, mmap.)
- ✅ ~~Avaliar vector search nativo do SurrealDB 3.0~~ (pesquisado 01/07/2026, ver "Avaliação SurrealDB 3.0 vs Qdrant" abaixo)
- ✅ ~~Avaliar Mem0/Kore como referência de decay de memória~~ (pesquisado 01/07/2026, ver "Avaliação Mem0/Kore" abaixo)
- ✅ ~~Shadow Thoughts: agendamento automático no loop_proativo~~ (feito 01/07/2026 — Fase 3 completa)
- ✅ ~~`lyra_agent.py` integrado ao backend com endpoint HTTP~~ (feito 01/07/2026)
- ✅ ~~Decay Ebbinghaus variável por categoria~~ (feito 01/07/2026)
- ✅ ~~Reconciliação SurrealDB↔Qdrant~~ (feito 01/07/2026 — 15 episódios recuperados)
- **[MÉDIA]** Migrar frontend Three.js para WebGPURenderer (r171+)
- ✅ ~~Investigar protocolo A2A~~ (pesquisado 01/07/2026, ver "Avaliação A2A" abaixo)
- ✅ ~~Dashboard de telemetria histórica~~ (feito 01/07/2026, ver "Telemetria histórica" abaixo)
- ✅ ~~Módulo central de segurança (audit log + rate limiter + keyring + self-healing)~~ (feito 01/07/2026)
- ✅ ~~Clipboard AI (analisar_clipboard_com_ia)~~ (feito 01/07/2026)

## 12. Segurança e Monitoramento (01/07/2026)

### ✅ lyra_seguranca.py — módulo central de segurança

Novo arquivo `Lyra_Ollama/lyra_seguranca.py` com 4 componentes:

**Rate Limiter (in-memory, thread-safe)**

- `checar_rate_limit(nome_tool)` → `(permitido: bool, mensagem: str)`
- Usa `deque` por tool + `threading.Lock`. Remove timestamps expirados em cada chamada.
- Limites configurados em `_RATE_LIMITS`:
  - `executar_comando`: 20/5min | `iniciar_processo_bg`: 5/5min
  - `escrever_arquivo`: 30/60s | `organizar_pasta`: 3/5min
  - `criar_ferramenta`: 5/10min | `consultar_especialista`: 3/10min | `navegar_web`: 10/5min
- `resetar_rate_limit(nome_tool)` disponível para uso administrativo.

**Audit Log (SurrealDB append-only)**

- `registrar_audit(tool, args, resultado, solicitante, bloqueado, motivo_bloqueio)` — não bloqueia nunca.
- Padrão: buffer em memória + daemon thread `lyra-audit-flush` que descarrega a cada 5s.
- Tabela `audit_log` no SurrealDB (`lyra_core.Db_CORTEX`). Cada registro armazena: timestamp, tool, args_resumo (≤500 chars), resultado_resumo (≤500 chars), solicitante, bloqueado, motivo_bloqueio.
- `consultar_audit(limite, tool_filtro, apenas_bloqueados)` — queries filtradas.

**Windows Credential Manager (keyring)**

- `migrar_chaves_para_keyring()` — lê `.env`, salva cada chave no Credential Manager, sobrescreve `.env` com valores em branco. **Admin-only: NÃO está no TOOLS_MAP.**
- `carregar_chaves_do_keyring()` — injeta chaves em `os.environ` no startup.
- `listar_chaves_keyring()` — mostra quais chaves estão configuradas (sem revelar valores).
- Chaves conhecidas: `GROQ_API_KEY`, `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`.
- Requer `pip install keyring`.

**Health Check de serviços**

- `checar_servicos()` — HTTP GET nos 5 serviços: SurrealDB(:8090/health), Qdrant(:6333/healthz), embed_service(:8001/health), Ollama(:11434/api/version), FastAPI(:8000/health). Timeout 3s por serviço.
- `tentar_reiniciar_servico(nome)` — PowerShell `Start-Process` para SurrealDB, Qdrant e embed_service. Aguarda 3s e re-verifica.

### ✅ cerebro_maestro.py — integração de segurança

`_executar_tool_segura()` agora:

1. Chama `checar_rate_limit(nome)` antes de qualquer execução.
2. Se bloqueado: registra audit com `bloqueado=True` e retorna JSON de erro imediatamente.
3. Se permitido: executa tool, registra audit com resultado.

`loop_proativo()` agora:

- A cada 5 iterações (~5min): chama `checar_servicos()`, reinicia automaticamente serviços offline via `asyncio.to_thread(tentar_reiniciar_servico, nome)`.
- Usa `_iteracoes_loop % 5 == 0` como gatilho.

### ✅ lyra_tools.py — novas ferramentas (total: 58 tools)

**Seção 17 — Segurança e Monitoramento:**

- `consultar_audit_log(limite, tool_filtro, apenas_bloqueados)` → wrapper de `lyra_seguranca.consultar_audit()`
- `checar_servicos_lyra()` → wrapper de `lyra_seguranca.checar_servicos()`
- `listar_chaves_keyring()` → wrapper de `lyra_seguranca.listar_chaves_keyring()`
- `migrar_chaves_para_keyring()` → wrapper admin (existe como função Python, mas **excluída do TOOLS_MAP** intencionalmente)

**Seção 18 — Clipboard AI:**

- `analisar_clipboard_com_ia(instrucao="")` — lê área de transferência, envia ao Gemini (gemini-2.5-flash-preview-05-20) ou ao Ollama local ("Lyra") como fallback, escreve resultado de volta no clipboard.
- Requer `pip install pyperclip`.

**Contagem final verificada:** `TOOLS_MAP = 58 | TOOLS_SCHEMA = 58` (teste passou com `python -c "..."`).

---

## 2.6. Reformulação do frontend — shell de navegação estilo app Claude (04/08/2026)

UI reorganizada com inspiração estrutural no app do Claude (sidebar + views), mantendo a identidade Lyra (esfera 3D, neon ciano, glassmorphism, Inter, sentence case). **Stack mantida: vanilla JS, zero build step** — decisão deliberada (Tauri/framework não ajudam o objetivo de executável; PyInstaller + pywebview empacota o que existe).

### Arquivos novos
- `Front_end_Lyra/ui.css` — sidebar, views, cards, toggles, chat como view central.
- `Front_end_Lyra/ui.js` — roteador de views (`LyraUI.showView`), sessões, integrações, toggles de config. Carrega DEPOIS do script.js e usa as globals dele.

### Estrutura de navegação
- **Sidebar persistente** (recolhível pra rail de ícones via hambúrguer, persiste em `localStorage.lyra_sb_collapsed`): nova conversa, nav (início/chat/memória/integrações/configurações), lista de conversas (sessões), rodapé com dots WS/cérebro/estado + fonte + seletor de modelo (`#sel-modelo` continua com o mesmo id).
- **Chat virou view central** (não é mais modal flutuante) — `toggleChat()` no script.js virou fachada que delega pro `LyraUI.showView`. `#chat-scrim` morto (display:none).
- **Configurações** (view nova): toggle TTS (espelha `btn-mute`/`lyra_tts_mudo`), toggle grain, atividade/telemetria/serviços (blocos movidos do painel antigo, MESMOS ids: `m-*`, `t-*`, `svc-*`, `dot-*` — `_setupMetrics`/`_setupHealth` intocados), build.
- **Integrações** (view nova): cards Telegram/voz live/mic/TTS/enxame/upload com status real via `GET /integracoes` (poll 12s).
- Esc fecha na ordem: grafo > view atual > home. `/` continua abrindo o chat. Painel lateral antigo (`#side-panel`, `#top-left`) removido do HTML e do CSS.
- `-webkit-app-region: no-drag` obrigatório em sidebar/views/chat — sobem até a faixa do `#drag-region` (52px).

### Sessões de conversa (backend, cerebro_maestro.py)
- Globals `sessao_atual` / `_sessao_titulo_ok`; helpers `_sql_surreal()`, `_surreal_result()`, `_sessao_id_limpo()`.
- `registrar_evento` grava `sessao_id` em cada evento; primeira fala do usuário vira título da sessão (UPDATE sessao).
- Startup (`_carregar_estado_inicial`): retoma a sessão mais recente (restart continua a conversa, histórico restaurado filtrado por ela); se banco pré-migração, cria a primeira sessão e mantém o restore antigo.
- Endpoints novos (mesmos padrões: 127.0.0.1, CORS do app): `GET /sessoes` (lista + entrada sintética `legado` p/ eventos sem sessao_id), `POST /sessoes` (nova sessão, zera historico_recente — SurrealDB/Qdrant intactos), `POST /sessoes/ativar` (troca sessão e recarrega historico_recente), `GET /historico?sessao=<id|legado>` (mensagens da sessão direto do SurrealDB; sem parâmetro = comportamento original).
- `GET /integracoes`: telegram/mic via `psutil.process_iter` (cmdline contém `lyra_telegram`/`mic_engine`), voz live via contador `_voice_live_ativas` no `/ws/voice`, TTS via `_tts_mudo`.

### Não quebrado (verificado)
Esfera 3D, grafo (`abrirGrafo` só perdeu a linha do painel antigo), voz live, mic, export, upload/drag&drop, histórico ↑/↓, boot sequence, prefers-reduced-motion. Smoke: `py_compile` OK, `node --check` OK, cross-check getElementById×HTML sem ids órfãos.

### 2.6.1. Correções pós-deploy do frontend novo (04/08/2026, noite) — testado ao abrir a Lyra de verdade

Ao subir a Lyra pela primeira vez com o shell novo, dois bugs reais nas queries SurrealDB das sessões (Fase 2):

1. **Record id escapado com crase, não `⟨⟩`** — a versão do SurrealDB rodando aqui devolve `sessao:\`uuid\`` (crase), não `sessao:⟨uuid⟩`. `_sessao_id_limpo()` só tirava `⟨⟩` e deixava as crases coladas no id, quebrando a comparação "sessão ativa" na sidebar. Corrigido pra também stripar crase. E pra escrever (UPDATE do título), trocado o `f"UPDATE sessao:⟨{id}⟩"` manual por `UPDATE type::record("sessao", $id)` com o id via `json.dumps` — evita depender de qual caractere de escape a instalação usa.
2. **`ORDER BY` em campo fora do `SELECT`** — SurrealDB rejeita com 400 (`Idiom missing here`) se você faz `SELECT sessao_id ... ORDER BY timestamp` sem `timestamp` no SELECT. Achado na query de retomada de sessão do startup (`_carregar_estado_inicial`); corrigido incluindo `timestamp` no SELECT. As outras queries do arquivo já seguiam essa regra — só essa nova quebrava.

Também achado no processo (não é bug do código novo): havia um `cerebro_maestro.py` antigo ainda rodando na porta 8000 de uma sessão anterior, sem os endpoints novos — o `lyra_launcher.py` detecta a porta ocupada mas não mata o processo antigo, só tenta subir um novo ao lado e falha no bind. Precisou `Stop-Process` manual no PID antigo antes de reiniciar. Vale considerar o launcher matar processo antigo na mesma porta automaticamente — não fiz essa mudança agora (fora do escopo do frontend).

---

## 3. Refatoração OOP completa (07-08/08/2026)

Migração de todo o backend Python de procedural pra OOP, em 6 fases, seguindo plano aprovado pelo usuário. **Zero quebra de contrato de API** (endpoints HTTP/WS idênticos) — validado com `test_smoke.py` (17/17) rodando contra o sistema real (SurrealDB + Qdrant + embed_service + Ollama + Groq) após cada fase.

### Arquivos novos
- `config.py` — todas as portas/URLs/model IDs num só lugar (substituiu 127 magic strings espalhados).
- `surreal_client.py` — `SurrealClient` (substitui 5 implementações duplicadas de `_sql_surreal`/`_sq`/`_sx`/`_surreal_query`/`_sql`). Singleton `surreal` importado por todo mundo.
- `logger.py` — `Logger` com `atexit` registrado (corrige file descriptor leak do `open()` solto em `cerebro_maestro.py`).
- `llm_cascade.py` — `LLMCascade`: unifica a cascata Groq→Gemini→Claude CLI→local que estava triplicada em `cerebro_maestro.py` (streaming SSE), `lyra_agent.py` e `lyra_agentes.py` (batch). Modo streaming (`stream_groq/gemini/claude_cli/local`) e modo batch (`run()`).
- `session_manager.py` — `SessionManager`: histórico de conversa, sessão ativa, briefing, contador de turnos — tudo que era global solto em `cerebro_maestro.py`, agora com locks internos.
- `rag_engine.py` — `RAGEngine`: busca híbrida (BM25+denso+rerank+freshness), traversal de grafo, persistência de eventos (SurrealDB+Qdrant). Também hospeda os utilitários de texto (`remove_accents`, `extract_keywords`, `classify_intent`) que eram funções soltas no módulo do cérebro.
- `proactive_loop.py` — `ProactiveLoop`: o antigo `loop_proativo()` de 156 linhas, decomposto em sub-métodos testáveis (lembretes, números, agendamentos, processos bg, enxames, self-healing).
- `Lyra_Ollama/tools/` — `lyra_tools.py` (3028 linhas indiferenciadas) dividido em 16 submódulos por domínio (`fs`, `os_tools`, `vision`, `memory`, `documents`, `web`, `system`, `notifications`, `reminders`, `processes`, `numbers`, `specialist`, `clipboard`, `git_tools`, `email_cal`, `security_tools`) + `_registry.py` (`ToolRegistry`) + `_lazy.py`/`_shared.py` (singletons/helpers compartilhados). `__init__.py` agrega tudo em `TOOLS_MAP`/`TOOLS_SCHEMA`/`run_tool` — contrato idêntico ao antigo, 58/58 ferramentas conferidas por comparação automática entre o antigo e o novo antes do swap.

### Desvio deliberado do plano original
O plano pedia nomes de função em inglês também dentro de `tools/`. Não fiz essa parte: os nomes de função Python nesse módulo são o próprio contrato de function-calling usado pelo LLM em produção (system prompt, agentes, schema `"name"`) — renomear 70+ funções either quebraria esse contrato ou exigiria manter dois nomes por função (Python vs schema), risco desproporcional ao ganho estético. Mantive os nomes em português; documentação/comentários novos (docstrings de classe, `_registry.py`, `_lazy.py`, `_shared.py`) seguem em inglês conforme pedido.

### Bugs corrigidos na refatoração
- File descriptor de `maestro.log` nunca fechado → `Logger` com `atexit`.
- Race em `historico_recente`/`_contador_turnos` (múltiplas `/chat` concorrentes) → `asyncio.Lock` dentro de `SessionManager`.
- Race em `sessao_atual`/`_session_briefing` no startup vs primeiro `/chat` → `asyncio.Event` (`wait_ready()`/`load_initial_state()`).
- Lazy singletons sem lock (`_qdrant`, `_bm25`, `_gemini_tools_cache` em `cerebro_maestro.py`, `lyra_tools.py`) → double-checked locking com `threading.Lock`.
- SQL injection em `consultar_audit_log` (`tool_filtro` interpolado direto na query) → validação `re.fullmatch(r"[a-zA-Z0-9_]+")` antes de interpolar.
- `_TOOLS_EXT_DIR`/`_PROCESSOS_BG_LOG_DIR`/`_NTFY_TOPICO_FILE` usavam `pathlib.Path(__file__).parent` — ao mover pra `tools/`, isso apontaria pro subdiretório errado; corrigido pra `.parent.parent` (mantém os mesmos caminhos em disco de antes, `lyra_tools_ext/` etc continuam em `Lyra_Ollama/`).

### Compatibilidade
`lyra_tools.py` virou shim de 12 linhas (re-exporta `TOOLS_MAP`, `TOOLS_SCHEMA`, `executar_tool`, e os símbolos internos usados por `proactive_loop.py`/`lyra_seguranca.py`) — nenhum consumidor precisou mudar. Original de 3028 linhas preservado em `_lixeira/lyra_tools_ORIGINAL_pre_split.py`. `lyra_tools_ext/somar_numeros.py` (ferramenta de exemplo, nunca usada em produção) também movida pra `_lixeira/` — `_index.json` zerado.

### Nomenclatura interna alterada (referência pra quem procurar código antigo)
- `sessao_atual`/`_sessao_titulo_ok`/`historico_recente`/`_session_briefing`/`_contador_turnos` (globals soltos) → atributos/métodos de `SessionManager` (`_session.session_id`, `_session.briefing`, `_session.turn_counter`, `_session.snapshot()`/`sanitized_messages()`/`append_user()`/`append_assistant()`).
- `buscar_hibrido()`/`registrar_evento()`/`buscar_grafo_surreal()` (funções soltas) → métodos de `RAGEngine` (`_rag.search()`/`.record_event()`/`.search_graph()`), com wrappers de compatibilidade no módulo (mesmos nomes, mesma assinatura) pra `calibrar_pesos_rag.py` e o endpoint `/grafo` não precisarem mudar.
- `qdrant_client`/`indice_bm25` (globals) → `_rag.qdrant_client`/`_rag.bm25_index`.
- `_stream_groq`/`_stream_gemini`/`_stream_claude_cli`/`_stream_local` (implementações completas) → wrappers finos sobre `LLMCascade`, que agora concentra toda a lógica de streaming/tool-calling por provedor.
