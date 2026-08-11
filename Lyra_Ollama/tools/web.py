"""tools/web.py — Web tools: DuckDuckGo search, AI-grounded search, URL scraping, AI browser automation, weather."""

import os
import time

_CACHE_BUSCA_IA: dict[str, tuple[float, dict]] = {}  # query normalizada -> (timestamp, resultado)
_CACHE_BUSCA_IA_TTL_S = 3600  # 1h — perguntas repetidas não gastam cota de novo

def pesquisar_internet(query: str, limit: int = 3) -> dict:
    """Busca anônima na internet via DuckDuckGo."""
    try:
        from ddgs import DDGS
        resultados = list(DDGS().text(query, max_results=limit))
        return {"query": query, "resultados": resultados, "ok": True}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def pesquisar_com_ia(query: str) -> dict:
    """
    Busca na internet com IA + grounding do Google (via Gemini) — diferente
    de pesquisar_internet (DuckDuckGo, snippets crus), isso devolve uma
    resposta já sintetizada e atual, com as fontes usadas. Exige
    GEMINI_API_KEY; sem ela, use pesquisar_internet como alternativa offline.
    Cacheia por 1h — a mesma pergunta repetida não gasta cota de novo.
    """
    chave = query.strip().lower()
    cache_hit = _CACHE_BUSCA_IA.get(chave)
    if cache_hit and (time.time() - cache_hit[0]) < _CACHE_BUSCA_IA_TTL_S:
        return {**cache_hit[1], "cache": True}

    try:
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if not gemini_key:
            return {"erro": "GEMINI_API_KEY não configurada — use pesquisar_internet.", "ok": False}
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=gemini_key)
        cfg = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())])
        resp = client.models.generate_content(model="gemini-3.5-flash", contents=query, config=cfg)

        fontes = []
        gm = resp.candidates[0].grounding_metadata if resp.candidates else None
        if gm and gm.grounding_chunks:
            fontes = [{"titulo": c.web.title, "url": c.web.uri} for c in gm.grounding_chunks if c.web]

        resultado = {"ok": True, "query": query, "resposta": resp.text, "fontes": fontes}
        _CACHE_BUSCA_IA[chave] = (time.time(), resultado)
        return {**resultado, "cache": False}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def buscar_url(url: str, max_chars: int = 6000) -> dict:
    """Busca e extrai o texto principal de uma URL. Usa Crawl4AI (Markdown limpo,
    suporta páginas JS/SPA) com fallback para requests+BeautifulSoup."""
    # Tenta Crawl4AI em thread separada para não conflitar com o event loop do FastAPI
    try:
        import asyncio, threading
        from crawl4ai import AsyncWebCrawler

        resultado = [None]
        erro_crawl = [None]

        def _run_crawl4ai():
            async def _crawl():
                async with AsyncWebCrawler(headless=True, verbose=False) as crawler:
                    r = await crawler.arun(url=url)
                    return r
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                resultado[0] = loop.run_until_complete(_crawl())
            except Exception as e:
                erro_crawl[0] = str(e)
            finally:
                loop.close()

        t = threading.Thread(target=_run_crawl4ai, daemon=True)
        t.start()
        t.join(timeout=25)

        if resultado[0] and resultado[0].success and resultado[0].markdown:
            md = resultado[0].markdown.strip()
            titulo = resultado[0].metadata.get("title", "") if resultado[0].metadata else ""
            return {
                "ok": True, "url": url, "titulo": titulo,
                "conteudo": md[:max_chars], "truncado": len(md) > max_chars,
                "via": "crawl4ai",
            }
    except Exception:
        pass

    # Fallback: requests + BeautifulSoup (sem JS, mas funciona em qualquer ambiente)
    try:
        import requests
        from bs4 import BeautifulSoup
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (LyraBot)"})
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        titulo = soup.title.string.strip() if soup.title and soup.title.string else ""
        texto = " ".join(soup.get_text(separator=" ").split())
        return {
            "ok": True, "url": url, "titulo": titulo,
            "conteudo": texto[:max_chars], "truncado": len(texto) > max_chars,
            "via": "beautifulsoup",
        }
    except Exception as e:
        return {"erro": str(e), "ok": False}

