"""tools/notifications.py — Notification tools: Windows toast and ntfy.sh push notifications."""

import pathlib
import secrets

_NTFY_TOPICO_FILE = pathlib.Path(__file__).parent.parent / "lyra_ntfy_topico.txt"

def notificar_usuario(titulo: str, mensagem: str, urgencia: str = "normal") -> dict:
    """
    Notificação nativa do Windows (toast). urgencia: 'normal' | 'alta'.
    É o canal de saída pra lembretes vencidos e pro Sistema de Números — usado
    pra interromper o usuário só quando algo realmente cruza o limiar de
    importância, não pra toda interação.
    """
    try:
        from winotify import Notification, audio
        toast = Notification(
            app_id="Lyra",
            title=titulo,
            msg=mensagem,
            duration="long" if urgencia == "alta" else "short",
        )
        toast.set_audio(audio.Reminder if urgencia == "alta" else audio.Default, loop=False)
        toast.show()
        return {"ok": True, "titulo": titulo}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def _get_ntfy_topico() -> str:
    """Gera (uma vez) e persiste um nome de tópico secreto — quem souber esse
    nome e se inscrever nele no app ntfy recebe as notificações. Não exige
    conta nem chave de API, só o app instalado + inscrito no mesmo tópico."""
    if _NTFY_TOPICO_FILE.exists():
        return _NTFY_TOPICO_FILE.read_text(encoding="utf-8").strip()
    import secrets
    topico = "lyra-" + secrets.token_hex(8)
    _NTFY_TOPICO_FILE.write_text(topico, encoding="utf-8")
    return topico

def notificar_celular(mensagem: str, titulo: str = "Lyra", urgente: bool = False) -> dict:
    """
    Envia notificação push pro celular via ntfy.sh (https://ntfy.sh) — alcança
    o usuário mesmo longe do PC, diferente de notificar_usuario (toast do
    Windows, só visível na própria máquina). Sem API key: basta o app ntfy
    instalado e inscrito no mesmo tópico secreto retornado por obter_topico_celular.
    """
    try:
        import requests
        topico = _get_ntfy_topico()
        r = requests.post(
            f"https://ntfy.sh/{topico}",
            data=mensagem.encode("utf-8"),
            headers={
                "Title": titulo.encode("utf-8"),
                "Priority": (b"urgent" if urgente else b"default"),
                "Tags": b"robot",
            },
            timeout=10,
        )
        r.raise_for_status()
        return {"ok": True, "topico": topico}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def obter_topico_celular() -> dict:
    """Retorna o nome do tópico ntfy que o usuário precisa abrir no app pra
    se inscrever e começar a receber as notificações da Lyra."""
    topico = _get_ntfy_topico()
    return {"ok": True, "topico": topico,
            "instrucao": f"Instale o app ntfy (Android/iOS/web), abra, toque em '+' e "
                        f"inscreva-se no tópico '{topico}'."}


SCHEMA = [
        {
            "type": "function",
            "function": {
                "name": "notificar_usuario",
                "description": "Envia notificação nativa do Windows (toast) pro usuário.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "titulo":   {"type": "string"},
                        "mensagem": {"type": "string"},
                        "urgencia": {"type": "string", "enum": ["normal", "alta"]},
                    },
                    "required": ["titulo", "mensagem"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "notificar_celular",
                "description": "Envia notificação push pro celular do usuário (via ntfy.sh), pra avisos que precisam alcançar ele mesmo longe do PC.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mensagem": {"type": "string"},
                        "titulo":   {"type": "string"},
                        "urgente":  {"type": "boolean"},
                    },
                    "required": ["mensagem"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "obter_topico_celular",
                "description": "Retorna o tópico ntfy que o usuário precisa se inscrever no app pra receber notificações push da Lyra.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
]


MAP = {
    "notificar_usuario": notificar_usuario,
    "notificar_celular": notificar_celular,
    "obter_topico_celular": obter_topico_celular,
}
