"""tools/email_cal.py — Google Workspace tools: Gmail read/draft, Calendar list/create (lazy-imports lyra_google_workspace)."""

def ler_emails(query: str = "is:unread", max_results: int = 10) -> dict:
    """Lista emails do Gmail. Suporta filtros nativos: 'is:unread', 'from:x@y.com',
    'subject:assunto', 'after:2026/06/01'. Retorna id, remetente, assunto, data e snippet."""
    try:
        import lyra_google_workspace as _gws
        return _gws.ler_emails(query=query, max_results=max_results)
    except Exception as e:
        return {"erro": str(e)}

def ler_email(email_id: str) -> dict:
    """Lê o corpo completo de um email pelo ID retornado por ler_emails()."""
    try:
        import lyra_google_workspace as _gws
        return _gws.ler_email(email_id=email_id)
    except Exception as e:
        return {"erro": str(e)}

def criar_rascunho_email(para: str, assunto: str, corpo: str) -> dict:
    """Cria rascunho no Gmail (NÃO envia — fica salvo para revisão)."""
    try:
        import lyra_google_workspace as _gws
        return _gws.criar_rascunho_email(para=para, assunto=assunto, corpo=corpo)
    except Exception as e:
        return {"erro": str(e)}

def listar_eventos(dias: int = 7) -> dict:
    """Lista eventos do Google Calendar nos próximos N dias. Retorna título, início, fim e local."""
    try:
        import lyra_google_workspace as _gws
        return _gws.listar_eventos(dias=dias)
    except Exception as e:
        return {"erro": str(e)}

def criar_evento(titulo: str, inicio: str, fim: str, descricao: str = "", convidados: list | None = None) -> dict:
    """Cria evento no Google Calendar. inicio/fim em ISO 8601, ex: '2026-07-05T14:00:00-03:00'."""
    try:
        import lyra_google_workspace as _gws
        return _gws.criar_evento(titulo=titulo, inicio=inicio, fim=fim, descricao=descricao, convidados=convidados)
    except Exception as e:
        return {"erro": str(e)}


SCHEMA = [
        {
            "type": "function",
            "function": {
                "name": "ler_emails",
                "description": "Lista emails do Gmail. Suporta filtros nativos: 'is:unread', 'from:x@y.com', 'subject:assunto', 'after:2026/06/01'. Exige setup OAuth (ver lyra_google_workspace.py).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query":       {"type": "string",  "description": "Filtro Gmail (default 'is:unread')."},
                        "max_results": {"type": "integer", "description": "Máx de emails a retornar (default 10)."},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ler_email",
                "description": "Lê o corpo completo de um email pelo ID retornado por ler_emails().",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "email_id": {"type": "string", "description": "ID do email (campo 'id' de ler_emails)."},
                    },
                    "required": ["email_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "criar_rascunho_email",
                "description": "Cria rascunho no Gmail (NÃO envia — fica salvo no Gmail para revisão manual).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "para":    {"type": "string", "description": "Endereço de destino."},
                        "assunto": {"type": "string", "description": "Linha de assunto."},
                        "corpo":   {"type": "string", "description": "Texto do email."},
                    },
                    "required": ["para", "assunto", "corpo"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "listar_eventos",
                "description": "Lista eventos do Google Calendar nos próximos N dias. Retorna título, início, fim e local.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dias": {"type": "integer", "description": "Número de dias à frente (default 7)."},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "criar_evento",
                "description": "Cria evento no Google Calendar. inicio/fim em ISO 8601, ex: '2026-07-05T14:00:00-03:00'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "titulo":     {"type": "string", "description": "Título do evento."},
                        "inicio":     {"type": "string", "description": "Data/hora de início ISO 8601."},
                        "fim":        {"type": "string", "description": "Data/hora de fim ISO 8601."},
                        "descricao":  {"type": "string", "description": "Descrição opcional."},
                        "convidados": {"type": "array",  "items": {"type": "string"}, "description": "Lista de emails de convidados (opcional)."},
                    },
                    "required": ["titulo", "inicio", "fim"],
                },
            },
        },
]


MAP = {
    "ler_emails": ler_emails,
    "ler_email": ler_email,
    "criar_rascunho_email": criar_rascunho_email,
    "listar_eventos": listar_eventos,
    "criar_evento": criar_evento,
}
