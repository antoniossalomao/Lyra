"""
routers/chat.py — o endpoint mais crítico do sistema: `/chat` (cascata de
modelos com streaming SSE, RAG híbrido, Câmara de Eco Heurística,
Speculative Decoding, roteador de especialistas) + `/tts/mudo` e
`/tts/falar` (controle de voz, pequenos e de baixo risco, mantidos junto por
proximidade lógica).

Extraído de cerebro_maestro.py na reorganização OOP (Lyra 2.0) — última peça
da Fase 1, deixada por último de propósito: é o código com mais estado
mutável entrelaçado do projeto inteiro (várias das notas abaixo documentam
bugs de produção já corrigidos aqui — race condition de sessão concorrente,
vazamento de latência por keep_alive errado, etc). A extração é MECÂNICA —
toda linha de lógica é idêntica ao original, só move de função solta pra
método de classe, trocando `global X` por `self._get_x()`/`self._set_x()`
(estado que cerebro_maestro.py continua dono, porque outros routers também
leem, ex: `_tts_mudo` e `_ultima_latencia_ms` são lidos por SystemRouter) ou
por atributo direto (estado só usado aqui). Verificado por compile+import,
igual todo outro router — a correção do FLUXO (Groq/Gemini/Claude/local
respondendo de verdade) só se prova rodando o processo de verdade, o que já
era true pra `MemoryRouter.grafo_completo` e outros que também dependem de
serviço externo no ar.
"""
import asyncio
import datetime
import json
import re
import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

import config as cfg
from models.chat import MensagemUsuario


