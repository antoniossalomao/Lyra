"""tools/vision.py — Screen/image tools: screenshots with OCR, screen description, image analysis and generation."""

import os
import pathlib
import time

def capturar_tela(ocr: bool = True, monitor: int = 1) -> dict:
    """
    Captura screenshot + extrai texto via EasyOCR (GPU).
    Salva em Lyra_Core/Sons/cache/screenshot_<ts>.png
    """
    try:
        import mss
        import mss.tools

        output_dir = (pathlib.Path(__file__).parent.parent
                      / "Lyra_Core" / "Sons" / "cache")
        output_dir.mkdir(parents=True, exist_ok=True)
        ts       = int(time.time())
        img_path = output_dir / f"screenshot_{ts}.png"

        with mss.mss() as sct:
            mon     = sct.monitors[monitor]
            sct_img = sct.grab(mon)
            mss.tools.to_png(sct_img.rgb, sct_img.size, output=str(img_path))

        resultado = {
            "ok":        True,
            "path":      str(img_path),
            "resolucao": f"{sct_img.width}x{sct_img.height}",
        }

        if ocr:
            try:
                import easyocr
                reader = easyocr.Reader(["pt", "en"], gpu=True, verbose=False)
                textos = reader.readtext(str(img_path), detail=0)
                resultado["texto_ocr"]         = "\n".join(textos)
                resultado["linhas_detectadas"] = len(textos)
            except Exception as e:
                resultado["ocr_erro"] = str(e)

        return resultado
    except Exception as e:
        return {"erro": str(e), "ok": False}

