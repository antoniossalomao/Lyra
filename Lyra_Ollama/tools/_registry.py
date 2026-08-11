"""tools/_registry.py — central dispatcher for all Lyra tools (native +
dynamic extensions created at runtime via specialist.criar_ferramenta).
"""

import importlib.util
import json
from typing import Any, Callable


class ToolRegistry:
    """Aggregates TOOLS_MAP/TOOLS_SCHEMA from every domain submodule and
    dispatches calls by name, falling back to dynamically-created tools on
    disk (tools_ext/) when a name isn't in the native map.

    Attributes:
        tools_map:    name -> callable, aggregated from every domain module.
        tools_schema: OpenAI-format tool definitions, same aggregation.
    """

    def __init__(self, tools_map: dict[str, Callable], tools_schema: list[dict],
                 ext_dir, ext_index_path):
        self.tools_map = dict(tools_map)
        self.tools_schema = list(tools_schema)
        self._ext_dir = ext_dir
        self._ext_index_path = ext_index_path

    def register(self, fn: Callable, schema: dict) -> None:
        """Register a single callable with its OpenAI-format schema (used by
        callers that want to extend the registry without a new submodule)."""
        self.tools_map[fn.__name__] = fn
        self.tools_schema.append(schema)

    def filter(self, blocked: set[str]) -> tuple[list[dict], dict[str, Callable]]:
        """Return (schema_list, tool_map) with blocked tool names removed.
        Used by lyra_agent/lyra_agentes to enforce their sandboxed tool sets."""
        schema = [t for t in self.tools_schema if t["function"]["name"] not in blocked]
        tools = {k: v for k, v in self.tools_map.items() if k not in blocked}
        return schema, tools

    def run(self, nome: str, args: dict) -> Any:
        """Dispatch a tool call by name: native tools first, then tools_ext/.

        Returns:
            The tool's raw return value (dict, usually) or an error dict.
        """
        fn = self.tools_map.get(nome)
        if fn:
            return fn(**args)

        ext_path = self._ext_dir / f"{nome}.py"
        if ext_path.exists():
            if self._ext_index_path.exists():
                index = json.loads(self._ext_index_path.read_text(encoding="utf-8"))
                info = index.get(nome, {})
                if info.get("pendente_aprovacao"):
                    riscos = ", ".join(info.get("riscos_detectados", [])) or "padrão suspeito"
                    return {"erro": f"Ferramenta '{nome}' está BLOQUEADA pendente de aprovação "
                                    f"manual do usuário (riscos detectados: {riscos}). Não posso "
                                    f"executá-la sozinha — avise o usuário que precisa aprovar."}
            spec = importlib.util.spec_from_file_location(nome, str(ext_path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            fn = getattr(mod, nome, None)
            if fn:
                self.tools_map[nome] = fn  # cache para próximas chamadas
                return fn(**args)

        return {"erro": f"Ferramenta desconhecida: '{nome}'. "
                        f"Disponíveis: {list(self.tools_map.keys())}"}
