"""tools/security_tools.py — Security tools: audit-log queries, Lyra service status, and Windows keyring key listing."""

def consultar_audit_log(limite: int = 50, tool_filtro: str = "", apenas_bloqueados: bool = False) -> dict:
    """
    Consulta o audit log imutável da Lyra — registro de todas as ferramentas
    chamadas, com timestamp, args, resultado e se foram bloqueadas por rate limit.
    Útil pra o usuário auditar o que a Lyra fez em segundo plano.
    """
    try:
        import lyra_seguranca
        return lyra_seguranca.consultar_audit(
            limite=limite,
            tool_filtro=tool_filtro,
            apenas_bloqueados=apenas_bloqueados,
        )
    except Exception as e:
        return {"ok": False, "erro": str(e)}

def migrar_chaves_para_keyring() -> dict:
    """
    Move as API keys do arquivo .env para o Windows Credential Manager
    (keyring). Após isso, as chaves ficam protegidas pelo login do Windows
    e não ficam mais em texto plano em disco.
    Operação única — reinicie o cerebro_maestro depois.
    """
    try:
        import lyra_seguranca
        return lyra_seguranca.migrar_chaves_para_keyring()
    except Exception as e:
        return {"ok": False, "erro": str(e)}

def listar_chaves_keyring() -> dict:
    """Mostra quais API keys estão configuradas no Credential Manager (sem revelar os valores)."""
    try:
        import lyra_seguranca
        return lyra_seguranca.listar_chaves_keyring()
    except Exception as e:
        return {"ok": False, "erro": str(e)}


SCHEMA = [
        {
            "type": "function",
            "function": {
                "name": "consultar_audit_log",
                "description": "Consulta o registro imutável de todas as ferramentas executadas pela Lyra (audit log). Use para responder 'o que você fez ontem?', 'quais comandos foram executados?', ou para auditar ações suspeitas.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limite":           {"type": "integer", "description": "Número de registros a retornar (default 50)."},
                        "tool_filtro":      {"type": "string",  "description": "Filtra por nome de ferramenta específica (ex: 'executar_comando')."},
                        "apenas_bloqueados": {"type": "boolean", "description": "Se true, retorna só as chamadas que foram bloqueadas por rate limit."},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "listar_chaves_keyring",
                "description": "Mostra quais API keys estão configuradas no Windows Credential Manager, sem revelar os valores.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
]


MAP = {
    "consultar_audit_log": consultar_audit_log,
    "listar_chaves_keyring": listar_chaves_keyring,
}