def explicar_tela(pergunta: str = "") -> dict:
    """
    Tira um print da tela e descreve o conteúdo visual. Tenta Gemini 2.5
    Flash (visão multimodal, muito mais preciso) primeiro; se a API falhar
    (sem internet/sem cota), cai pro llava-phi3 local (~2.9GB, sobe na VRAM
    só pra essa chamada e descarrega na hora — keep_alive=0). Diferente de
    capturar_tela (que só faz OCR de texto), isso entende imagem/ícone/jogo.
    """
    try:
        captura = capturar_tela(ocr=False)
        if not captura.get("ok"):
            return captura

        texto_pergunta = pergunta.strip() or "Descreva detalhadamente o que aparece nesta tela."

        gemini_key = os.environ.get("GEMINI_API_KEY")
        if gemini_key:
            try:
                from google import genai
                from google.genai import types
                client = genai.Client(api_key=gemini_key)
                with open(captura["path"], "rb") as f:
                    img_bytes = f.read()
                resp = client.models.generate_content(
                    model="gemini-3.5-flash",
                    contents=[
                        types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                        texto_pergunta,
                    ],
                )
                return {"ok": True, "descricao": resp.text, "screenshot": captura["path"], "via": "gemini"}
            except Exception as e:
                # Antes: exceção descartada em silêncio — se o Gemini quebrasse
                # (nome de modelo errado, cota, rede), a degradação pro llava-phi3
                # nunca aparecia em lugar nenhum. Acabamos de achar exatamente
                # esse tipo de bug hoje (modelo Gemini errado em outra função).
                print(f"[explicar_tela] Gemini Vision falhou, caindo para llava-phi3 local: {e}")

        from ollama import Client
        c = Client(host='http://127.0.0.1:11434')
        with open(captura["path"], "rb") as f:
            img_bytes = f.read()
        res = c.chat(
            model="llava-phi3",
            messages=[{"role": "user", "content": texto_pergunta, "images": [img_bytes]}],
            keep_alive=0,
        )
        return {"ok": True, "descricao": res["message"]["content"], "screenshot": captura["path"], "via": "local"}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def analisar_imagem(path: str, pergunta: str = "") -> dict:
    """
    Analisa um arquivo de imagem (ex: colada/anexada no chat pelo usuário)
    via Gemini Vision — diferente de explicar_tela (que tira um print da
    tela atual), isso analisa uma imagem já existente em disco.
    """
    try:
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if not gemini_key:
            return {"erro": "GEMINI_API_KEY não configurada.", "ok": False}
        p = pathlib.Path(path)
        if not p.exists():
            return {"erro": f"Arquivo não encontrado: {path}"}

        mime_por_ext = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp"}
        mime = mime_por_ext.get(p.suffix.lower())
        if not mime:
            return {"erro": f"Extensão não suportada: {p.suffix}. Use png, jpg, jpeg, webp, gif ou bmp."}

        # Detecta o formato real pelos bytes — um arquivo salvo com extensão
        # errada (ex: Pollinations devolve JPEG mesmo com nome .png) faz o
        # Gemini rejeitar com 503 se o mime_type declarado não bater com o
        # conteúdo real.
        assinatura = p.read_bytes()[:12]
        if assinatura.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif assinatura.startswith(b"\x89PNG"):
            mime = "image/png"
        elif assinatura[:4] == b"RIFF" and assinatura[8:12] == b"WEBP":
            mime = "image/webp"
        elif assinatura.startswith(b"GIF8"):
            mime = "image/gif"

        from google import genai
        from google.genai import types
        client = genai.Client(api_key=gemini_key)
        texto_pergunta = pergunta.strip() or "Descreva detalhadamente o que aparece nesta imagem."
        resp = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=[types.Part.from_bytes(data=p.read_bytes(), mime_type=mime), texto_pergunta],
        )
        return {"ok": True, "path": str(p), "descricao": resp.text}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def gerar_imagem(prompt: str, path: str = "") -> dict:
    """
    Gera uma imagem a partir de uma descrição em texto, via Pollinations.ai
    (gratuito, sem API key, sem limite de cota — usa Flux por baixo).
    Sempre salva em Lyra_Core/Sons/cache/imagens/ — mesmo se 'path' vier
    preenchido, só o nome do arquivo é usado (sem pasta), porque essa pasta é
    a que o cerebro_maestro serve publicamente em /imagens pra exibir a
    imagem inline no chat. Um 'path' com pasta própria quebraria essa URL.
    """
    try:
        import requests
        from urllib.parse import quote

        pasta = (pathlib.Path(__file__).parent.parent / "Lyra_Core" / "Sons" / "cache" / "imagens")
        pasta.mkdir(parents=True, exist_ok=True)

        url = f"https://image.pollinations.ai/prompt/{quote(prompt)}"
        r = requests.get(url, timeout=60)
        r.raise_for_status()

        # Pollinations sempre devolve JPEG, mesmo que o nome sugerido tenha
        # outra extensão — usar o Content-Type real evita salvar um arquivo
        # com extensão errada (já causou erro 503 no Gemini, que valida o
        # mime_type declarado contra os bytes reais da imagem).
        content_type = r.headers.get("Content-Type", "image/jpeg")
        ext_real = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(content_type, ".jpg")
        nome_base = pathlib.Path(path).stem if path else f"img_{int(time.time())}"
        destino = pasta / f"{nome_base}{ext_real}"
        destino.write_bytes(r.content)
        # URL pública servida pelo cerebro_maestro (mount /imagens) — o
        # frontend renderiza isso inline no chat via markdown ![](url).
        url_publica = f"http://127.0.0.1:8000/imagens/{destino.name}"
        return {"ok": True, "path": str(destino), "url": url_publica,
                "prompt": prompt, "bytes": len(r.content),
                "instrucao": "Inclua a imagem na resposta com markdown: ![imagem](URL_ACIMA)"}
    except Exception as e:
        return {"erro": str(e), "ok": False}


SCHEMA = [
        {
            "type": "function",
            "function": {
                "name": "capturar_tela",
                "description": "Tira um print e extrai texto.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ocr":     {"type": "boolean"},
                        "monitor": {"type": "integer"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "explicar_tela",
                "description": "Tira um print e descreve VISUALMENTE o conteúdo (imagem/ícone/diagrama/jogo) — use quando o usuário perguntar 'o que é isso na tela' / 'explica isso aí' / 'o que eu tô vendo'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pergunta": {"type": "string", "description": "O que o usuário quer saber sobre a tela (opcional, default descreve tudo)."},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "analisar_imagem",
                "description": "Analisa uma imagem já existente em disco (ex: colada/anexada pelo usuário no chat) — diferente de explicar_tela, que tira print da tela atual.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "pergunta": {"type": "string", "description": "O que perguntar sobre a imagem (opcional)."},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "gerar_imagem",
                "description": "Gera uma imagem a partir de uma descrição em texto (ex: 'um gato astronauta'). Use quando o usuário pedir pra criar/desenhar/gerar uma imagem.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Descrição da imagem a gerar, em qualquer idioma."},
                        "path": {"type": "string", "description": "Caminho de destino (opcional)."},
                    },
                    "required": ["prompt"],
                },
            },
        },
]


MAP = {
    "capturar_tela": capturar_tela,
    "explicar_tela": explicar_tela,
    "analisar_imagem": analisar_imagem,
    "gerar_imagem": gerar_imagem,
}
