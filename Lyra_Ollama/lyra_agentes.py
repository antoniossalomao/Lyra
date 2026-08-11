# -*- coding: utf-8 -*-
"""
lyra_agentes.py — Sub-agentes paralelos (enxame/swarm) para o Projeto Lyra.

Importado por cerebro_maestro.py, que expõe os endpoints:
  POST /enxame               — criar
  GET  /enxame/{id}          — status
  POST /enxame/{id}/consolidar — consolidar resultados via LLM

Cada sub-tarefa roda com cascata Groq Llama 70B → Gemini 2.5 Flash isolada,
com acesso a QUASE TODAS as ferramentas do lyra_tools — exceto uma denylist de
operações destrutivas/auto-modificantes/recursivas (TOOLS_BLOQUEADAS), perigosas
em agentes autônomos rodando em paralelo (PowerShell, escrita de arquivo, spawn
de processos, criar_ferramenta, criar enxames, etc.).
Concorrência limitada por asyncio.Semaphore(max_paralelo).
"""

import asyncio
import json
import os
from datetime import datetime

from surreal_client import surreal
from config import GROQ_MODEL, GEMINI_MODEL

# ── Configuração ──────────────────────────────────────────────────────────────

GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Denylist: tudo do lyra_tools é liberado pras subtarefas, EXCETO estas.
# Critério de bloqueio (perigoso em agente autônomo paralelo):
#   - execução de código/comando arbitrário e abertura de apps
#   - mutação do sistema de arquivos (escrita/organização) e do clipboard
#   - auto-modificação (criar_ferramenta) e jobs pesados (backup)
#   - spawn de processos/vigilâncias/agendamentos em background
#   - escrita em stores que poluem (salvar_memoria, registrar_numero)
#   - notificações (evita spam vindo de N subtarefas)
#   - delegar pro Claude Code (consultar_especialista — agente completo)
#   - RECURSÃO: criar/operar enxames de dentro de uma subtarefa
TOOLS_BLOQUEADAS = {
    "executar_comando", "abrir_app",
    "escrever_arquivo", "organizar_pasta", "escrever_clipboard", "controlar_midia",
    "criar_ferramenta", "backup_memoria",
    "iniciar_vigilancia_pasta", "parar_vigilancia_pasta",
    "iniciar_processo_bg", "gerenciar_agendamentos",
    "salvar_memoria", "registrar_numero",
    "notificar_usuario", "notificar_celular",
    "consultar_especialista",
    "criar_enxame", "status_enxame", "consolidar_enxame",
}

MAX_PARALELO_PADRAO = 3   # com cloud APIs (Groq), não há pressão de VRAM
TIMEOUT_SUBTAREFA   = 120  # segundos por subtarefa
MAX_ROUNDS_TOOL     = 8   # rounds máximos de tool-calling por subtarefa

_tools_schema_cache = None
_tools_map_cache    = None


# ── Helpers SurrealDB (delegam pro SurrealClient compartilhado) ───────────────

_sq = surreal.query_result   # query → result[0]
_sx = surreal.execute        # statement sem retorno
_safe_id = surreal.safe_id
_surreal_set = surreal.format_set


# ── Ferramentas seguras ───────────────────────────────────────────────────────

def _get_tools():
    global _tools_schema_cache, _tools_map_cache
    if _tools_schema_cache is None:
        import lyra_tools
        _tools_map_cache    = {k: v for k, v in lyra_tools.TOOLS_MAP.items()
                                if k not in TOOLS_BLOQUEADAS}
        _tools_schema_cache = [t for t in lyra_tools.TOOLS_SCHEMA
                                if t["function"]["name"] not in TOOLS_BLOQUEADAS]
    return _tools_schema_cache, _tools_map_cache


def _exec_tool(nome: str, args: dict) -> str:
    _, tools_map = _get_tools()
    if nome not in tools_map:
        return json.dumps({"erro": f"'{nome}' bloqueada em subtarefas (destrutiva/recursiva)."})
    try:
        res = tools_map[nome](**args)
        return json.dumps(res, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"erro": f"Falha em {nome}: {e}"})


# ── LLM com cascata Groq → Gemini (via LLMCascade compartilhada) ─────────────

_cascade = None  # singleton lazy — evita construir clients em import


def _get_cascade():
    global _cascade
    if _cascade is None:
        from llm_cascade import LLMCascade
        _cascade = LLMCascade({"groq": GROQ_API_KEY, "gemini": GEMINI_API_KEY})
    return _cascade


async def _chamar_llm_subtarefa(msgs: list, tools_schema: list) -> str:
    """Tenta Groq; se falhar (rate-limit, indisponível), cai pro Gemini.
    Local fica de fora de propósito: N subtarefas paralelas disputando a VRAM
    do qwen3:8b travariam a máquina.

    Raises:
        RuntimeError: quando todos os provedores da subtarefa falham.
    """
    resultado = await _get_cascade().run(
        messages=msgs,
        tools_schema=tools_schema,
        tool_executor=_exec_tool,
        max_iterations=MAX_ROUNDS_TOOL,
        providers=["groq", "gemini"],
        max_tokens=1200,
    )
    if resultado["provider"] is None:
        raise RuntimeError(
            f"Todos os LLMs falharam em subtarefa: {'; '.join(resultado['erros'])}")
    return resultado["resposta_final"]


