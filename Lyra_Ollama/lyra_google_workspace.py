"""
lyra_google_workspace.py — Gmail + Google Calendar via OAuth2.

SETUP (uma vez só):
  1. Acesse https://console.cloud.google.com/
  2. Crie um projeto → Ative "Gmail API" e "Google Calendar API"
  3. Credenciais → Criar credenciais → ID do cliente OAuth 2.0 → App para computador
  4. Baixe o JSON e salve em: C:\\Lyra_Project\\Lyra_Core\\google_auth\\credentials.json
  5. Execute este arquivo diretamente UMA VEZ para autorizar:
       python lyra_google_workspace.py
     Um browser vai abrir para login. Depois gera token.json automaticamente.

FERRAMENTAS EXPOSTAS (adicionar em lyra_tools.py):
  - ler_emails(query, max_results)         → lista emails (suporta filtros Gmail)
  - ler_email(email_id)                    → corpo completo de um email
  - criar_rascunho_email(para, assunto, corpo) → cria rascunho (não envia)
  - listar_eventos(dias)                   → eventos do calendário nos próximos N dias
  - criar_evento(titulo, inicio, fim, descricao) → cria evento (ISO 8601)
"""

import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import os
import base64
import json
import datetime
from pathlib import Path

_AUTH_DIR   = Path(r"C:\Lyra_Project\Lyra_Core\google_auth")
_CREDS_FILE = _AUTH_DIR / "credentials.json"
_TOKEN_FILE = _AUTH_DIR / "token.json"

_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
]

_gmail_svc    = None
_calendar_svc = None


def _get_creds():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if _TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_FILE), _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not _CREDS_FILE.exists():
                raise FileNotFoundError(
                    f"credentials.json não encontrado em {_CREDS_FILE}. "
                    "Siga o SETUP no topo deste arquivo."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(_CREDS_FILE), _SCOPES)
            creds = flow.run_local_server(port=0)
        _TOKEN_FILE.write_text(creds.to_json())

    return creds


def _gmail():
    global _gmail_svc
    if _gmail_svc is None:
        from googleapiclient.discovery import build
        _gmail_svc = build("gmail", "v1", credentials=_get_creds())
    return _gmail_svc


def _calendar():
    global _calendar_svc
    if _calendar_svc is None:
        from googleapiclient.discovery import build
        _calendar_svc = build("calendar", "v3", credentials=_get_creds())
    return _calendar_svc


# ── Gmail ─────────────────────────────────────────────────────────────────────

def ler_emails(query: str = "is:unread", max_results: int = 10) -> dict:
    """
    Lista emails do Gmail. Suporta filtros nativos do Gmail:
      "is:unread", "from:alguem@email.com", "subject:assunto", "after:2026/06/01"
    Retorna lista com id, remetente, assunto, data e snippet (prévia).
    """
    try:
        res = _gmail().users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()

        mensagens = []
        for m in res.get("messages", []):
            msg = _gmail().users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()

            headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
            mensagens.append({
                "id":       m["id"],
                "de":       headers.get("From", ""),
                "assunto":  headers.get("Subject", "(sem assunto)"),
                "data":     headers.get("Date", ""),
                "snippet":  msg.get("snippet", ""),
            })

        return {"emails": mensagens, "total": len(mensagens)}
    except Exception as e:
        return {"erro": str(e)}


def ler_email(email_id: str) -> dict:
    """
    Lê o corpo completo de um email pelo ID.
    O ID vem do campo 'id' retornado por ler_emails().
    """
    try:
        msg = _gmail().users().messages().get(
            userId="me", id=email_id, format="full"
        ).execute()

        headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}

        def _extrair_corpo(payload):
            """Extrai texto plain do payload (recursivo para multipart)."""
            mime = payload.get("mimeType", "")
            if mime == "text/plain" and "data" in payload.get("body", {}):
                return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
            for part in payload.get("parts", []):
                resultado = _extrair_corpo(part)
                if resultado:
                    return resultado
            return ""

        return {
            "id":      email_id,
            "de":      headers.get("From", ""),
            "para":    headers.get("To", ""),
            "assunto": headers.get("Subject", "(sem assunto)"),
            "data":    headers.get("Date", ""),
            "corpo":   _extrair_corpo(msg["payload"]),
        }
    except Exception as e:
        return {"erro": str(e)}


