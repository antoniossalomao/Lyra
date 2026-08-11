"""
test_smoke.py — suite de smoke test do cerebro_maestro.py (recriado 01/07/2026;
o original documentado no README/LYRA_TECNICO.md sumiu do disco em algum
momento — nenhum arquivo test_*.py restava no projeto).

Cobre os endpoints atuais (checados via grep em cerebro_maestro.py na hora de
escrever isso — se endpoints novos forem adicionados, adicionar aqui também).
Só GET/leitura + 1 chamada de /chat opcional (--rapido pula). Não testa
POST /upload (multipart), POST /enxame (cria enxame de verdade, custa
tempo/tokens) nem DELETE /historico (destrutivo) — marcados como "não
testado" no relatório final, não como falha.

Uso:
  python test_smoke.py
  python test_smoke.py --rapido   # pula o teste de /chat (mais lento, custa tokens)
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse
import json
import time
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000"


def _get(path: str, timeout: float = 10.0):
    req = urllib.request.Request(BASE + path, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def _post(path: str, body: dict, timeout: float = 30.0):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method="POST",
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ct = r.headers.get("Content-Type", "")
        corpo = r.read().decode("utf-8")
        if "application/json" in ct:
            return r.status, json.loads(corpo)
        return r.status, corpo  # SSE (/chat) vem como text/event-stream


CHECAGENS = []


def checagem(nome):
    def deco(fn):
        CHECAGENS.append((nome, fn))
        return fn
    return deco


@checagem("GET / responde com servico ativo")
def _c1():
    status, corpo = _get("/")
    assert status == 200 and corpo.get("ativo") is True, corpo


@checagem("GET /status reporta cerebro_ativo")
def _c2():
    status, corpo = _get("/status")
    assert status == 200 and corpo.get("cerebro_ativo") is True, corpo


@checagem("GET /health responde com qdrant/surreal/ollama")
def _c3():
    status, corpo = _get("/health", timeout=15)
    assert status == 200
    for svc in ("qdrant", "surreal", "ollama"):
        assert svc in corpo, f"{svc} ausente em /health"


@checagem("GET /metrics tem cpu/ram")
def _c4():
    status, corpo = _get("/metrics")
    assert status == 200 and "cpu_pct" in corpo and "ram_pct" in corpo, corpo


@checagem("GET /stats tem total_chats e tiers")
def _c5():
    status, corpo = _get("/stats")
    assert status == 200 and "total_chats" in corpo and "tiers" in corpo, corpo


@checagem("GET /stats/historico devolve lista de snapshots")
def _c6():
    status, corpo = _get("/stats/historico?limite=5")
    assert status == 200 and isinstance(corpo.get("snapshots"), list), corpo


@checagem("GET /buscar retorna resultados estruturados")
def _c7():
    # timeout 45s: a 1ª busca pós-idle paga reativação do embedder + lazy-load
    # do BM25/reranker (~10-15s) — 15s dava falso-negativo em cold start
    status, corpo = _get("/buscar?q=capital+da+franca&top_k=3", timeout=45)
    assert status == 200 and "resultados" in corpo, str(corpo)[:200]


@checagem("GET /grafo/completo retorna nodes/links")
def _c8():
    status, corpo = _get("/grafo/completo", timeout=15)
    assert status == 200 and "nodes" in corpo and "links" in corpo, str(corpo)[:200]


@checagem("GET /grafo (query) nao quebra")
def _c9():
    status, corpo = _get("/grafo?q=teste&limite=5", timeout=15)
    assert status == 200, str(corpo)[:200]


@checagem("GET /historico retorna lista")
def _c10():
    status, corpo = _get("/historico")
    assert status == 200, str(corpo)[:200]


@checagem("GET /resumo_sessao responde")
def _c11():
    status, corpo = _get("/resumo_sessao", timeout=15)
    assert status == 200, str(corpo)[:200]


@checagem("GET /memoria/categorias responde")
def _c12():
    status, corpo = _get("/memoria/categorias", timeout=15)
    assert status == 200, str(corpo)[:200]


@checagem("GET /exportar responde")
def _c13():
    status, corpo = _get("/exportar", timeout=10)
    assert status == 200, str(corpo)[:200]


@checagem("GET /enxames responde")
def _c14():
    status, corpo = _get("/enxames", timeout=10)
    assert status == 200, str(corpo)[:200]


@checagem("GET /dashboard responde (HTML)")
def _c15():
    req = urllib.request.Request(BASE + "/dashboard", method="GET")
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.status == 200


@checagem("POST /tts/mudo alterna e restaura estado")
def _c16():
    status0, corpo0 = _get("/status")
    original = corpo0.get("tts_mudo")
    status1, _ = _post("/tts/mudo", {"mudo": not original})
    assert status1 == 200
    _, corpo2 = _get("/status")
    assert corpo2.get("tts_mudo") == (not original)
    # restaura o estado original — não deixar o TTS num estado diferente do
    # que estava antes do smoke test rodar.
    _post("/tts/mudo", {"mudo": original})
    _, corpo3 = _get("/status")
    assert corpo3.get("tts_mudo") == original


def _rodar_teste_chat():
    print("  [CHAT] Testando POST /chat (modelo=groq, sem tool)...")
    status, corpo = _post("/chat", {"texto": "responda apenas: pong", "modelo": "groq"}, timeout=30)
    assert status == 200 and "pong" in corpo.lower(), f"resposta inesperada: {corpo[:200]}"
    print("  [CHAT] OK — Groq respondeu 'pong' como esperado.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rapido", action="store_true", help="pula o teste de /chat")
    args = parser.parse_args()

    print(f"\n{'='*60}\n  test_smoke.py — {len(CHECAGENS)} checagens + endpoints\n{'='*60}\n")

    passou, falhou = 0, []
    for nome, fn in CHECAGENS:
        try:
            fn()
            print(f"  [OK]     {nome}")
            passou += 1
        except Exception as e:
            print(f"  [FALHOU] {nome} — {e}")
            falhou.append(nome)

    if not args.rapido:
        try:
            _rodar_teste_chat()
            passou += 1
        except Exception as e:
            print(f"  [FALHOU] teste de /chat — {e}")
            falhou.append("POST /chat")
    else:
        print("  [PULADO] teste de /chat (--rapido)")

    nao_testados = ["POST /upload (multipart)", "POST /enxame (custa tempo/tokens)",
                     "DELETE /historico (destrutivo)", "WEBSOCKET /ws/voice (precisa audio real)"]

    print(f"\n{'─'*60}")
    print(f"  {passou}/{passou + len(falhou)} passaram.")
    if falhou:
        print(f"  Falharam: {', '.join(falhou)}")
    print(f"  Não testados (fora do escopo de smoke test): {', '.join(nao_testados)}")
    print(f"{'─'*60}\n")

    sys.exit(1 if falhou else 0)


if __name__ == "__main__":
    main()
