# -*- coding: utf-8 -*-
"""Conteúdo textual do LYRA_GENESIS_V2.pdf — editar aqui, não no gerador."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from gerar_genesis_pdf import Doc  # noqa: E402

OUT = str(pathlib.Path(__file__).parent.parent / "LYRA_GENESIS_V2.pdf")


def build():
    d = Doc(OUT)

    # ════════════════════════════════════════════════════════════════
    d.title("LYRA — NÚCLEO DO PROJETO", "> Consolidado em 22/06/2026. Atualizado em 02/07/2026.")

    d.section("1. Quem é o arquiteto")
    d.para(
        "Antônio — estudante de ADS na UNIMAR (Marília-SP). Arquiteto único do projeto Lyra "
        "(IA pessoal local). Entendimento técnico sólido, prefere explicações diretas e sem "
        "enrolação. Treina bateria, frequenta academia."
    )
    d.gap(4)
    d.bullet("Hardware:", "Ryzen 7 3700X | RTX 2060 SUPER 8GB VRAM | 64GB RAM | 2.73TB HD")
    d.bullet("Email:", "antonio.assuino.salomao@gmail.com")
    d.gap(6)

    d.section("2. O que é a Lyra")
    d.para(
        "IA pessoal local, identidade feminina, voz suave/técnica/clínica, não-servil. Não é "
        "um chatbot — é pensada como organismo cognitivo: hardware como corpo, modelos como "
        "córtex, SurrealDB+Qdrant como memória."
    )
    d.gap(6)

    d.section("3. Ring 0 — Princípios Invioláveis")
    d.bullet("1.", "Antônio é o Administrador Supremo. Protocolo de Sobrescrita anula qualquer raciocínio da máquina.")
    d.bullet("2.", "core.py é somente leitura.")
    d.bullet("3.", "100% offline por padrão. Exceções conscientes aprovadas: cascata cloud (Groq→Gemini→Claude→local) desde 25/06/2026; TTS online; consultar_especialista(nivel=\"cloud\") delega ao Claude Code sem aprovação por ação.")
    d.bullet("4.", "Hardware-Bound Logic Gates — telemetria da placa-mãe/RTX/RAM como chave física.")
    d.bullet("5.", "Toda auto-modificação de código requer aprovação explícita antes de produção.")
    d.bullet("6.", "Ações de execução de alto risco exigem confirmação explícita no chat — Câmara de Eco Heurística (seção 4.4).")
    d.gap(6)

    d.section("4. Arquitetura de Cognição e Memória")
    d.subsection("4.1 Camadas de memória")
    d.table(
        ["Camada", "Tecnologia", "Função"],
        [
            ["RAM (volátil)", "Contexto LLM + cache quente", "Working memory"],
            ["Qdrant (vetores)", "BAAI/bge-m3, 1024d (lyra_memory_v2), embed_service :8001", "Memória semântica"],
            ["SurrealDB (grafos)", "Tabelas + relações ->", "Memória episódica/temporal"],
            ["Cold storage", "Arquivos comprimidos em disco", "Memória arquivada"],
        ],
        [95, 300, 130],
    )
    d.para("Base atual: ~3.27M registros no SurrealDB. Funil de Eventos intercepta toda mensagem, grava timestamp, SurrealDB e Qdrant; últimas 10 msgs em RAM.")
    d.gap(6)

    d.subsection("4.2 Shadow Thoughts — Ciclo de Sono")
    d.para("✓ IMPLEMENTADO (01/07/2026) — agendado automático a cada 3h no loop_proativo:", cor=(0.298, 0.6863, 0.3137))
    d.bullet("WAKE:", "registra episódios novos (tag new_memory).")
    d.bullet("NREM:", "dedup semântico (cosseno > 0.95) — marca duplicado=True, não apaga. 1ª execução: 28 duplicatas.")
    d.bullet("REM:", "cria arestas 'conecta' cross-domain entre tópicos co-ocorrentes no SurrealDB.")
    d.bullet("DEEP SLEEP:", "comprime eventos > 4 semanas em resumos semanais.")
    d.bullet("Endpoint:", "POST /shadow_thoughts para disparo manual.")
    d.gap(6)

    d.subsection("4.3 Memória em grafos nativos (SurrealDB)")
    d.para("✓ IMPLEMENTADO. _grafo_salvar_relacoes() cria, a cada evento, arestas evento→precedeu→evento (threading) e evento→sobre→topico:keyword (indexação). buscar_grafo_surreal() faz traversal e complementa o RAG. Exposto em GET /grafo.", cor=(0.8627, 0.8824, 0.9216))
    d.gap(6)

    d.subsection("4.4 Outros mecanismos cognitivos")
    d.bullet("Enxame de sub-agentes (lyra_agentes.py):", "IMPLEMENTADO. Decompõe tarefa em N sub-tarefas paralelas via asyncio.Semaphore, consolida via LLM.", status="ok")
    d.bullet("Enxame de especialistas (MoE roteado):", "IMPLEMENTADO (02/07/2026). Lista declarativa ESPECIALISTAS roteia a cascata do /chat por categoria (codigo/geral).", status="ok")
    d.bullet("Speculative Decoding:", "IMPLEMENTADO (02/07/2026) — não acelera geração (inviável com APIs cloud); é sidecar de detecção de divergência semântica: draft qwen3:0.6b em paralelo, divergencia_draft = 1 - cosseno. Limiar 0.45, só loga, não bloqueia.", status="ok")
    d.bullet("Câmara de Eco Heurística:", "IMPLEMENTADO (02/07/2026) — v1 heurística por padrões (sem LLM). Bloqueia executar_comando/iniciar_processo_bg/escrever_arquivo/organizar_pasta de alto risco e exige confirmação explícita no turno seguinte.", status="ok")
    d.gap(6)

    d.subsection("4.5 Protocolo Darwin — Auto-evolução (Fase 5+)")
    d.para("Archive de versões, geração de variantes em sandbox RAM, rollback automático em regressão. ADAS (meta-agente): cria agentes para problemas recorrentes.")

    # ════════════════════════════════════════════════════════════════
    d.section("5. Interface / Front-end")
    d.para("Sem janelas padrão do Windows — tudo flutua sobre o desktop via pywebview + Three.js.")
    d.gap(4)
    d.bullet("Esfera de Partículas:", "núcleo azul central com 3 camadas (60 brilhantes + 240 médias + 300 pequenas), fundo espacial com nebulosas, rotação suave, reage ao estado (idle/ouvindo/processando/falando).")
    d.bullet("Painel Lateral:", "conexões WS/Cérebro, estado, modelo, atividade (CPU/RAM/GPU/VRAM + sparkline), telemetria de tiers + sparkline histórico, serviços, botão de Grafo de Memória.")
    d.bullet("Chat:", "modal flutuante, export .md, limpeza de histórico, anexo de imagem/áudio, botão reler em voz alta por mensagem.")
    d.bullet("Grafo de Memória 3D:", "overlay fullscreen com 3d-force-graph v1.73.4 + Three.js r128. Lyra no centro fixada, tópicos na esfera Fibonacci, eventos como partículas. Busca de nós, detalhe ao clicar. Conectado ao SurrealDB via /grafo/completo.")
    d.bullet("Axônios sinápticos:", "chegou a ser implementado e testado, mas DESCARTADO (01/07/2026) por pedido do Antônio. Não reimplementar sem pedido novo.", status="off")
    d.gap(6)

    d.section("6. Voz, Sentidos e Telemetria")
    d.bullet("Voz pipeline 1:", "mic_engine.py — wake word 'lyra' → Silero VAD → faster-whisper 'small' → /chat. TTS PAUSADO por decisão do usuário.")
    d.bullet("Voz pipeline 2 (Voice Live):", "botão dedicado, Gemini Live API (gemini-2.5-flash-native-audio-latest), WEBSOCKET /ws/voice, bidirecional em tempo real.")
    d.bullet("Visão Semântica:", "explicar_tela() via Gemini Vision (primário) + llava-phi3 (fallback). analisar_imagem() para imagens em disco.")
    d.bullet("Emotion Engine:", "planejado — análise paralinguística, 40+ estados via pitch/tempo/tremor.", status="wip")
    d.bullet("Wi-Fi Sensing:", "planejado — CSI via ESP32 como sonar passivo (802.11bf).", status="wip")

    # ════════════════════════════════════════════════════════════════
    d.section("7. Stack Técnico Atual (canônico — 02/07/2026)")
    d.table(
        ["CAMADA", "TECNOLOGIA"],
        [
            ["Interface", "Three.js + pywebview (TS/JS)"],
            ["WebSocket hub", "ws://127.0.0.1:8765 (lyra_app.py)"],
            ["Backend/API", "FastAPI :8000 (cerebro_maestro.py) — expõe MCP em /mcp"],
            ["LLM Engine", "Ollama + cascata cloud Groq→Gemini→Claude→local"],
            ["LLM Principal", "Groq gpt-oss-120b / Gemini 3.5-flash / Claude Sonnet / qwen3:8b (fallback)"],
            ["Embedding", "BAAI/bge-m3 (1024d) via embed_service :8001 — migração CONCLUÍDA"],
            ["Reranker", "bge-reranker-v2-m3 (cross-encoder) via embed_service :8001 /rerank"],
            ["BM25 esparso", "bm25s — bm25s_index/ + bm25s_meta.pkl. /buscar ~382ms"],
            ["Vector DB", "Qdrant standalone :6333 (v1.17.1 FIXADO — não atualizar)"],
            ["Graph+Doc DB", "SurrealDB 3.0.5 (:8090, NS 'lyra_core', DB 'Db_CORTEX')"],
            ["TTS", "PAUSADO por decisão do usuário"],
            ["STT", "faster-whisper 'small' (CPU int8)"],
            ["Visão", "Gemini Vision (primário) + llava-phi3 (fallback)"],
            ["Agente ReAct", "lyra_agent.py — loop ReAct + POST /agente"],
            ["Enxame", "lyra_agentes.py — asyncio.Semaphore, fan-out/fan-in"],
            ["Shadow Thoughts", "lyra_shadow_thoughts.py — NREM/REM/DEEP, cron ~3h"],
            ["Segurança", "lyra_seguranca.py — sandboxing + Câmara de Eco Heurística"],
            ["Integrações", "lyra_telegram.py, lyra_browser.py, lyra_google_workspace.py"],
        ],
        [110, 415],
    )

    d.section("8. Roadmap por Fases")
    roadmap = [
        ("0-1", "Ingestão de datasets, vetorização Qdrant, Modelfile, commands.py, audio_manager.py, mic_engine.py, webcam.py, frontend pywebview, Funil de Memória", "ok"),
        ("2", "lyra_tools.py (acesso total ao PC), auto-extensão", "ok"),
        ("2", "Cascata de modelos cloud (Groq→Gemini→Claude→local)", "ok"),
        ("2", "Hybrid RAG (BM25 bm25s + BGE-M3 dense + RRF + bge-reranker-v2-m3)", "ok"),
        ("2", "Enxame de sub-agentes paralelos (lyra_agentes.py)", "ok"),
        ("2", "Grafo de Memória 3D (3d-force-graph + Three.js)", "ok"),
        ("2", "lyra_agent.py (loop ReAct + self-test) + integrado ao backend POST /agente", "ok"),
        ("2", "Geração de imagens (gerar_imagem() via Pollinations.ai)", "ok"),
        ("2", "Voz Live bidirecional (Gemini Live, /ws/voice)", "ok"),
        ("3", "Shadow Thoughts (NREM/REM/DEEP) — agendado 3h", "ok"),
        ("3", "5 Inovações Cognitivas: Goal Drift, Freshness Tags, Session Replay, Cognitive Load, Response Provenance", "ok"),
        ("3", "Telemetria histórica (sparkline de cascata, /stats/historico)", "ok"),
        ("3", "Reconciliação SurrealDB↔Qdrant (reconciliar_episodios.py)", "ok"),
        ("3", "Refactor cascata — executar_chat_com_tools() compartilhado", "ok"),
        ("3", "Speculative Decoding (sidecar de detecção de alucinação)", "ok"),
        ("3", "Enxame de especialistas (MoE roteado)", "ok"),
        ("3", "Câmara de Eco Heurística (bloqueio de ações de risco)", "ok"),
        ("4", "Emotion Engine (voz paralinguística, 40+ estados)", "wip"),
        ("4", "Wi-Fi Sensing via ESP32 (802.11bf CSI)", "wip"),
        ("5", "Protocolo Darwin (auto-reescrita supervisionada, ADAS)", "wip"),
        ("6", "BCI OpenBCI ESP-EEG, Protocolo Narciso (digital twin)", "future"),
    ]
    for fase, item, status in roadmap:
        d.bullet(f"[Fase {fase}]", item, status=status)
    d.gap(6)

    d.section("9. Visão de Longo Prazo")
    for item in [
        "Sistema de Arquivos Líquido — hard links que 'brotam' conforme contexto.",
        "Total Recall — OCR contínuo de tela indexado.",
        "Telepatia de Clipboard — intercepta Ctrl+C, age antes do Ctrl+V.",
        "DNA de Projeto — versionamento semântico que guarda a intenção, não só o diff.",
        "OPSEC avançado — esteganografia de núcleo, sandbox hipertempo em RAM, honeypot USB, CRYSTALS-Kyber.",
        "Soberania acadêmica — mentor UML/Java, resumidor automático de PDFs de aula.",
        "Sensor Fusion — unifica Wi-Fi CSI + microfone + teclado + câmera num modelo de estado global.",
        "Ghost OS Level 2 — isolamento via namespace/eBPF.",
    ]:
        d.bullet(None, item)
    d.gap(10)
    d.para('"Não é uma IA. É uma extensão do sistema nervoso."', cor=(0.7059, 0.8235, 1.0), size=9.5)

    # ════════════════════════════════════════════════════════════════
    d.title("LYRA — REFERÊNCIA TÉCNICA", "> Consolidado em 25/06/2026. Atualizado em 02/07/2026.")

    d.section("1. Padrões Técnicos Confirmados (não quebrar)")
    d.bullet(None, "Embedding padrão: BAAI/bge-m3 (1024 dims) — migração CONCLUÍDA (26/06/2026). Coleção lyra_memory_v2, ~3.09M vetores, 100% GPU.", status="ok")
    d.bullet(None, "embed_service.py (:8001) serve BGE-M3 + reranker bge-reranker-v2-m3 como microserviço HTTP. cerebro_maestro.py NÃO carrega sentence_transformers direto.")
    d.bullet(None, "NUNCA usar ENCODE_BATCH acima de 32 nem MAX_SEQ_LEN > 512 — estoura VRAM.", status="off")
    d.bullet(None, "CRÍTICO — usar 127.0.0.1, NUNCA localhost, em chamadas internas. localhost ~2050ms vs 127.0.0.1 ~5-20ms no Windows (resolver tenta IPv6 primeiro).", status="off")
    d.bullet(None, "UUID determinístico (uuid5) para IDs do Qdrant — hash() colidia e não era idempotente.")
    d.bullet(None, "Paginação por cursor no SurrealDB (WHERE id > $cursor), nunca LIMIT/START com 1M+ registros.")
    d.bullet(None, "CRÍTICO — import pyarrow ANTES de torch (Windows). Ordem trocada gera access violation 0xc0000005 sem traceback.", status="off")
    d.bullet(None, "NUNCA atualizar binário do Qdrant sem backup completo de qdrant_data/ — v1.17.1→v1.18.2 já descartou ~666k vetores. Fixado em v1.17.1.", status="off")
    d.bullet(None, "venv_embed (5GB) APOSENTADO (30/06/2026) — Python principal atualizado pra torch 2.6+cu124, embed_service roda nele direto.", status="ok")
    d.bullet(None, "Decay Ebbinghaus — REMOVIDO (01/07/2026). Score = relevancia*0.94 + freshness_factor*0.06 (Knowledge Freshness Tags, seletivo por categoria).", status="off")
    d.bullet(None, "sys.stdout.reconfigure(encoding='utf-8', errors='replace') obrigatório em todo script com output redirecionado.")
    d.bullet(None, "SurrealDB porta 8090, DB 'Db_CORTEX' (case-sensitive). Headers HTTP surreal-ns/surreal-db (não NS/DB).")
    d.gap(6)

    d.section("2. Bugs e Melhorias")
    d.subsection("Resolvidos recentemente (01-02/07/2026)")
    for txt in [
        "Refactor cascata — executar_chat_com_tools() compartilhado elimina 3 cópias do loop de tool-calling. _MAX_ITERACOES_TOOLS=25.",
        "Reconciliação SurrealDB↔Qdrant — 15 episódios órfãos de 26/06 recuperados por reconciliar_episodios.py.",
        "5 Inovações Cognitivas: Goal Drift Detector, Knowledge Freshness Tags, Session Replay, Cognitive Load Throttling, Response Provenance.",
        "MoE roteado (ESPECIALISTAS) — lista declarativa formaliza o roteamento codigo/geral da cascata do /chat.",
        "Speculative Decoding — sidecar de detecção de divergência semântica (qwen3:0.6b draft em paralelo).",
        "Câmara de Eco Heurística — bloqueio de ações de risco (deleção/formatação/shutdown/etc) com confirmação explícita no turno seguinte.",
        "navegar_web (browser-use) corrigido de ponta a ponta — Chromium instalado, API nova do browser-use (ChatGoogle), modelo Gemini com quota real.",
        "Auditoria geral de bugs (02/07/2026): encoding corrompido em executar_comando/abrir_app (PowerShell OEM vs UTF-8), keyring apagando chaves não-conhecidas do .env, race condition em /chat misturando respostas entre requisições concorrentes, modelo Gemini inexistente em analisar_clipboard_com_ia, falha silenciosa do Gemini Vision em explicar_tela.",
        "Bug de regressão: Groq rejeitava mensagens com campos extras (fontes_rag/divergencia_draft) — sanitização de mensagens antes de enviar à API.",
    ]:
        d.bullet(None, txt, status="ok")
    d.gap(4)

    d.subsection("Pendentes / Melhorias futuras")
    for txt in [
        "[MÉDIA] Migrar frontend Three.js para WebGPURenderer (r171+).",
        "[BAIXA] Separar validação do RAG por categoria (episodio vs conhecimento_geral) no validador_cortical.py.",
        "[BAIXA] Avaliar estado input-required do A2A para sub-agentes que precisam perguntar ao Antônio.",
        "Tarefas manuais pendentes (ver instrucoes.md): Telegram bot, Google OAuth, Screenpipe, atualizar SurrealDB via winget, registrar MCP em ~/.claude/settings.json.",
        "Validar Voz Live ponta a ponta com microfone físico real.",
        "Confirmar visualmente sparkline histórico #t-hist-spark no painel lateral.",
    ]:
        d.bullet(None, txt, status="wip")

    # ════════════════════════════════════════════════════════════════
    d.section("3. Referência da API HTTP (cerebro_maestro.py :8000)")
    d.para("28 endpoints. Endpoints principais cobertos por test_smoke.py (17 checagens). Atualizado 02/07/2026.", cor=(0.4706, 0.5098, 0.5882), size=8)
    d.gap(4)
    d.table(
        ["Método", "Rota", "Descrição"],
        [
            ["GET", "/", "Ping — {servico, ativo, versao}"],
            ["GET", "/dashboard", "Dashboard HTML standalone"],
            ["GET", "/status", "Estado (cerebro_ativo, qdrant, embedder, tts_mudo, carga_cognitiva)"],
            ["GET", "/health", "Latência real Qdrant/SurrealDB/Ollama + VRAM + contagem"],
            ["GET", "/metrics", "CPU/RAM (psutil) + GPU/VRAM% (nvidia-smi, cache 4s)"],
            ["GET", "/stats", "Telemetria cascata: usos/falhas/latência/% por andar"],
            ["GET", "/stats/historico", "Snapshots históricos de cascata (telemetria_historico.jsonl)"],
            ["POST", "/chat", "Chat principal SSE streaming. Body: {texto, modelo}"],
            ["GET", "/buscar", "Busca híbrida BM25+BGE-M3+RRF+freshness+reranker"],
            ["GET", "/grafo", "Traversal de grafo SurrealDB por keywords"],
            ["GET", "/grafo/completo", "Grafo completo para o visualizador 3D"],
            ["GET", "/memoria/categorias", "Composição da base por categoria (Qdrant)"],
            ["GET", "/historico", "Histórico em memória (inclui fontes_rag/divergencia_draft)"],
            ["DELETE", "/historico", "Limpa histórico em memória (não afeta SurrealDB/Qdrant)"],
            ["GET", "/resumo_sessao", "Briefing + histórico (preview)"],
            ["GET", "/exportar", "Exporta sessão como markdown"],
            ["POST", "/tts/mudo", "Liga/desliga voz global. Body: {mudo: bool}"],
            ["POST", "/tts/falar", "Dispara TTS para texto arbitrário. Body: {texto}"],
            ["POST", "/upload", "Upload de imagem/áudio do chat"],
            ["POST", "/enxame", "Cria enxame de sub-agentes"],
            ["GET", "/enxames", "Lista enxames recentes"],
            ["GET", "/enxame/{id}", "Status do enxame + subtarefas"],
            ["POST", "/enxame/{id}/consolidar", "Consolida resultados via LLM"],
            ["POST", "/agente", "Loop ReAct autônomo. Body: {objetivo, max_iteracoes}"],
            ["GET", "/agente/runs", "Lista execuções recentes de agente_run"],
            ["POST", "/shadow_thoughts", "Dispara ciclo Shadow Thoughts em background"],
            ["WS", "/ws/voice", "Voice Live bidirecional (Gemini Live API)"],
            ["GET/POST", "/mcp", "Todos os endpoints acima como ferramentas MCP"],
        ],
        [45, 100, 380],
        size=7.6, leading=10.5,
    )

    d.section("4. Hybrid RAG — Arquitetura")
    d.para("Query → [BM25 esparso (bm25s)] + [Dense vetorial (BGE-M3)] → merge (RRF) → bge-reranker-v2-m3 → freshness → top-K → LLM")
    d.gap(4)
    d.bullet("BM25 (bm25s):", "~382ms sobre 3.08M docs (era 2.1s com rank_bm25). Acerta nomes próprios/siglas/código exato.")
    d.bullet("Dense (BGE-M3):", "1024 dims, normalizado, GPU via embed_service :8001. Acerta semântica/sinonímia.")
    d.bullet("RRF:", "Reciprocal Rank Fusion — combina listas sem ajuste de escala.")
    d.bullet("Reranker (bge-reranker-v2-m3):", "cross-encoder 3º estágio.")
    d.bullet("Score final:", "relevancia*0.94 + freshness_factor*0.06. Ebbinghaus decay REMOVIDO (01/07/2026); freshness é seletivo por categoria (código 180d, wiki 3650d, matemática/episódio sem penalidade).")
    d.gap(6)

    d.section("5. Módulo de Expansão & Modo Construção")
    d.subsection("Validador Cortical de RAG (validador_cortical.py)")
    d.para("Gera perguntas sintéticas a partir de registros aleatórios do Db_CORTEX e mede Hit Rate (top-K) e MRR. Política de rollback: HR_Min 85% | MRR_Min 0.68.")
    d.gap(4)
    d.subsection("Task-Aware Budgeting")
    d.para("Detecta transição de domínio (chat casual → debug técnico) e resume (não descarta) mensagens de baixa densidade técnica.")
    d.gap(4)
    d.subsection("Modo Construção — chaveamento de modelos")
    d.table(
        ["", "Modo Chat", "Modo Construção"],
        [
            ["Modelo", "Cascata cloud ou qwen3:8b", "Qwen3.6 27B / DeepSeek-R1 32B distilled"],
            ["Hardware", "8GB VRAM", "64GB RAM (GPU offload via LM Studio)"],
            ["Vazão", ">40 tok/s", "5-10 tok/s"],
        ],
        [75, 200, 250],
    )

    # ════════════════════════════════════════════════════════════════
    d.section("6. Datasets Ingeridos")
    d.para("Schema: { titulo, texto (max 3000), fonte, categoria }. Script: Scripts_Ingestao/pipeline_noturno.sh", cor=(0.4706, 0.5098, 0.5882), size=8)
    d.gap(4)
    d.table(
        ["Tabela", "Dataset", "Conteúdo"],
        [
            ["wiki_conhecimento", "wikimedia/wikipedia 20231101.pt", "1.112.246 artigos PT-BR"],
            ["base_codigo", "nickrosh/Evol-Instruct-Code-80k-v1", "80k pares instrução/código"],
            ["base_codigo", "iamtarun/code_instructions_120k_alpaca", "120k instruções Python"],
            ["base_codigo", "sahil2801/CodeAlpaca-20k", "20k instruções código geral"],
            ["base_codigo", "iamtarun/python_code_instructions_18k_alpaca", "18k Python específico"],
            ["base_instrucoes_ptbr", "dominguesm/Canarim-Instruct-PTBR-Dataset", "316k instruções PT-BR nativo"],
            ["base_instrucoes_ptbr", "CohereLabs/aya_dataset (por=por)", "Instruções PT-BR curadas"],
            ["base_raciocinio", "openai/gsm8k", "8.5k problemas matemáticos CoT"],
            ["base_raciocinio", "meta-math/MetaMathQA", "395k QA matemático passo a passo"],
            ["base_conversas", "teknium/OpenHermes-2.5", "~1M conversas alta qualidade (GPT-4)"],
            ["base_conhecimento_qa", "piEsposito/br-quad-2.0", "SQuAD 2.0 traduzido PT-BR"],
            ["base_conhecimento_qa", "eraldoluis/faquad", "QA nativo PT-BR (ensino superior)"],
            ["base_medicina_ptbr", "AKCIT/MedPT", "384.095 pares Q&A médicas PT-BR"],
        ],
        [110, 210, 205],
        size=7.6, leading=10.5,
    )

    d.section("7. Melhores LLMs Locais (referência 2026)")
    d.table(
        ["Modelo", "Uso", "Notas"],
        [
            ["qwen3:8b", "Fallback local atual da Lyra", "Cascata cloud vai na frente"],
            ["qwen3:0.6b", "Draft sidecar (spec decoding)", "Detecção de divergência semântica"],
            ["Groq gpt-oss-120b", "1º andar cascata cloud", "Free tier"],
            ["Gemini 3.5-flash", "2º andar cascata cloud", "Free tier"],
            ["Claude Sonnet (via Claude Code)", "3º andar — delegação completa", "Full agent, ferramentas nativas"],
            ["Qwen3.6 27B", "Candidato Modo Construção", "Via RAM offload (64GB)"],
            ["DeepSeek-R1 distilado 7B", "Raciocínio chain-of-thought local", "~5-10 tok/s"],
        ],
        [140, 190, 195],
    )
    d.gap(6)

    d.section("8. Modelos de Embedding")
    d.table(
        ["Modelo", "Dims", "Status"],
        [
            ["BAAI/bge-m3", "1024", "EM USO — lyra_memory_v2, GPU via embed_service :8001"],
            ["bge-reranker-v2-m3", "—", "EM USO — cross-encoder reranker, 3º estágio do RAG"],
            ["paraphrase-multilingual-MiniLM-L12-v2", "384", "APOSENTADO — lyra_memory v1 apagada"],
            ["jina-embeddings-v3", "1024", "Referência — melhor qualidade multilingual"],
            ["nomic-embed-text-v1.5", "768", "Referência — excelente PT-BR local"],
        ],
        [230, 55, 240],
        size=7.8,
    )

    d.section("9. VLMs em 8GB")
    d.table(
        ["Modelo", "VRAM", "Status"],
        [
            ["Gemini Vision (gemini-2.5-flash)", "Cloud", "Primário — explicar_tela() e analisar_imagem()"],
            ["llava-phi3", "~2.9GB", "Fallback local via Ollama"],
            ["SmolVLM 2B", "~1.5GB", "Alternativa local rápida"],
            ["MiniCPM-V 2.6", "~5.5GB", "Melhor qualidade, concorre com LLM principal"],
        ],
        [230, 70, 225],
    )
    d.gap(6)

    d.section("10. Geração de Imagem/Vídeo/Áudio")
    d.bullet("Imagem:", "Pollinations.ai (gratuito, sem key, Flux) — em uso via gerar_imagem(). ComfyUI + SD 1.5 (~2GB VRAM) como alternativa local.")
    d.bullet("Vídeo:", "LTX-2 OPTIMIZED (único viável em 8GB, FP8, 2-5s de vídeo em 60-90s). NÃO roda simultâneo com o LLM.")
    d.bullet("Áudio/Música:", "MusicGen Small (~1GB VRAM), AudioLDM2 (~2GB).")

    # ════════════════════════════════════════════════════════════════
    d.section("11. Sessão 02/07/2026 — Itens Implementados")
    d.subsection("Câmara de Eco Heurística — bloqueio de ações de risco")
    d.para("lyra_seguranca.avaliar_risco_acao() avalia executar_comando/iniciar_processo_bg/escrever_arquivo/organizar_pasta. Hash SHA256 determinístico liga uma confirmação à ação exata; só aceita no turno IMEDIATAMENTE seguinte ao bloqueio (contador monotônico, imune a truncamento de histórico). Validado ao vivo: Stop-Process bloqueado, 'sim, executa mesmo assim' libera, erro benigno reportado corretamente.")
    d.gap(4)
    d.subsection("Speculative Decoding — sidecar de detecção de divergência")
    d.para("Draft qwen3:0.6b roda em paralelo à cascata principal (só quando não precisa tools). divergencia_draft = 1 - cosseno(vetor_final, vetor_draft) via BGE-M3. Limiar 0.45 só loga, não bloqueia. Limitação conhecida: mede similaridade de tópico/estrutura, não correção factual (teste manual com resposta errada mas mesma estrutura deu divergência baixa).")
    d.gap(4)
    d.subsection("MoE roteado — ESPECIALISTAS")
    d.para("Lista declarativa formaliza o roteamento condicional que já existia (código→Claude primeiro, geral→Groq primeiro). Ganho estrutural: adicionar especialista novo é uma entrada na lista, não editar if/else espalhado.")
    d.gap(4)
    d.subsection("navegar_web (browser-use) corrigido de ponta a ponta")
    d.para("3 problemas em cadeia: Chromium nunca instalado; API do browser-use migrou pra abstração própria (ChatGoogle em vez de langchain ChatGoogleGenerativeAI); modelo gemini-2.0-flash com quota zero, trocado por gemini-2.5-flash. Validado ao vivo — ciclo completo funcional.")
    d.gap(4)
    d.subsection("Auditoria geral de bugs — 3 sub-agentes em paralelo")
    d.para("6 bugs reais corrigidos: modelo Gemini inexistente em analisar_clipboard_com_ia; falha silenciosa do Gemini Vision em explicar_tela; encoding corrompido em executar_comando/abrir_app (PowerShell OEM vs UTF-8); migrar_chaves_para_keyring apagava chaves não-conhecidas do .env (risco: TELEGRAM_ALLOWED_USERS sumindo abre o bot pra qualquer usuário); race condition em /chat podia misturar respostas entre requisições concorrentes. test_smoke.py 17/17 após todas as correções.")

    # ════════════════════════════════════════════════════════════════
    d.title("LYRA — AGENTES PARALELOS E PLANOS", "> Consolidado em 25/06/2026. Atualizado em 02/07/2026.")

    d.section("1. Enxame de Sub-Agentes (lyra_agentes.py) — IMPLEMENTADO")
    d.para("Implementado em 26/06/2026. Status: produção.")
    d.gap(4)
    d.bullet(None, "Dispara N sub-tarefas em paralelo via asyncio.Semaphore(max_paralelo=2).")
    d.bullet(None, "Cada sub-tarefa usa cascata Groq→Gemini isolada com tool-calling real.")
    d.bullet(None, "Persistência em SurrealDB (tabelas enxame + subtarefa).")
    d.bullet(None, "Toolset: denylist (não allowlist) — bloqueia só destrutivo/recursivo/auto-modificante.")
    d.bullet(None, "Endpoints: POST /enxame, GET /enxame/{id}, POST /enxame/{id}/consolidar, GET /enxames.")
    d.bullet(None, "Ferramentas em lyra_tools: criar_enxame, status_enxame, consolidar_enxame.")
    d.bullet(None, "loop_proativo detecta enxames concluídos e notifica automaticamente.")
    d.gap(6)

    d.section("2. lyra_agent.py (loop ReAct) — IMPLEMENTADO")
    d.para("Implementado em 30/06/2026. Integrado ao backend em 01/07/2026. _rodar_local validado ao vivo em 02/07/2026.")
    d.gap(4)
    d.bullet(None, "Loop ReAct standalone autônomo — separado do chat.")
    d.bullet(None, "executar_agente_async(objetivo, max_iteracoes) — API pública assíncrona.")
    d.bullet(None, "Cascata Groq→Gemini→local (mesmo padrão do cerebro_maestro, sem streaming).")
    d.bullet(None, "Persiste em SurrealDB tabela agente_run: objetivo, iteracoes, passos, resposta_final, sucesso.")
    d.bullet(None, "TOOLS_BLOQUEADAS_PADRAO: bloqueia destrutivo/recursivo/auto-modificante.")
    d.bullet(None, "self_test() valida 3 casos: aritmética sem tool, busca com tool, tool inexistente. 3/3.", status="ok")
    d.bullet(None, "_rodar_local validado ao vivo: 3/3 casos passaram via Ollama local direto, confirma loop ReAct igual nos 3 andares.", status="ok")
    d.bullet(None, "Endpoint POST /agente + GET /agente/runs no cerebro_maestro.py.")
    d.gap(6)

    d.section("3. Shadow Thoughts (lyra_shadow_thoughts.py) — IMPLEMENTADO")
    d.table(
        ["Fase", "O que faz", "Quando roda"],
        [
            ["NREM", "Dedup semântico (cosseno > 0.95), marca duplicado=True", "A cada ciclo (~3h)"],
            ["REM", "Arestas 'conecta' cross-domain entre tópicos co-ocorrentes", "A cada ciclo (~3h)"],
            ["DEEP", "Comprime eventos >4 semanas em resumos semanais", "A cada ciclo (~3h)"],
        ],
        [55, 335, 130],
    )
    d.gap(4)
    d.bullet(None, "Disparado automaticamente a cada 180 iterações do loop_proativo (~3h).")
    d.bullet(None, "Endpoint POST /shadow_thoughts para disparo manual (fases=nrem,rem,deep).")
    d.bullet(None, "Segurança: NREM não deleta — só marca. REM usa RELATE upsert. DEEP cria resumo e marca comprimido=True.")
    d.gap(6)

    d.section("4. Backlog Pendente")
    d.table(
        ["Prioridade", "Item", "Notas"],
        [
            ["ALTA", "Telegram bot (@BotFather + .env TELEGRAM_BOT_TOKEN)", "instrucoes.md item pendente"],
            ["ALTA", "Google OAuth (Gmail + Calendar)", "lyra_google_workspace.py"],
            ["ALTA", "Registrar MCP: ~/.claude/settings.json → url http://127.0.0.1:8000/mcp", "Conecta Claude Code à Lyra"],
            ["MÉDIA", "npm install -g @screenpipe/cli", "Total Recall — OCR contínuo"],
            ["MÉDIA", "SurrealDB update via winget", "Versão mais recente"],
            ["MÉDIA", "Migrar frontend Three.js → WebGPURenderer (r171+)", "Performance gráfica"],
            ["BAIXA", "Validar Voice Live com microfone físico real", "End-to-end áudio"],
            ["BAIXA", "Confirmar sparkline #t-hist-spark no painel lateral", "Visual"],
            ["BAIXA", "Estado input-required para sub-agentes (ideia do A2A)", "v2 do enxame"],
            ["FUTURA", "Emotion Engine (paralinguística)", "Fase 4"],
            ["FUTURA", "Wi-Fi Sensing via ESP32 (802.11bf)", "Fase 4"],
            ["FUTURA", "Protocolo Darwin (auto-reescrita supervisionada)", "Fase 5"],
        ],
        [55, 330, 135],
        size=7.6, leading=10.5,
    )
    d.gap(6)

    d.section("5. Pesquisas Técnicas Realizadas")
    d.bullet(None, "SurrealDB 3.0 vs Qdrant para vector search: NÃO migrar agora — ~15-20GB RAM, esforço alto, Qdrant já estável (~382ms). Revisar quando Qdrant mostrar dor real.")
    d.bullet(None, "Mem0 / Kore para decay de memória: Kore confirma abordagem atual (Freshness Tags seletivo). Mem0 foca resolução de conflitos, não decay. Manter implementação atual.")
    d.bullet(None, "Protocolo A2A (Agent-to-Agent): NÃO adotar — resolve interop entre fornecedores diferentes, problema que a Lyra não tem. Ideias aproveitadas: ciclo de vida rico + Agent Cards, base pra lista ESPECIALISTAS.")
    d.bullet(None, "Baseline RAG (calibrar_pesos_rag.py): diferença entre pesos não significativa (n=40). Decay removido — score = relevância pura + freshness seletivo.")
    d.gap(10)

    d.para(
        "Gerado em 02/07/2026 a partir de LYRA_NUCLEO.md + LYRA_TECNICO.md + LYRA_AGENTES_E_PLANOS.md.",
        cor=(0.4706, 0.5098, 0.5882), size=7.5,
    )

    d.finish()
    print(f"OK: {OUT}")


if __name__ == "__main__":
    build()
