# -*- coding: utf-8 -*-
"""
lyra_agent.py — Loop ReAct autônomo e standalone da Lyra.

Diferente do chat principal (cerebro_maestro.py, streaming pro frontend via SSE),
recebe um OBJETIVO (não uma conversa) e itera sozinho chamando ferramentas de
lyra_tools até responder ou até esgotar max_iteracoes. Sem streaming: retorna
o resultado final de uma vez.

Reaproveita o mesmo padrão de cascata Groq → Gemini (function-calling formato
OpenAI/Gemini nativo) e de persistência SurrealDB de lyra_agentes.py — aqui
para uma única execução sequencial (não enxame paralelo), tabela `agente_run`.
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from surreal_client import surreal

# ── Configuração ──────────────────────────────────────────────────────────────

GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Mesmo critério de lyra_agentes.py: bloqueia o que é destrutivo, spawna
# processos/agendamentos em background, se auto-modifica ou é recursivo
# (chamar o próprio agente/enxame de dentro de uma execução autônoma).
TOOLS_BLOQUEADAS_PADRAO = {
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

MAX_ITERACOES_PADRAO = 10

_SYSTEM_AGENTE = (
    "Você é a Lyra, IA pessoal do Projeto Lyra (Admin: Antônio), executando "
    "um agente autônomo: recebeu um OBJETIVO e deve resolvê-lo sozinha, sem "
    "conversa contínua com o usuário. Use as ferramentas disponíveis quando "
    "precisar de dados que não tem. Quando o objetivo estiver cumprido, "
    "responda com TEXTO FINAL direto (sem chamar mais ferramentas) contendo "
    "o resultado ou a resposta pedida. PT-BR obrigatório."
)


# ── Persistência SurrealDB ────────────────────────────────────────────────────

async def _persistir_run(run_id: str, resultado: dict):
    await surreal.execute(
        f"CREATE agente_run:`{run_id}` CONTENT "
        + json.dumps({
            "objetivo":       resultado["objetivo"],
            "iteracoes":      resultado["iteracoes_usadas"],
            "passos":         resultado["passos"],
            "resposta_final": resultado["resposta_final"],
            "sucesso":        resultado["sucesso"],
            "criado_em":      datetime.now().isoformat(),
        }, ensure_ascii=False) + ";"
    )


# ── Ferramentas (schema + dispatcher seguro) ─────────────────────────────────

def _get_tools(ferramentas_bloqueadas: set[str]):
    import lyra_tools
    tools_map = {k: v for k, v in lyra_tools.TOOLS_MAP.items() if k not in ferramentas_bloqueadas}
    tools_schema = [t for t in lyra_tools.TOOLS_SCHEMA
                    if t["function"]["name"] not in ferramentas_bloqueadas]
    return tools_schema, tools_map


def _exec_tool_segura(tools_map: dict, nome: str, args: dict) -> str:
    if nome not in tools_map:
        return json.dumps({"erro": f"'{nome}' bloqueada para agentes autônomos (destrutiva/recursiva)."})
    try:
        res = tools_map[nome](**args)
        return json.dumps(res, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"erro": f"Falha em {nome}: {e}"})


# ── API pública ────────────────────────────────────────────────────────────────

_cascade = None  # singleton lazy — evita construir clients em import


def _get_cascade():
    """Return the module-level LLMCascade singleton (batch mode only here)."""
    global _cascade
    if _cascade is None:
        from llm_cascade import LLMCascade
        _cascade = LLMCascade({"groq": GROQ_API_KEY, "gemini": GEMINI_API_KEY})
    return _cascade


async def executar_agente_async(objetivo: str, max_iteracoes: int = MAX_ITERACOES_PADRAO,
                                 ferramentas_bloqueadas: set[str] | None = None) -> dict:
    """Run the autonomous ReAct loop for a goal via the unified LLM cascade.

    Args:
        objetivo:               Natural-language objective.
        max_iteracoes:          Max tool-call rounds per provider.
        ferramentas_bloqueadas: Denylist override (default TOOLS_BLOQUEADAS_PADRAO).

    Returns:
        Dict with objetivo, resposta_final, passos, iteracoes_usadas, sucesso.
    """
    bloqueadas = ferramentas_bloqueadas if ferramentas_bloqueadas is not None else TOOLS_BLOQUEADAS_PADRAO
    tools_schema, tools_map = _get_tools(bloqueadas)

    resultado = await _get_cascade().run(
        goal=objetivo,
        tools_schema=tools_schema,
        tool_executor=lambda nome, args: _exec_tool_segura(tools_map, nome, args),
        max_iterations=max_iteracoes,
        system_prompt=_SYSTEM_AGENTE,
    )
    if resultado["provider"] is None:
        resultado["resposta_final"] = (
            f"Falha em todos os andares da cascata: {'; '.join(resultado['erros'])}")

    resultado = {"objetivo": objetivo, **resultado}

    try:
        await _persistir_run(surreal.safe_id(), resultado)
    except Exception as e:
        resultado["aviso_persistencia"] = f"Falha ao persistir agente_run: {e}"

    return resultado


def executar_agente(objetivo: str, max_iteracoes: int = MAX_ITERACOES_PADRAO,
                     ferramentas_bloqueadas: set[str] | None = None) -> dict:
    return asyncio.run(executar_agente_async(objetivo, max_iteracoes, ferramentas_bloqueadas))


# ── Self-test ──────────────────────────────────────────────────────────────────

def self_test() -> dict:
    """Bateria de objetivos simples validando que o loop ReAct não trava,
    reflete resultado de tool na resposta final quando uma é chamada, e
    sobrevive a erro de tool sem derrubar o processo."""
    casos = [
        {
            "nome": "aritmetica_sem_tool",
            "objetivo": "Quanto é 15 vezes 23? Responda só o número.",
            "verificar": lambda r: "345" in (r["resposta_final"] or ""),
        },
        {
            "nome": "busca_memoria",
            "objetivo": "Use a ferramenta buscar_memoria para pesquisar 'capital da França' e diga o que encontrou.",
            "verificar": lambda r: r["sucesso"] and any(p["tool"] == "buscar_memoria" for p in r["passos"]),
        },
        {
            "nome": "tool_inexistente_nao_derruba",
            "objetivo": "Chame a ferramenta 'ferramenta_que_nao_existe_xyz' com qualquer argumento e depois me diga o que aconteceu.",
            "verificar": lambda r: r["sucesso"] or r["iteracoes_usadas"] >= 1,
        },
    ]

    detalhes = []
    passou_n = 0

    for caso in casos:
        try:
            resultado = executar_agente(caso["objetivo"], max_iteracoes=6)
            ok = bool(caso["verificar"](resultado))
        except Exception as e:
            resultado = {"erro": str(e)}
            ok = False

        if ok:
            passou_n += 1
        detalhes.append({
            "caso": caso["nome"],
            "passou": ok,
            "resposta_final": resultado.get("resposta_final", ""),
            "iteracoes_usadas": resultado.get("iteracoes_usadas"),
            "passos": [p.get("tool") for p in resultado.get("passos", [])] if isinstance(resultado.get("passos"), list) else [],
        })

    saida = {"total": len(casos), "passou": passou_n, "falhou": len(casos) - passou_n, "detalhes": detalhes}

    print(f"\n[self_test] {saida['passou']}/{saida['total']} casos passaram.")
    for d in detalhes:
        marca = "OK" if d["passou"] else "FALHOU"
        print(f"  [{marca}] {d['caso']} — iteracoes={d['iteracoes_usadas']} tools={d['passos']}")
        print(f"         resposta: {d['resposta_final'][:200]}")

    return saida


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Loop ReAct autônomo da Lyra.")
    parser.add_argument("--objetivo", type=str, help="Objetivo a resolver.")
    parser.add_argument("--max-iteracoes", type=int, default=MAX_ITERACOES_PADRAO)
    parser.add_argument("--self-test", action="store_true", help="Roda a bateria de auto-teste.")
    args = parser.parse_args()

    if args.self_test:
        resultado_teste = self_test()
        sys.exit(0 if resultado_teste["falhou"] == 0 else 1)
    elif args.objetivo:
        resultado = executar_agente(args.objetivo, max_iteracoes=args.max_iteracoes)
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
    else:
        parser.print_help()
        sys.exit(1)