def consultar_clima(cidade: str = "Marilia") -> dict:
    """Consulta o clima atual e previsão de uma cidade via wttr.in (gratuito,
    sem API key). Default Marília-SP (cidade do Antônio)."""
    try:
        import requests
        # wttr.in com ?format=j1 devolve JSON estruturado (atual + 3 dias)
        r = requests.get(
            f"https://wttr.in/{requests.utils.quote(cidade)}?format=j1&lang=pt",
            timeout=15, headers={"User-Agent": "curl/8.0 (LyraBot)"},
        )
        r.raise_for_status()
        d = r.json()
        atual = d.get("current_condition", [{}])[0]
        area  = (d.get("nearest_area", [{}])[0] or {})
        nome_area = ""
        try:
            nome_area = area.get("areaName", [{}])[0].get("value", "")
        except Exception:
            pass
        desc = ""
        try:
            desc = atual.get("lang_pt", [{}])[0].get("value", "") or atual.get("weatherDesc", [{}])[0].get("value", "")
        except Exception:
            pass
        hoje = (d.get("weather", [{}])[0] or {})
        return {
            "ok": True,
            "cidade": nome_area or cidade,
            "temp_c": atual.get("temp_C"),
            "sensacao_c": atual.get("FeelsLikeC"),
            "descricao": desc,
            "umidade_pct": atual.get("humidity"),
            "vento_kmh": atual.get("windspeedKmph"),
            "previsao_hoje": {
                "max_c": hoje.get("maxtempC"),
                "min_c": hoje.get("mintempC"),
            },
        }
    except Exception as e:
        return {"erro": str(e), "ok": False}

def navegar_web(objetivo: str, url_inicial: str = "") -> dict:
    """Abre Chromium controlado por IA para completar um objetivo multi-passo.
    Lazy-import lyra_browser para não carregar Playwright se não for usar."""
    try:
        import lyra_browser as _lb
        return _lb.navegar_web(objetivo, url_inicial)
    except Exception as e:
        return {"erro": str(e), "ok": False}


SCHEMA = [
        {
            "type": "function",
            "function": {
                "name": "pesquisar_internet",
                "description": "Busca web.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "pesquisar_com_ia",
                "description": "Busca na internet com IA e fontes atuais (Google Search grounding) — prefira essa sobre pesquisar_internet quando precisar de uma resposta sintetizada e atualizada, não só links crus.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "buscar_url",
                "description": "Busca e extrai o texto principal de uma URL específica.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url":       {"type": "string"},
                        "max_chars": {"type": "integer"},
                    },
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "consultar_clima",
                "description": "Consulta clima atual e previsão de uma cidade (temperatura, sensação, umidade, vento). Use quando perguntarem sobre clima/tempo/temperatura de uma cidade. Default Marília-SP.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cidade": {"type": "string", "description": "Nome da cidade (ex: 'Marilia', 'Sao Paulo', 'Tokyo'). Default Marilia."},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "navegar_web",
                "description": (
                    "Abre um browser real (Chromium) controlado por IA para completar um objetivo. "
                    "Use quando pesquisar_internet/buscar_url não bastam: sites com JS obrigatório, "
                    "formulários multi-passo, login necessário, SPAs, ou quando precisar interagir "
                    "com a página (clicar, preencher, navegar entre abas). "
                    "Exemplos: 'faça login em X e me diga meu saldo', 'preencha o formulário em Y'. "
                    "ATENÇÃO: mais lento (~30s). Prefira buscar_url para simples leitura de texto."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "objetivo":    {"type": "string", "description": "O que fazer no browser (instrução completa)."},
                        "url_inicial": {"type": "string", "description": "URL para abrir primeiro (opcional)."},
                    },
                    "required": ["objetivo"],
                },
            },
        },
]


MAP = {
    "pesquisar_internet": pesquisar_internet,
    "pesquisar_com_ia": pesquisar_com_ia,
    "buscar_url": buscar_url,
    "consultar_clima": consultar_clima,
    "navegar_web": navegar_web,
}