# ── Execução de subtarefa ─────────────────────────────────────────────────────

_SYSTEM_SUBTAREFA = (
    "Você é a Lyra, IA pessoal do Projeto Lyra (Admin: Antônio). "
    "Está executando uma sub-tarefa isolada de um enxame de agentes paralelos. "
    "Você tem ferramentas (busca na web, leitura de arquivos/URLs, memória, visão, "
    "documentos, etc.) — USE-AS quando a tarefa exigir dados que você não tem. "
    "COMPLETE A TAREFA com o mínimo de texto explicativo. "
    "Entregue resultado direto: dados, resumo ou texto solicitado. PT-BR obrigatório."
)


async def _executar_subtarefa(enxame_id: str, sub_id: str, descricao: str):
    """Executa uma subtarefa: Groq com tool-calling, persiste resultado no SurrealDB."""
    await _sx(
        f"UPDATE subtarefa:`{sub_id}` SET "
        f"status = 'rodando', iniciado_em = '{datetime.now().isoformat()}';"
    )

    tools_schema, _ = _get_tools()

    msgs = [
        {"role": "system", "content": _SYSTEM_SUBTAREFA},
        {"role": "user",   "content": descricao},
    ]

    resultado = ""

    try:
        resultado = await _chamar_llm_subtarefa(msgs, tools_schema)
        await _sx(
            f"UPDATE subtarefa:`{sub_id}` SET "
            + _surreal_set({
                "status":       "concluida",
                "resultado":    resultado[:2000],
                "concluido_em": datetime.now().isoformat(),
            }) + ";"
        )

    except asyncio.TimeoutError:
        await _sx(
            f"UPDATE subtarefa:`{sub_id}` SET "
            + _surreal_set({"status": "erro", "erro": f"Timeout após {TIMEOUT_SUBTAREFA}s.",
                            "concluido_em": datetime.now().isoformat()})
            + ";"
        )
    except Exception as e:
        await _sx(
            f"UPDATE subtarefa:`{sub_id}` SET "
            + _surreal_set({"status": "erro", "erro": str(e)[:500],
                            "concluido_em": datetime.now().isoformat()})
            + ";"
        )


# ── Orquestrador do enxame ────────────────────────────────────────────────────

async def _rodar_enxame(enxame_id: str, sub_pairs: list[tuple[str, str]], max_paralelo: int):
    """Roda todas as subtarefas com concorrência limitada pelo Semaphore."""
    sem = asyncio.Semaphore(max_paralelo)

    async def _com_sem(sub_id: str, descricao: str):
        async with sem:
            await _executar_subtarefa(enxame_id, sub_id, descricao)

    await asyncio.gather(*[_com_sem(sid, desc) for sid, desc in sub_pairs], return_exceptions=True)

    # Verifica se alguma falhou para refletir no status do enxame
    rows = await _sq(
        f"SELECT status FROM subtarefa WHERE enxame_id = '{enxame_id}';"
    )
    status_enxame = "concluido"
    if any(r.get("status") == "erro" for r in rows):
        n_erros = sum(1 for r in rows if r.get("status") == "erro")
        status_enxame = f"concluido_com_erros({n_erros})"

    await _sx(
        f"UPDATE enxame:`{enxame_id}` SET "
        f"status = '{status_enxame}', concluido_em = '{datetime.now().isoformat()}';"
    )


# ── API pública (usada pelos endpoints do cerebro_maestro) ────────────────────

async def criar_enxame(objetivo: str, subtarefas: list[str],
                       max_paralelo: int = MAX_PARALELO_PADRAO) -> dict:
    """
    Cria enxame no SurrealDB e dispara execução em background.
    Retorna imediatamente: {enxame_id, status, total}.
    """
    if not subtarefas:
        return {"erro": "Lista de subtarefas vazia."}
    if len(subtarefas) > 20:
        return {"erro": "Máximo 20 subtarefas por enxame."}
    max_paralelo = max(1, min(max_paralelo, 6))

    enxame_id = _safe_id()
    agora     = datetime.now().isoformat()

    await _sx(
        f"CREATE enxame:`{enxame_id}` CONTENT "
        + json.dumps({
            "objetivo":         objetivo,
            "total_subtarefas": len(subtarefas),
            "max_paralelo":     max_paralelo,
            "status":           "rodando",
            "criado":           agora,
            "concluido_em":     None,
            "resumo_final":     None,
        }, ensure_ascii=False) + ";"
    )

    sub_pairs: list[tuple[str, str]] = []
    for desc in subtarefas:
        sub_id = _safe_id()
        await _sx(
            f"CREATE subtarefa:`{sub_id}` CONTENT "
            + json.dumps({
                "enxame_id":   enxame_id,
                "descricao":   desc,
                "status":      "pendente",
                "resultado":   None,
                "erro":        None,
                "iniciado_em": None,
                "concluido_em": None,
            }, ensure_ascii=False) + ";"
        )
        sub_pairs.append((sub_id, desc))

    # Dispara em background — não bloqueia a resposta HTTP
    asyncio.create_task(_rodar_enxame(enxame_id, sub_pairs, max_paralelo))

    return {"enxame_id": enxame_id, "status": "rodando", "total": len(subtarefas)}


