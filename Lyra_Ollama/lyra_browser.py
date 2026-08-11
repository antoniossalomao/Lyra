"""
lyra_browser.py — Navegação web controlada por IA (browser-use + Playwright).

Expõe navegar_web(objetivo, url_inicial) que instrui um agente LLM a operar
um browser real (Chromium headless) para alcançar um objetivo:
  - Preencher formulários, clicar em botões, navegar entre páginas
  - Coletar dados de sites que exigem JS / login
  - Fluxos multi-passo que pesquisar_internet / buscar_url não alcançam

DEPENDÊNCIAS (já instaladas):
  pip install browser-use langchain-google-genai

PRIMEIRA VEZ (baixa Playwright Chromium ~150MB):
  python -m playwright install chromium
"""

import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import asyncio
import os
import threading
from typing import Optional


async def _run_agent(objetivo: str, url_inicial: str, api_key: str) -> str:
    from browser_use import Agent
    from browser_use.llm.google.chat import ChatGoogle

    # browser-use 0.13.x tem abstração própria de LLM (browser_use.llm.*),
    # não aceita mais objetos langchain_google_genai.ChatGoogleGenerativeAI
    # direto (falha com "object has no attribute 'provider'").
    # gemini-2.0-flash tem quota FREE TIER = 0 nesta conta (modelo velho,
    # sem free tier mais) — 2.5-flash é o que tem quota real disponível.
    llm = ChatGoogle(
        model="gemini-2.5-flash",
        api_key=api_key,
        temperature=0.1,
    )

    task = objetivo
    if url_inicial:
        task = f"Comece em {url_inicial} e então: {objetivo}"

    agent = Agent(task=task, llm=llm)
    result = await agent.run(max_steps=20)

    if hasattr(result, "final_result"):
        return result.final_result() or str(result)
    return str(result)


def navegar_web(objetivo: str, url_inicial: str = "") -> dict:
    """
    Abre um browser real (Chromium) controlado por IA para completar um objetivo.
    Ideal para: login + coleta, formulários multi-passo, SPAs com JS obrigatório.
    objetivo: o que fazer no browser (ex: "buscar preço do produto X em site.com")
    url_inicial: URL para abrir primeiro (opcional — o agente pode navegar livremente)
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return {"erro": "GEMINI_API_KEY não configurada.", "ok": False}

    resultado = {}
    erro = {}

    def _thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            r = loop.run_until_complete(_run_agent(objetivo, url_inicial, api_key))
            resultado["texto"] = r
        except Exception as e:
            erro["msg"] = str(e)
        finally:
            loop.close()

    t = threading.Thread(target=_thread, daemon=True)
    t.start()
    t.join(timeout=180)

    if t.is_alive():
        return {"erro": "Timeout: browser-use demorou mais de 3 minutos.", "ok": False}
    if erro:
        msg = erro["msg"]
        if "playwright" in msg.lower() or "chromium" in msg.lower() or "executable" in msg.lower():
            return {
                "erro": (
                    "Playwright/Chromium não instalado. Rode UMA VEZ:\n"
                    "  python -m playwright install chromium\n"
                    f"Detalhe: {msg}"
                ),
                "ok": False,
            }
        return {"erro": msg, "ok": False}

    return {"ok": True, "resultado": resultado.get("texto", ""), "objetivo": objetivo}


if __name__ == "__main__":
    print("=== Teste browser-use ===")
    r = navegar_web(
        objetivo="Acesse google.com e diga qual é o título da página inicial",
        url_inicial="https://www.google.com",
    )
    if r.get("ok"):
        print(f"✓ Resultado:\n{r['resultado']}")
    else:
        print(f"✗ Erro: {r['erro']}")