class ChatRouter:
    def __init__(self, *, log, session, rag, get_cerebro_ativo, top_k_ajustado,
                 classificar_intencao, sem_acento, registrar_evento, rotear_especialista,
                 tool_keywords_re, tools_schema, tools_desabilitadas, rodar_draft, mapa_tiers,
                 primeiro_chunk_ou_falha, registrar_tier, embed, cosine_sim,
                 limiar_divergencia_alucinacao, get_ultima_acao_bloqueada,
                 confirmacoes_risco, lock_risco, get_tts_mudo, set_tts_mudo,
                 set_ultima_latencia_ms, telemetria, audio_manager):
        self._log = log
        self._session = session
        self._rag = rag
        self._get_cerebro_ativo = get_cerebro_ativo
        self._top_k_ajustado = top_k_ajustado
        self._classificar_intencao = classificar_intencao
        self._sem_acento = sem_acento
        self._registrar_evento = registrar_evento
        self._rotear_especialista = rotear_especialista
        self._tool_keywords_re = tool_keywords_re
        self._tools_schema = tools_schema
        self._tools_desabilitadas = tools_desabilitadas
        self._rodar_draft = rodar_draft
        self._mapa_tiers = mapa_tiers
        self._primeiro_chunk_ou_falha = primeiro_chunk_ou_falha
        self._registrar_tier = registrar_tier
        self._embed = embed
        self._cosine_sim = cosine_sim
        self._limiar_divergencia_alucinacao = limiar_divergencia_alucinacao
        self._get_ultima_acao_bloqueada = get_ultima_acao_bloqueada
        self._confirmacoes_risco = confirmacoes_risco
        self._lock_risco = lock_risco
        self._get_tts_mudo = get_tts_mudo
        self._set_tts_mudo = set_tts_mudo
        self._set_ultima_latencia_ms = set_ultima_latencia_ms
        self._telemetria = telemetria
        self._audio_manager = audio_manager

        self.router = APIRouter()
        self.router.add_api_route("/chat", self.chat_endpoint, methods=["POST"])
        self.router.add_api_route("/tts/mudo", self.definir_tts_mudo, methods=["POST"])
        self.router.add_api_route("/tts/falar", self.tts_falar, methods=["POST"])

    async def chat_endpoint(self, msg: MensagemUsuario):
        _t0_req = time.monotonic()

        # Espera o startup terminar de restaurar sessão/briefing — sem isso, um
        # /chat nos primeiros segundos corria com sessão None e histórico vazio.
        await self._session.wait_ready()

        _, tamanho_hist = await self._session.append_user(msg.texto)

        # Registra a fala do usuário com classificação de intenção (Innovation 1)
        asyncio.create_task(self._registrar_evento(
            fonte="chat", ator="Antônio", texto=msg.texto,
            intencao=self._classificar_intencao("Antônio", msg.texto)))

        if tamanho_hist > cfg.MAX_HISTORY_MSGS:
            asyncio.create_task(self._session.compress_if_needed())

        contexto_str = ""
        # Sem acento — matching de keyword não pode depender do usuário digitar
        # certinho ("saude" vs "saúde"), já causou a Lyra inventar CPU/RAM em vez
        # de chamar a ferramenta porque "saude" sem acento não casava com "saúde".
        msg_lower = self._sem_acento(msg.texto.lower())

        # Detecta se é pergunta sobre memória/histórico pessoal (controla top_k maior)
        keywords_memoria = [self._sem_acento(k) for k in ["lembra", "quando", "qual foi", "primeira pergunta",
                            "quantas vezes", "me perguntei", "você já", "há quanto tempo",
                            "ontem", "semana passada"]]
        eh_pergunta_memoria = any(kw in msg_lower for kw in keywords_memoria)

        # Detecta pergunta factual genérica (não só memória pessoal) — a base wiki_
        # conhecimento foi ingerida exatamente pra isso: a Lyra deve CONSULTAR a
        # memória em vez de confiar só no conhecimento interno do modelo pequeno
        # (que erra/recusa fatos triviais) ou inventar. Só pula RAG em conversa
        # puramente casual (sem "?" nem palavra interrogativa) — mas saudações tipo
        # "tudo bem?"/"como vai?" têm "?" sem ser pergunta de conhecimento, então
        # essas ficam de fora mesmo com "?" pra não pagar o custo do RAG à toa.
        saudacoes_casuais = [self._sem_acento(s) for s in ["tudo bem", "como vai", "como você está",
                             "e aí", "oi,", "olá,", "bom dia", "boa tarde",
                             "boa noite", "tudo certo", "tudo joia", "suave"]]
        eh_saudacao_casual = any(s in msg_lower for s in saudacoes_casuais) and len(msg.texto) < 40
        palavras_interrogativas = [self._sem_acento(p) for p in ["qual", "quem", "quando", "onde", "como",
                                   "por que", "porque", "quanto", "quantos", "quantas", "o que",
                                   "que é", "quais"]]
        eh_pergunta_factual = (not eh_saudacao_casual) and (
            "?" in msg.texto or any(p in msg_lower for p in palavras_interrogativas))

        # A busca híbrida (BM25 + vetorial sobre ~2,2M registros) custa 5-10s sozinha
        # — inaceitável rodar em toda mensagem casual ("oi", "tudo bem?"). Mas pular
        # ela inteira fazia a Lyra recusar/errar fatos triviais que estão na wiki
        # ingerida — então só pula mesmo em conversa casual, não em perguntas.
        ids_rag: list[str] = []  # IDs Qdrant usados no RAG desta mensagem (Innovation 5)
        if self._get_cerebro_ativo() and self._rag.active and (eh_pergunta_memoria or eh_pergunta_factual):
            try:
                # to_thread: _rag.search é síncrona (httpx.post bloqueante em embed/
                # rerank + BM25 em CPU) — sem isso, travava o event loop inteiro do
                # uvicorn por 5-10s, inclusive /health e o WS de voz.
                # top_k ajustado dinamicamente pela carga cognitiva (Innovation 4)
                resultados = await asyncio.to_thread(self._rag.search, msg.texto, top_k=self._top_k_ajustado(5))
                ids_rag = [str(r.get("id", "")) for r in resultados if r.get("id")]

                # Atualiza last_accessed_at e retrieval_count nos vetores recuperados
                asyncio.create_task(self._rag.update_access(resultados))

                # Filtro de episódio + formatação + suplemento de grafo vivem em
                # RAGEngine.build_context — ver docstring lá pro racional.
                contexto_str = await self._rag.build_context(msg.texto, resultados, eh_pergunta_memoria)
            except Exception as e:
                self._log(f"[FALHA RAG] {e}")

        # Snapshot sanitizado (role/content só) — metadados extras fazem o Groq
        # rejeitar a request com 400 "unsupported property".
        mensagens = await self._session.sanitized_messages()

        # Prepara o contexto de realidade (Data/Hora) para evitar alucinações temporais
        agora = datetime.datetime.now()
        dia_semana = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"][agora.weekday()]
        data_hora_str = f"[SISTEMA] Hoje é {dia_semana}, {agora.strftime('%d/%m/%Y as %H:%M')}."

        # Exceção consciente à Diretiva Nº 2 (decidida com Antônio em 24/06/2026):
        # se o usuário pedir explicitamente pra usar o Claude, a aprovação já está
        # dada nessa mesma mensagem — não precisa o modelo perguntar de novo.
        _KEYWORDS_CLOUD_APROVADO = ["faça isso com o claude", "faz isso com o claude",
                                    "usa o claude", "use o claude", "chama o claude",
                                    "chame o claude", "pede ajuda pro claude",
                                    "peça ajuda pro claude", "manda pro claude",
                                    "envia pro claude", "pede pro claude"]
        eh_aprovacao_cloud_explicita = any(self._sem_acento(kw) in msg_lower for kw in _KEYWORDS_CLOUD_APROVADO)

        # Câmara de Eco Heurística (02/07/2026) — confirmação explícita de uma ação
        # de alto risco bloqueada por _executar_tool_segura(). Frases pareadas com
        # verbo de ação (não "sim"/"confirmo" soltos) — reduz colisão com confirmações
        # de outro assunto (ex: confirmar um compromisso de calendário). Duas travas
        # combinadas: só aprova a ação EXATA que está pendente (_ultima_acao_bloqueada,
        # nunca uma diferente) e só no turno IMEDIATAMENTE seguinte ao bloqueio
        # (índice de historico_recente igual ao registrado no momento do bloqueio) —
        # a janela de 10min sozinha não bastaria pra evitar aprovação fora de contexto.
        _KEYWORDS_RISCO_APROVADO = [self._sem_acento(k) for k in [
            "confirmo, pode executar", "confirmo, executa", "sim, executa mesmo assim",
            "sim, pode executar", "autorizo, pode fazer", "autorizo a executar",
            "pode continuar mesmo assim", "manda ver, confirmado", "pode fazer mesmo assim",
            "executa mesmo assim", "confirmado, pode rodar"]]
        eh_aprovacao_risco_explicita = False
        aviso_risco_str = ""
        _ultima_acao_bloqueada = self._get_ultima_acao_bloqueada()
        if _ultima_acao_bloqueada is not None:
            dentro_da_janela = (time.time() - _ultima_acao_bloqueada["ts"]) < 600  # 10min
            eh_proximo_turno = self._session.turn_counter == _ultima_acao_bloqueada["turno_bloqueio"] + 1
            if dentro_da_janela and eh_proximo_turno and any(kw in msg_lower for kw in _KEYWORDS_RISCO_APROVADO):
                eh_aprovacao_risco_explicita = True
                _h = _ultima_acao_bloqueada["hash"]
                with self._lock_risco:
                    self._confirmacoes_risco[_h] = time.time()
                aviso_risco_str = (f"\n\n[SISTEMA] O usuário confirmou explicitamente a ação de risco pendente "
                                   f"({_ultima_acao_bloqueada['nome']}: {_ultima_acao_bloqueada['motivo']}). "
                                   f"Chame a MESMA ferramenta de novo com os MESMOS parâmetros de antes.")

        if len(mensagens) > 0:
            # Bug real corrigido 02/07/2026: usar mensagens[-1]["content"] assume
            # que a última entrada de historico_recente É a mensagem desta
            # requisição — mas entre o append do usuário e aqui, o código faz
            # vários await (RAG híbrido, grafo SurrealDB), cedendo o event loop.
            # Se uma segunda requisição /chat concorrente também der append nesse
            # intervalo, mensagens[-1] pode ser a pergunta de OUTRA requisição,
            # não a desta — a resposta sai contaminada/trocada entre sessões
            # concorrentes. msg.texto é local a esta requisição, imune a
            # mutação concorrente — sempre a fonte correta.
            ultima_msg = msg.texto
            aviso_cloud_str = ""
            if eh_aprovacao_cloud_explicita:
                aviso_cloud_str = ("\n\n[SISTEMA] O usuário autorizou explicitamente o uso do Claude "
                                   "(nuvem) nesta mensagem. Chame consultar_especialista com "
                                   "nivel='cloud' e aprovado=True diretamente, sem perguntar de novo.")
            aviso_cloud_str += aviso_risco_str
            if contexto_str:
                # A instrução rígida de "diga que não tem registro" só faz sentido
                # quando a pergunta É sobre memória — caso contrário, qualquer match
                # fraco/irrelevante do RAG fazia a Lyra recusar conversa casual
                # ("oi, tudo bem?") tratando-a como pergunta de memória sem resposta.
                if eh_pergunta_memoria:
                    aviso_bloco = f"\n\n[AVISO CRÍTICO]\n- Use timestamps das memórias acima (NUNCA invente datas)\n- Se não encontrar, diga: 'Não tenho registro disso'{aviso_cloud_str}"
                else:
                    aviso_bloco = aviso_cloud_str
                mensagens[-1] = {
                    "role": "user",
                    "content": f"{data_hora_str}\n\n[MEMÓRIAS DO CÉREBRO]\n{contexto_str}{aviso_bloco}\n\nUsuário: {ultima_msg}"
                }
            else:
                mensagens[-1] = {
                    "role": "user",
                    "content": f"{data_hora_str}{aviso_cloud_str}\n\nUsuário: {ultima_msg}"
                }

        # Roteador de Intenção — ativa ferramentas só com keyword no início de palavra
        # (regex \b, compilada em tool_keywords_re). Evita falsos positivos.
        # Filtra por tools_desabilitadas (toggle do painel MCP, seção 9 item 5) —
        # lido a cada request porque o usuário pode ligar/desligar a qualquer momento.
        tools_habilitadas = [
            t for t in self._tools_schema
            if t.get("type") != "function" or t["function"]["name"] not in self._tools_desabilitadas
        ] or None  # lista vazia (usuário desligou tudo) equivale a "sem ferramentas", não [] —
                    # alguns provedores tratam [] como erro de schema, não como "sem tools".
        precisa_tools = bool(self._tool_keywords_re.search(msg_lower))
        ferramentas = tools_habilitadas if precisa_tools else None
        if eh_aprovacao_cloud_explicita:
            precisa_tools = True
            ferramentas = tools_habilitadas
        if eh_aprovacao_risco_explicita:
            precisa_tools = True
            ferramentas = tools_habilitadas

        # Enxame de Especialistas (MoE roteado) — proposta formalizada em
        # LYRA_TECNICO.md 10.9, implementada em 02/07/2026. Cada especialista
        # tem categoria + trigger + ordem de andares. Adicionar um especialista
        # novo = uma entrada na lista (ver ESPECIALISTAS em cerebro_maestro.py),
        # não editar lógica de roteamento espalhada.
        especialista = self._rotear_especialista(msg_lower, msg.texto)

        stream = self._construir_stream(msg, mensagens, precisa_tools, ferramentas,
                                        especialista, ids_rag, _t0_req)
        return StreamingResponse(stream(), media_type="text/event-stream")

    def _construir_stream(self, msg, mensagens, precisa_tools, ferramentas,
                          especialista, ids_rag, _t0_req):
        async def stream():
            resposta_completa = ""
            tier_usado = None

            # Speculative Decoding (Fase 3) — dispara o draft (qwen3:0.6b) já aqui,
            # em paralelo com a cascata principal, pra não somar latência. Só faz
            # sentido comparar quando a resposta é texto puro: se ferramentas forem
            # chamadas, o andar principal vê dados que o draft nunca vê (clima,
            # hora, resultado de busca) — divergência ali seria falso-positivo.
            draft_task = asyncio.create_task(self._rodar_draft(list(mensagens))) if not precisa_tools else None

            if msg.modelo in self._mapa_tiers:
                # Seletor manual do painel — só esse andar, sem fallback (o
                # usuário escolheu de propósito, melhor falhar visivelmente do
                # que cair pra outro modelo escondido).
                andares = [self._mapa_tiers[msg.modelo]]
            else:
                andares = [self._mapa_tiers[nome] for nome in especialista["andares"]]

            for nome_tier, gerador_fn in andares:
                try:
                    gerador = gerador_fn(list(mensagens), ferramentas)
                    gerador_pronto = await self._primeiro_chunk_ou_falha(gerador)
                except StopAsyncIteration:
                    self._log(f"[CASCATA] {nome_tier} retornou vazio — tentando próximo andar.")
                    self._registrar_tier(nome_tier, falhou=True)
                    continue
                except Exception as e:
                    self._log(f"[CASCATA] {nome_tier} falhou: {e}")
                    self._registrar_tier(nome_tier, falhou=True)
                    continue

                tier_usado = nome_tier
                # Manda a fonte como campo estruturado ("tier"), não como texto
                # no meio da resposta — o frontend mostra isso discreto no painel
                # lateral em vez de no balão de chat (pedido do usuário).
                yield f"data: {json.dumps({'tier': nome_tier})}\n\n"
                if nome_tier == "Local":
                    self._log("[CASCATA] Todas as APIs de nuvem falharam — usando qwen3:8b local.")

                try:
                    async for chunk in gerador_pronto:
                        yield f"data: {json.dumps({'text': chunk})}\n\n"
                        resposta_completa += chunk
                except Exception as e:
                    self._log(f"[CASCATA] {nome_tier} falhou no meio do stream: {e}")
                    yield f"data: {json.dumps({'text': chr(10) + '_(conexao interrompida)_'})}\n\n"
                break  # comprometido com esse andar (sucesso ou falha no meio) -- nao tenta outro

            if tier_usado is None:
                self._log("[CASCATA] Todos os 4 andares falharam.")
                if draft_task is not None:
                    draft_task.cancel()
                yield f"data: {json.dumps({'text': 'Todas as fontes de resposta falharam (Groq, Gemini, Claude e o modelo local). Tente novamente em alguns segundos.'})}\n\n"
                yield "data: [DONE]\n\n"
                return

            # Speculative Decoding: compara a resposta final com o draft (se deu
            # tempo de terminar). Divergência alta = log de alerta, não bloqueia
            # nem altera a resposta — é só um sinal de possível alucinação.
            divergencia_draft = None
            if draft_task is not None and resposta_completa:
                try:
                    draft_texto = await asyncio.wait_for(draft_task, timeout=8)
                except Exception:
                    draft_texto = None
                if draft_texto:
                    try:
                        vetor_final, vetor_draft = await asyncio.gather(
                            asyncio.to_thread(self._embed, resposta_completa.strip()),
                            asyncio.to_thread(self._embed, draft_texto),
                        )
                        if vetor_final and vetor_draft:
                            divergencia_draft = round(1 - self._cosine_sim(vetor_final, vetor_draft), 4)
                            if divergencia_draft > self._limiar_divergencia_alucinacao:
                                self._log(f"[SPEC-DECODE] divergência alta ({divergencia_draft}) entre {tier_usado} "
                                    f"e draft qwen3:0.6b — possível alucinação. Draft: {draft_texto[:150]!r}")
                    except Exception as e:
                        self._log(f"[SPEC-DECODE] falha ao comparar draft: {e}")
            elif draft_task is not None:
                draft_task.cancel()

            if resposta_completa:
                resposta_limpa = resposta_completa.strip()
                await self._session.append_assistant(resposta_limpa,
                                                fontes_rag=ids_rag or None,  # Innovation 5
                                                divergencia_draft=divergencia_draft)
                asyncio.create_task(self._registrar_evento(fonte="chat", ator="Lyra", texto=resposta_limpa,
                                                      fontes_rag=ids_rag or None,
                                                      divergencia_draft=divergencia_draft))

                # Filtra blocos de codigo e fala em voz alta
                try:
                    texto_falado = re.sub(r'```.*?```', '', resposta_limpa, flags=re.DOTALL)
                    texto_falado = re.sub(r'`.*?`', '', texto_falado)
                    texto_falado = texto_falado.replace('*', '').replace('#', '')
                    if texto_falado.strip() and self._audio_manager is not None and not self._get_tts_mudo():
                        asyncio.create_task(self._audio_manager.falar(texto_falado.strip()))
                except Exception as e:
                    self._log(f"[ERRO TTS] {e}")

            ultima_latencia_ms = round((time.monotonic() - _t0_req) * 1000)
            self._set_ultima_latencia_ms(ultima_latencia_ms)
            # Telemetria: registra sucesso do andar que respondeu + latência
            if tier_usado:
                self._telemetria["total_chats"] += 1
                self._registrar_tier(tier_usado, latencia_ms=ultima_latencia_ms)
            yield "data: [DONE]\n\n"

        return stream

    def definir_tts_mudo(self, payload: dict):
        """Liga/desliga a resposta por voz (audio_manager.falar) globalmente —
        botão de mute no frontend. Estado vive em memória, não persiste reinício
        do cérebro (o frontend reaplica via localStorage assim que reconecta)."""
        mudo = bool(payload.get("mudo", False))
        self._set_tts_mudo(mudo)
        return {"ok": True, "tts_mudo": mudo}

    async def tts_falar(self, payload: dict):
        """Dispara TTS pra um texto arbitrário — usado pelo frontend pra reler uma
        resposta ou falar uma notificação. Respeita o mute global."""
        texto = (payload.get("texto") or "").strip()
        if not texto:
            return {"ok": False, "erro": "texto vazio"}
        if self._get_tts_mudo():
            return {"ok": False, "erro": "TTS mutado"}
        if self._audio_manager is None:
            return {"ok": False, "erro": "audio_manager indisponível"}
        asyncio.create_task(self._audio_manager.falar(texto[:500]))
        return {"ok": True}
