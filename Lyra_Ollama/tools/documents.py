"""tools/documents.py — Document tools: read/summarize PDFs/DOCX, generate PDF/DOCX/XLSX/HTML/TXT, transcribe audio, translate."""

import json
import os
import pathlib

def gerar_documento(tipo: str, conteudo: str, path: str,
                    titulo: str = "") -> dict:
    """
    Gera documento a partir de conteúdo em texto.
    tipo: 'pdf' | 'docx' | 'xlsx' | 'html' | 'txt'
    Para xlsx, conteudo pode ser JSON (lista de listas) ou texto separado por ';'.
    """
    try:
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        # ── txt ──
        if tipo == "txt":
            p.write_text(conteudo, encoding="utf-8")
            return {"ok": True, "path": str(p)}

        # ── html ──
        elif tipo == "html":
            if not conteudo.strip().lower().startswith("<!doctype"):
                conteudo = (
                    f'<!DOCTYPE html>\n<html lang="pt-BR">\n<head>'
                    f'<meta charset="UTF-8"><title>{titulo or "Documento"}</title>\n'
                    f'<style>body{{font-family:Inter,sans-serif;max-width:900px;'
                    f'margin:2rem auto;line-height:1.6;color:#e0e0e0;'
                    f'background:#0a0a0f}}</style>\n</head>\n<body>'
                    f'{conteudo}\n</body></html>'
                )
            p.write_text(conteudo, encoding="utf-8")
            return {"ok": True, "path": str(p)}

        # ── docx ──
        elif tipo == "docx":
            from docx import Document
            from docx.shared import Pt
            from docx.enum.text import WD_ALIGN_PARAGRAPH

            doc = Document()
            if titulo:
                h = doc.add_heading(titulo, 0)
                h.alignment = WD_ALIGN_PARAGRAPH.CENTER

            for linha in conteudo.split("\n"):
                if linha.startswith("## "):
                    doc.add_heading(linha[3:], level=1)
                elif linha.startswith("### "):
                    doc.add_heading(linha[4:], level=2)
                elif linha.startswith("#### "):
                    doc.add_heading(linha[5:], level=3)
                elif linha.startswith("- ") or linha.startswith("* "):
                    doc.add_paragraph(linha[2:], style="List Bullet")
                elif linha.startswith("1. "):
                    doc.add_paragraph(linha[3:], style="List Number")
                elif not linha.strip():
                    doc.add_paragraph("")
                else:
                    doc.add_paragraph(linha)

            doc.save(str(p))
            return {"ok": True, "path": str(p)}

        # ── pdf ──
        elif tipo == "pdf":
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import cm
            from reportlab.lib.enums import TA_JUSTIFY
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

            doc = SimpleDocTemplate(
                str(p), pagesize=A4,
                topMargin=2.5*cm, bottomMargin=2.5*cm,
                leftMargin=3*cm, rightMargin=2*cm,
            )
            styles = getSampleStyleSheet()
            corpo  = ParagraphStyle(
                "corpo", parent=styles["Normal"],
                fontSize=12, leading=18, alignment=TA_JUSTIFY,
            )
            story = []

            if titulo:
                story.append(Paragraph(titulo, styles["Title"]))
                story.append(Spacer(1, 0.5*cm))

            def _esc(s):
                return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

            for linha in conteudo.split("\n"):
                if not linha.strip():
                    story.append(Spacer(1, 0.3*cm))
                elif linha.startswith("## "):
                    story.append(Paragraph(_esc(linha[3:]), styles["Heading1"]))
                elif linha.startswith("### "):
                    story.append(Paragraph(_esc(linha[4:]), styles["Heading2"]))
                else:
                    story.append(Paragraph(_esc(linha), corpo))

            doc.build(story)
            return {"ok": True, "path": str(p)}

        # ── xlsx ──
        elif tipo == "xlsx":
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill, Alignment

            wb = Workbook()
            ws = wb.active
            ws.title = titulo[:31] if titulo else "Dados"

            try:
                dados = json.loads(conteudo)
            except json.JSONDecodeError:
                dados = [linha.split(";")
                         for linha in conteudo.strip().split("\n") if linha.strip()]

            header_fill = PatternFill(start_color="1a1a2e",
                                      end_color="1a1a2e", fill_type="solid")
            header_font = Font(bold=True, color="00d4ff")

            for r_idx, row in enumerate(dados, 1):
                for c_idx, valor in enumerate(row, 1):
                    cell = ws.cell(row=r_idx, column=c_idx, value=valor)
                    if r_idx == 1:
                        cell.fill      = header_fill
                        cell.font      = header_font
                        cell.alignment = Alignment(horizontal="center")

            for col in ws.columns:
                max_w = max((len(str(c.value or "")) for c in col), default=10)
                ws.column_dimensions[col[0].column_letter].width = min(max_w + 4, 50)

            wb.save(str(p))
            return {"ok": True, "path": str(p)}

        else:
            return {"erro": f"Tipo inválido: {tipo}. Use: pdf, docx, xlsx, html, txt"}

    except ImportError as e:
        return {"erro": f"Dependência não instalada: {e}"}
    except Exception as e:
        return {"erro": str(e)}

