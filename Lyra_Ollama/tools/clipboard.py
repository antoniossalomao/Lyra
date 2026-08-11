"""tools/clipboard.py — Clipboard tools: read/write and AI-assisted clipboard processing."""

import os

def ler_clipboard() -> dict:
    """Lê texto atual da área de transferência (Ctrl+C)."""
    try:
        import pyperclip
        texto = pyperclip.paste()
        return {"texto": texto, "ok": True}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def escrever_clipboard(texto: str) -> dict:
    """Escreve texto na área de transferência."""
    try:
        import pyperclip
        pyperclip.copy(texto)
        return {"ok": True, "bytes": len(texto.encode())}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def analisar_clipboard_com_ia(instrucao: str = "") -> dict:
    """
    Lê o clipboard atual e usa a IA para processá-lo conforme a instrução.
    Se nenhuma instrução for dada, oferece: resumir, corrigir, traduzir ou explicar.
    Coloca o resultado de volta no clipboard E retorna o texto.
    Exemplo: 'traduza para inglês', 'corrija o português', 'resuma em 3 pontos'.
    """
    try:
        import pyperclip
        texto = pyperclip.paste()
        if not texto or not texto.strip():
            return {"ok": False, "erro": "Clipboard vazio ou não contém texto."}

        texto = texto.strip()
        if len(texto) > 8000:
            texto = texto[:8000]
            truncado = True
        else:
            truncado = False

        gemini_key = os.environ.get("GEMINI_API_KEY")
        if gemini_key:
            try:
                from google import genai
                client = genai.Client(api_key=gemini_key)
                prompt = instrucao.strip() if instrucao.strip() else (
                    "Analise o texto abaixo e faça o que for mais útil: "
                    "corrija erros, resuma se longo, ou explique se for código/técnico. "
                    "Seja direto, sem preâmbulo."
                )
                resp = client.models.generate_content(
                    model="gemini-3.5-flash",
                    contents=f"{prompt}\n\n---\n{texto}",
                )
                resultado = resp.text.strip()
                via = "gemini"
            except Exception:
                resultado = None
                via = None
        else:
            resultado = None
            via = None

        if not resultado:
            from ollama import Client as OllamaClient
            c = OllamaClient(host="http://127.0.0.1:11434")
            prompt = instrucao.strip() if instrucao.strip() else (
                "Analise e melhore o texto abaixo. Se for código, explique. "
                "Se for longo, resuma. Se tiver erros, corrija. Seja direto."
            )
            res = c.chat(
                model="Lyra",
                messages=[
                    {"role": "system", "content": "Você é um assistente preciso. Responda apenas com o resultado, sem comentários extras."},
                    {"role": "user", "content": f"{prompt}\n\n---\n{texto}"},
                ],
            )
            resultado = res["message"]["content"].strip()
            via = "local"

        pyperclip.copy(resultado)

        return {
            "ok": True,
            "original_chars": len(texto),
            "truncado": truncado,
            "resultado": resultado,
            "via": via,
            "info": "Resultado copiado para o clipboard.",
        }
    except ImportError:
        return {"ok": False, "erro": "pyperclip não instalado: pip install pyperclip"}
    except Exception as e:
        return {"ok": False, "erro": str(e)}


SCHEMA = [
        {
            "type": "function",
            "function": {
                "name": "ler_clipboard",
                "description": "Lê clipboard (Ctrl+C).",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "escrever_clipboard",
                "description": "Escreve no clipboard (Ctrl+V).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "texto": {"type": "string"}
                    },
                    "required": ["texto"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "analisar_clipboard_com_ia",
                "description": "Lê o conteúdo do clipboard e processa com IA conforme instrução. Útil para traduzir, resumir, corrigir ou explicar o que o usuário acabou de copiar. O resultado é colocado de volta no clipboard.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "instrucao": {"type": "string", "description": "O que fazer com o texto do clipboard (ex: 'traduza para inglês', 'corrija o português', 'explique esse código'). Se omitido, a IA decide o que é mais útil."},
                    },
                },
            },
        },
]


MAP = {
    "ler_clipboard": ler_clipboard,
    "escrever_clipboard": escrever_clipboard,
    "analisar_clipboard_com_ia": analisar_clipboard_com_ia,
}