async def listar_enxames(limite: int = 20) -> dict:
    """Lista os enxames mais recentes (resumo), pra dashboard/debugging."""
    rows = await _sq(
        f"SELECT id, objetivo, status, total_subtarefas, criado, concluido_em "
        f"FROM enxame ORDER BY criado DESC LIMIT {min(limite, 100)};"
    )
    enxames = []
    for e in rows:
        eid = str(e.get("id", "")).split(":")[-1].strip("`")
        enxames.append({
            "enxame_id":        eid,
            "objetivo":         e.get("objetivo", "")[:120],
            "status":           e.get("status", "?"),
            "total_subtarefas": e.get("total_subtarefas", 0),
            "criado":           e.get("criado", ""),
            "concluido_em":     e.get("concluido_em"),
        })
    return {"total": len(enxames), "enxames": enxames}


async def status_enxame(enxame_id: str) -> dict:
    """Retorna estado atual do enxame e de todas as suas subtarefas."""
    enxame_rows = await _sq(f"SELECT * FROM enxame:`{enxame_id}`;")
    if not enxame_rows:
        return {"erro": f"Enxame '{enxame_id}' não encontrado."}

    enxame = enxame_rows[0]
    subs   = await _sq(f"SELECT * FROM subtarefa WHERE enxame_id = '{enxame_id}';")

    contagem = {"pendente": 0, "rodando": 0, "concluida": 0, "erro": 0}
    for s in subs:
        st = s.get("status", "pendente")
        if st in contagem:
            contagem[st] += 1

    return {
        "enxame_id":    enxame_id,
        "objetivo":     enxame.get("objetivo", ""),
        "status":       enxame.get("status", "?"),
        "criado":       enxame.get("criado", ""),
        "concluido_em": enxame.get("concluido_em"),
        "resumo_final": enxame.get("resumo_final"),
        "contagem":     contagem,
        "subtarefas": [
            {
                "id":         str(s.get("id", "")),
                "descricao":  s.get("descricao", "")[:120],
                "status":     s.get("status", "?"),
                "resultado":  (s.get("resultado") or "")[:300],
                "erro":       s.get("erro"),
                "iniciado_em": s.get("iniciado_em"),
                "concluido_em": s.get("concluido_em"),
            }
            for s in subs
        ],
    }


async def consolidar_enxame(enxame_id: str) -> dict:
    """
    Consolida resultados de todas as subtarefas num resumo coerente via Groq.
    Só funciona quando o enxame estiver concluído (status != 'rodando').
    """
    enxame_rows = await _sq(f"SELECT * FROM enxame:`{enxame_id}`;")
    if not enxame_rows:
        return {"erro": f"Enxame '{enxame_id}' não encontrado."}

    enxame = enxame_rows[0]
    if enxame.get("status") == "rodando":
        return {"erro": "Enxame ainda em execução. Aguarde todas as subtarefas terminarem."}
    if enxame.get("resumo_final"):
        return {"enxame_id": enxame_id, "resumo": enxame["resumo_final"], "fonte": "cache"}

    subs = await _sq(f"SELECT * FROM subtarefa WHERE enxame_id = '{enxame_id}';")
    if not subs:
        return {"erro": "Nenhuma subtarefa encontrada."}

    # Monta bloco de resultados para o LLM
    partes = [f"Objetivo do enxame: {enxame.get('objetivo', '')}"]
    for i, s in enumerate(subs, 1):
        status = s.get("status", "?")
        if status == "concluida":
            partes.append(f"\n[Subtarefa {i}] {s.get('descricao', '')}\nResultado: {s.get('resultado', '')}")
        else:
            partes.append(f"\n[Subtarefa {i}] {s.get('descricao', '')}\nStatus: {status} | Erro: {s.get('erro', '-')}")
    bloco = "\n".join(partes)

    try:
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY não configurada.")

        from groq import AsyncGroq
        client = AsyncGroq(api_key=GROQ_API_KEY)
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content":
                        "Você é a Lyra. Consolide os resultados das subtarefas abaixo "
                        "num único texto coeso e direto. Sem repetições, sem prefácios. PT-BR."},
                    {"role": "user", "content": bloco},
                ],
                temperature=0.3,
                max_tokens=1500,
            ),
            timeout=60,
        )
        resumo = resp.choices[0].message.content.strip()
    except Exception as e:
        resumo = f"[Falha na consolidação via LLM: {e}]\n\nResultados brutos:\n{bloco[:3000]}"

    # Persiste o resumo no enxame
    await _sx(
        f"UPDATE enxame:`{enxame_id}` SET "
        f"resumo_final = {json.dumps(resumo, ensure_ascii=False)};"
    )

    return {"enxame_id": enxame_id, "resumo": resumo}