def ler_documento(path: str) -> dict:
    """Extrai texto de PDF, DOCX, TXT/MD/CSV pra Lyra conseguir 'ler' documentos
    que o usuário apontar (complementa gerar_documento, que só escreve)."""
    try:
        p = pathlib.Path(path)
        if not p.exists():
            return {"erro": f"Arquivo não encontrado: {path}"}
        ext = p.suffix.lower()

        if ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(p))
            texto = "\n".join((pg.extract_text() or "") for pg in reader.pages)
        elif ext == ".docx":
            from docx import Document
            doc = Document(str(p))
            texto = "\n".join(par.text for par in doc.paragraphs)
        elif ext in (".txt", ".md", ".csv"):
            texto = p.read_text(encoding="utf-8", errors="replace")
        else:
            return {"erro": f"Extensão não suportada: {ext}. Use pdf, docx, txt, md ou csv."}

        texto = texto.strip()
        return {
            "ok": True, "path": str(p), "caracteres": len(texto),
            "conteudo": texto[:8000], "truncado": len(texto) > 8000,
        }
    except ImportError as e:
        return {"erro": f"Dependência não instalada: {e}", "ok": False}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def resumir_documento(path: str, foco: str = "") -> dict:
    """
    Resume um documento (PDF, DOCX, TXT/MD/CSV) inteiro via Gemini 2.5 Flash
    — diferente de ler_documento (que corta em 8000 caracteres), usa o
    contexto de ~1M tokens do Gemini pra processar o documento completo sem
    truncar. 'foco' é opcional (ex: 'só a parte financeira').
    """
    try:
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if not gemini_key:
            return {"erro": "GEMINI_API_KEY não configurada.", "ok": False}

        p = pathlib.Path(path)
        if not p.exists():
            return {"erro": f"Arquivo não encontrado: {path}"}
        ext = p.suffix.lower()

        if ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(p))
            texto = "\n".join((pg.extract_text() or "") for pg in reader.pages)
        elif ext == ".docx":
            from docx import Document
            doc = Document(str(p))
            texto = "\n".join(par.text for par in doc.paragraphs)
        elif ext in (".txt", ".md", ".csv"):
            texto = p.read_text(encoding="utf-8", errors="replace")
        else:
            return {"erro": f"Extensão não suportada: {ext}. Use pdf, docx, txt, md ou csv."}

        texto = texto.strip()
        if not texto:
            return {"erro": "Documento vazio ou sem texto extraível.", "ok": False}

        from google import genai
        client = genai.Client(api_key=gemini_key)
        instrucao = f"Resuma o documento abaixo em PT-BR, de forma clara e organizada."
        if foco:
            instrucao += f" Foque especificamente em: {foco}."
        resp = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=f"{instrucao}\n\n---DOCUMENTO---\n{texto}",
        )
        return {"ok": True, "path": str(p), "caracteres_originais": len(texto), "resumo": resp.text}
    except ImportError as e:
        return {"erro": f"Dependência não instalada: {e}", "ok": False}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def transcrever_audio(path: str) -> dict:
    """
    Transcreve um arquivo de áudio ou vídeo (mp3, wav, m4a, mp4, etc.) via
    Gemini 2.5 Flash, que entende áudio nativamente — sem precisar de
    Whisper local. Útil pra transcrever audios que o usuário anexar/apontar.
    """
    try:
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if not gemini_key:
            return {"erro": "GEMINI_API_KEY não configurada.", "ok": False}

        p = pathlib.Path(path)
        if not p.exists():
            return {"erro": f"Arquivo não encontrado: {path}"}

        mime_por_ext = {
            ".mp3": "audio/mp3", ".wav": "audio/wav", ".m4a": "audio/mp4",
            ".ogg": "audio/ogg", ".flac": "audio/flac",
            ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
        }
        mime = mime_por_ext.get(p.suffix.lower())
        if not mime:
            return {"erro": f"Extensão não suportada: {p.suffix}. Use mp3, wav, m4a, ogg, flac, mp4, mov ou webm."}

        from google import genai
        from google.genai import types
        client = genai.Client(api_key=gemini_key)
        dados = p.read_bytes()
        resp = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=[
                types.Part.from_bytes(data=dados, mime_type=mime),
                "Transcreva o áudio/fala deste arquivo, em português, na íntegra. "
                "Se houver várias pessoas falando, indique quem fala quando for óbvio do contexto.",
            ],
        )
        return {"ok": True, "path": str(p), "transcricao": resp.text}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def traduzir_texto(texto: str, idioma_destino: str = "en") -> dict:
    """Traduz um texto usando o próprio modelo Ollama local 'Lyra' — sem
    depender de nenhuma API externa de tradução."""
    try:
        from ollama import Client
        c = Client(host="http://127.0.0.1:11434")
        res = c.chat(
            model="Lyra",
            messages=[
                {"role": "system", "content": (
                    f"Você é um tradutor. Traduza o texto do usuário para o idioma "
                    f"'{idioma_destino}'. Responda APENAS com a tradução, sem comentários, "
                    f"explicações ou aspas extras.")},
                {"role": "user", "content": texto},
            ],
        )
        traducao = res["message"]["content"].strip()
        return {"ok": True, "original": texto, "idioma_destino": idioma_destino, "traducao": traducao}
    except Exception as e:
        return {"erro": str(e), "ok": False}