def criar_rascunho_email(para: str, assunto: str, corpo: str) -> dict:
    """
    Cria um rascunho no Gmail (NÃO envia — abre no Gmail para revisão).
    para: endereço de destino, assunto: linha de assunto, corpo: texto do email.
    """
    try:
        from email.mime.text import MIMEText
        mime = MIMEText(corpo)
        mime["to"]      = para
        mime["subject"] = assunto
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()

        rascunho = _gmail().users().drafts().create(
            userId="me", body={"message": {"raw": raw}}
        ).execute()

        return {
            "status":      "rascunho_criado",
            "rascunho_id": rascunho["id"],
            "para":        para,
            "assunto":     assunto,
        }
    except Exception as e:
        return {"erro": str(e)}


# ── Google Calendar ────────────────────────────────────────────────────────────

def listar_eventos(dias: int = 7) -> dict:
    """
    Lista eventos do Google Calendar nos próximos N dias (default 7).
    Retorna id, título, início, fim, local e descrição de cada evento.
    """
    try:
        agora   = datetime.datetime.utcnow().isoformat() + "Z"
        limite  = (datetime.datetime.utcnow() + datetime.timedelta(days=dias)).isoformat() + "Z"

        res = _calendar().events().list(
            calendarId="primary",
            timeMin=agora,
            timeMax=limite,
            maxResults=50,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        eventos = []
        for e in res.get("items", []):
            inicio = e["start"].get("dateTime", e["start"].get("date", ""))
            fim    = e["end"].get("dateTime", e["end"].get("date", ""))
            eventos.append({
                "id":        e["id"],
                "titulo":    e.get("summary", "(sem título)"),
                "inicio":    inicio,
                "fim":       fim,
                "local":     e.get("location", ""),
                "descricao": e.get("description", ""),
            })

        return {"eventos": eventos, "total": len(eventos), "janela_dias": dias}
    except Exception as e:
        return {"erro": str(e)}


def criar_evento(
    titulo: str,
    inicio: str,
    fim: str,
    descricao: str = "",
    convidados: list[str] | None = None,
) -> dict:
    """
    Cria um evento no Google Calendar.
    inicio/fim: ISO 8601 com timezone, ex: "2026-07-05T14:00:00-03:00"
    convidados: lista opcional de emails, ex: ["alguem@email.com"]
    """
    try:
        evento = {
            "summary":     titulo,
            "description": descricao,
            "start":       {"dateTime": inicio, "timeZone": "America/Sao_Paulo"},
            "end":         {"dateTime": fim,    "timeZone": "America/Sao_Paulo"},
        }
        if convidados:
            evento["attendees"] = [{"email": e} for e in convidados]

        criado = _calendar().events().insert(
            calendarId="primary", body=evento
        ).execute()

        return {
            "status":  "evento_criado",
            "id":      criado["id"],
            "titulo":  titulo,
            "inicio":  inicio,
            "fim":     fim,
            "link":    criado.get("htmlLink", ""),
        }
    except Exception as e:
        return {"erro": str(e)}


# ── Setup interativo (rodar este arquivo diretamente) ─────────────────────────

if __name__ == "__main__":
    print("=== Setup OAuth Google Workspace ===")
    print(f"Procurando credentials.json em: {_CREDS_FILE}")
    try:
        creds = _get_creds()
        print(f"✓ Autenticado! Token salvo em: {_TOKEN_FILE}")
        print("\nTestando Gmail...")
        r = ler_emails("is:unread", max_results=3)
        print(f"  → {r.get('total', 0)} emails não lidos encontrados.")
        print("\nTestando Calendar...")
        r = listar_eventos(dias=3)
        print(f"  → {r.get('total', 0)} eventos nos próximos 3 dias.")
        print("\n✓ Tudo funcionando. Pode usar as ferramentas na Lyra.")
    except FileNotFoundError as e:
        print(f"\n[ERRO] {e}")
    except Exception as e:
        print(f"\n[ERRO] {e}")
