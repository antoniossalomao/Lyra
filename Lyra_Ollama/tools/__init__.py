"""tools/__init__.py — aggregates every domain submodule into a single
ToolRegistry and re-exports TOOLS_MAP/TOOLS_SCHEMA/run_tool for backward
compatibility with the pre-split lyra_tools.py API.
"""

from . import (fs, os_tools, vision, memory, documents, web, system,
              notifications, reminders, processes, numbers, specialist,
              clipboard, git_tools, email_cal, security_tools)
from ._registry import ToolRegistry

_MODULES = (fs, os_tools, vision, memory, documents, web, system,
           notifications, reminders, processes, numbers, specialist,
           clipboard, git_tools, email_cal, security_tools)

TOOLS_MAP: dict = {}
TOOLS_SCHEMA: list = []
for _mod in _MODULES:
    TOOLS_MAP.update(_mod.MAP)
    TOOLS_SCHEMA.extend(_mod.SCHEMA)

_registry = ToolRegistry(TOOLS_MAP, TOOLS_SCHEMA,
                         specialist._TOOLS_EXT_DIR, specialist._TOOLS_EXT_INDEX)


def run_tool(nome: str, args: dict):
    """Dispatch a tool call by name — same contract as the old executar_tool()."""
    return _registry.run(nome, args)


# Funções internas usadas pelo proactive_loop.py e lyra_seguranca.py — mesmos
# nomes do lyra_tools.py monolítico, agora vivendo nos submódulos de domínio.
gerenciar_lembretes = reminders.gerenciar_lembretes
listar_numeros = numbers.listar_numeros
_marcar_numero_notificado = numbers._marcar_numero_notificado
_processar_agendamentos_devidos = reminders._processar_agendamentos_devidos
_checar_processos_bg_concluidos = processes._checar_processos_bg_concluidos
notificar_usuario = notifications.notificar_usuario