SCHEMA = [
        {
            "type": "function",
            "function": {
                "name": "gerar_documento",
                "description": "Cria PDF/Docx/Xlsx.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tipo":     {"type": "string"},
                        "conteudo": {"type": "string"},
                        "path":     {"type": "string"},
                        "titulo":   {"type": "string"},
                    },
                    "required": ["tipo", "conteudo", "path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ler_documento",
                "description": "Extrai texto de PDF, DOCX, TXT, MD ou CSV (corta em 8000 caracteres).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "resumir_documento",
                "description": "Resume um documento INTEIRO (PDF/DOCX/TXT/MD/CSV) sem truncar, via IA — use pra documentos grandes em vez de ler_documento.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "foco": {"type": "string", "description": "Opcional: em que parte focar o resumo."},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "transcrever_audio",
                "description": "Transcreve um arquivo de áudio ou vídeo (mp3, wav, m4a, ogg, flac, mp4, mov, webm) pra texto.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "traduzir_texto",
                "description": "Traduz um texto pro idioma indicado usando o modelo local.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "texto":          {"type": "string"},
                        "idioma_destino": {"type": "string"},
                    },
                    "required": ["texto"],
                },
            },
        },
]


MAP = {
    "gerar_documento": gerar_documento,
    "ler_documento": ler_documento,
    "resumir_documento": resumir_documento,
    "transcrever_audio": transcrever_audio,
    "traduzir_texto": traduzir_texto,
}
